"""Two promises this system makes about how it reports itself.

First: the corpus was imported, not managed. A due date this system stamped on
a request at import is a remediation target, and reporting it as a breached SLA
would be a claim about a period in which Halyard did not exist. Only actions
Halyard assigned can be judged against Halyard's clock.

Second: a route somebody named in a thread is not nothing. It is not a
candidate path either — the network does not corroborate it — so it is reported
as a lead to validate, distinct from the case where no route signal exists at
all.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from halyard.db.models import IntroRequest, Organization, RelationshipEdge
from halyard.db.session import sessionmaker_for
from halyard.domain.states import WorkflowState
from halyard.domain.workflow import (
    CORROBORATED_PATH,
    INGEST_ASSIGNED,
    NO_ROUTE_SIGNAL,
    UNVERIFIED_SUGGESTED_ROUTE,
    is_sla_managed,
)
from halyard.ingest.requests import derive_unevidenced_state
from halyard.matching.slack import suggested_route_person


def start(client, ask: str) -> dict:
    response = client.post("/api/intake/start", json={"raw_ask": ask, "requester_name": "Dana Okafor"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(scope="module")
def unconnected_account(engine) -> str:
    with sessionmaker_for(engine)() as session:
        name = session.execute(
            select(Organization.name)
            .outerjoin(RelationshipEdge, RelationshipEdge.organization_id == Organization.id)
            .where(Organization.is_crm_account.is_(True))
            .group_by(Organization.id)
            .having(func.count(RelationshipEdge.id) == 0)
            .order_by(Organization.name)
            .limit(1)
        ).scalar()
    if name is None:
        pytest.skip("every CRM account has an observed relationship")
    return str(name)


@pytest.fixture(scope="module")
def connected_account(engine) -> str:
    with sessionmaker_for(engine)() as session:
        return str(
            session.execute(
                select(Organization.name)
                .join(RelationshipEdge, RelationshipEdge.organization_id == Organization.id)
                .group_by(Organization.id)
                .order_by(func.count(RelationshipEdge.id).desc(), Organization.name)
                .limit(1)
            ).scalar()
        )


# FIX 1 — legacy backlog is not an SLA breach


def test_imported_requests_carry_the_ingest_stamp_not_an_operator_one(session):
    imported = session.scalars(
        select(IntroRequest).where(IntroRequest.origin == "historical_corpus")
    ).all()
    assert imported
    assert all(request.next_action_source == INGEST_ASSIGNED for request in imported)
    assert not any(is_sla_managed(request.next_action_source) for request in imported)


def test_imported_requests_never_report_as_breached_however_overdue(client):
    rows = client.get("/api/queue", params={"view": "all", "limit": 500}).json()["items"]
    imported = [row for row in rows if row["origin"] == "historical_corpus"]
    assert imported
    assert any(row["is_overdue"] for row in imported), "the corpus should still have passed due dates"
    assert not any(row["sla_breached"] for row in imported)
    assert all(row["legacy_backlog"] for row in imported)


def test_live_sla_metrics_are_not_inflated_by_the_imported_corpus(client):
    metrics = {row["key"]: row for row in client.get("/api/metrics/leadership").json()["metrics"]}
    rows = client.get("/api/queue", params={"view": "all", "limit": 500}).json()["items"]
    live_breaches = sum(1 for row in rows if row["sla_breached"])
    assert metrics["overdue"]["value"] == live_breaches
    assert metrics["stale"]["value"] == sum(1 for row in rows if row["potentially_stale"] and row["sla_managed"])
    #: The corpus is large and every one of its due dates has passed; if it were
    #: counted, these numbers would be in the hundreds.
    assert metrics["overdue"]["value"] < len(rows)


def test_leadership_separates_legacy_backlog_from_current_health(client):
    body = client.get("/api/metrics/leadership").json()
    groups = {row["key"]: row["group"] for row in body["metrics"]}
    assert groups["legacy_backlog"] == "legacy_backlog"
    assert groups["legacy_backlog_quiet"] == "legacy_backlog"
    assert groups["legacy_backlog_remediation"] == "legacy_backlog"
    assert groups["overdue"] == "current_workflow"
    assert groups["stale"] == "current_workflow"
    for row in body["metrics"]:
        assert row["window"]
        assert row["denominator"] is None or row["denominator"] >= row["value"]
    assert body["imported_requests_total"] > 0
    assert "SLA" not in " ".join(
        row["definition"] for row in body["metrics"] if row["group"] == "legacy_backlog"
    ).replace("missed SLAs", "")


def test_legacy_backlog_metrics_reconcile_with_their_queue_views(client):
    metrics = {row["key"]: row for row in client.get("/api/metrics/leadership").json()["metrics"]}
    counts = client.get("/api/queue", params={"view": "all"}).json()["counts"]
    for key in ("legacy_backlog", "legacy_backlog_quiet", "legacy_backlog_remediation"):
        assert metrics[key]["value"] == counts[key]
        assert metrics[key]["drill_down_view"] == key


def test_a_new_live_request_is_judged_by_the_application_clock(client, connected_account, clock):
    payload = start(client, f"Can someone introduce us to the VP of Sales at {connected_account}?")
    request = payload["request"]
    assert request["sla_managed"] is True
    assert request["legacy_backlog"] is False
    assert request["is_overdue"] is False
    assert request["days_since_activity"] == 0
    assert request["next_action_due_at"] > clock.now().isoformat()


def test_working_a_legacy_request_brings_it_under_halyard(client):
    backlog = client.get("/api/queue", params={"view": "legacy_backlog", "limit": 1}).json()["items"]
    item = backlog[0]
    body = client.post(
        f"/api/requests/{item['request_id']}/transition",
        json={"to_state": WorkflowState.BLOCKED.value, "actor": "ops", "note": "picked this up, waiting on legal"},
    )
    assert body.status_code == 200, body.text
    updated = body.json()
    assert updated["sla_managed"] is True
    assert updated["legacy_backlog"] is False
    assert updated["is_overdue"] is False


# FIX 2 — a suggested route is neither a path nor nothing


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Priya Raman said she knows their CISO", "Priya Raman"),
        ("adding Dana Okafor who might know someone there", "Dana Okafor"),
        ("Ask Marcus Webb, he has a line into the security org", "Marcus Webb"),
        ("Can someone introduce us to the VP of Security at Acme?", ""),
        ("No idea who could help with this one", ""),
    ],
)
def test_suggested_route_person_reads_people_not_sentences(text, expected):
    assert suggested_route_person(text) == expected


def test_derived_state_keeps_a_suggested_route_out_of_the_no_path_bucket():
    suggested = derive_unevidenced_state(
        was_ownerless=False, target_resolved=True, target_ambiguous=False,
        has_candidate_paths=False, declared_status="", has_suggested_route=True,
    )
    assert suggested.workflow_state == WorkflowState.PATH_REVIEW
    silent = derive_unevidenced_state(
        was_ownerless=False, target_resolved=True, target_ambiguous=False,
        has_candidate_paths=False, declared_status="", has_suggested_route=False,
    )
    assert silent.workflow_state == WorkflowState.NO_OBSERVABLE_PATH


def test_a_volunteered_route_is_a_lead_to_validate_not_a_candidate_path(client, unconnected_account):
    payload = start(
        client,
        f"Can someone introduce us to the CFO at {unconnected_account}? "
        "Priya Raman said she knows their finance team.",
    )
    request = payload["request"]
    assert request["route_signal"] == UNVERIFIED_SUGGESTED_ROUTE
    assert request["suggested_route_person"] == "Priya Raman"
    assert request["suggested_route_evidence"]
    assert request["workflow_state"] != WorkflowState.NO_OBSERVABLE_PATH.value
    #: The suggestion is never promoted: no path was invented from it.
    assert payload["paths"]["counts"]["total"] == 0
    assert "Validate the suggested route with Priya Raman" in request["next_action"]


def test_a_corroborated_path_is_reported_as_corroborated(client, connected_account):
    payload = start(client, f"Intro to the Head of Engineering at {connected_account}?")
    assert payload["paths"]["counts"]["total"] > 0
    assert payload["request"]["route_signal"] == CORROBORATED_PATH
    assert payload["request"]["suggested_route_person"] == ""


def test_no_route_signal_at_all_stays_no_route_signal(client, unconnected_account):
    payload = start(client, f"Can someone introduce us to the CFO at {unconnected_account}?")
    request = payload["request"]
    assert request["route_signal"] == NO_ROUTE_SIGNAL
    assert request["workflow_state"] == WorkflowState.NO_OBSERVABLE_PATH.value
    assert request["next_action"]
    assert request["operational_owner_id"]


def test_rejecting_every_path_leaves_a_suggestion_standing(client, connected_account):
    payload = start(
        client,
        f"Intro to the VP of Sales at {connected_account}? Marcus Webb said he has a contact there.",
    )
    request_id = payload["request"]["request_id"]
    for path in payload["paths"]["paths"]:
        response = client.post(
            f"/api/requests/{request_id}/route",
            json={"path_id": path["id"], "decision": "reject", "note": "not viable"},
        )
        assert response.status_code == 200, response.text
    final = client.get(f"/api/requests/{request_id}").json()
    assert final["route_signal"] == UNVERIFIED_SUGGESTED_ROUTE
    assert final["workflow_state"] == WorkflowState.PATH_REVIEW.value
    assert "Validate the suggested route" in final["next_action"]
