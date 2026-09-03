"""Leadership metrics and the account workspace, against the real corpus.

The point of these tests is that every leadership number states what it is true
of — denominator and window — and that clicking it lands on the requests it
counted. A metric an operator cannot reach the rows of is not defensible.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from halyard.db.models import Organization, RelationshipEdge
from halyard.db.session import sessionmaker_for


@pytest.fixture(scope="module")
def busy_account(engine) -> int:
    with sessionmaker_for(engine)() as session:
        row = session.execute(
            select(Organization.id)
            .join(RelationshipEdge, RelationshipEdge.organization_id == Organization.id)
            .group_by(Organization.id)
            .order_by(func.count(RelationshipEdge.id).desc(), Organization.name)
            .limit(1)
        ).one()
    return int(row[0])


def test_every_leadership_metric_states_its_denominator_and_window(client):
    body = client.get("/api/metrics/leadership").json()
    assert body["metrics"]
    for metric in body["metrics"]:
        assert metric["definition"]
        assert metric["window"]
        assert isinstance(metric["value"], int)
        if metric["denominator"] is not None:
            assert metric["value"] <= metric["denominator"]


def test_every_metric_has_a_denominator(client):
    """A bare count is not a defensible number: it has to say what it is out of."""
    body = client.get("/api/metrics/leadership").json()
    missing = [metric["key"] for metric in body["metrics"] if metric["denominator"] is None]
    assert missing == []


def test_each_metric_drills_down_to_the_rows_it_counted(client):
    body = client.get("/api/metrics/leadership").json()
    for metric in body["metrics"]:
        view = metric["drill_down_view"]
        if view is None:
            continue
        queued = client.get("/api/queue", params={"view": view, "limit": 500}).json()
        assert queued["total"] == metric["value"], f"{metric['key']} does not reconcile with the {view} queue"


def test_ownership_metrics_preserve_the_historical_fact_without_implying_it_persists(client):
    body = client.get("/api/metrics/leadership").json()
    assert body["requests_with_operational_owner"] == body["requests_total"]
    assert body["historically_ownerless_at_ingest"] > 0
    keys = {metric["key"] for metric in body["metrics"]}
    assert "needs_ownership_review" in keys and "unowned" not in keys


def test_account_view_exposes_coverage_activity_and_provenance(client, busy_account):
    view = client.get(f"/api/accounts/{busy_account}/view").json()
    assert view["name"]
    assert view["coverage"]["connectors"]
    assert view["coverage"]["edge_count"] > 0
    assert "not an available introduction" in view["coverage"]["note"]
    for row in view["coverage"]["connectors"]:
        assert row["sources"], "every coverage row names the file it came from"
    assert view["request_count"] == len(view["active_requests"]) + len(view["settled_requests"])


def test_account_view_lists_prior_observed_introductions_only_when_observed(client, busy_account):
    view = client.get(f"/api/accounts/{busy_account}/view").json()
    for intro in view["prior_observed_introductions"]:
        assert intro["request_id"] and intro["connector"]


def test_a_live_request_appears_on_its_account_view(client, busy_account):
    name = client.get(f"/api/accounts/{busy_account}").json()["name"]
    created = client.post(
        "/api/intake/start",
        json={"raw_ask": f"Can someone introduce us to the CFO at {name}?", "requester_name": "Leadership Test"},
    )
    assert created.status_code == 201, created.text
    key = created.json()["request"]["request_id"]

    view = client.get(f"/api/accounts/{busy_account}/view").json()
    assert key in {row["request_id"] for row in view["active_requests"]}


def test_account_people_are_listed_once_however_many_affiliations_they_hold(client, busy_account):
    body = client.get(f"/api/accounts/{busy_account}/view").json()
    ids = [person["id"] for person in body["known_people"]]
    assert len(ids) == len(set(ids))


def test_a_request_under_path_review_with_no_paths_explains_the_contradiction(client):
    """State evidence and network evidence can disagree; the operator sees both."""
    rows = client.get("/api/queue", params={"view": "path_review", "limit": 500}).json()["items"]
    for row in rows:
        paths = client.get(f"/api/requests/{row['request_id']}/paths").json()
        if paths["counts"]["total"] == 0:
            assert paths["note"], f"{row['request_id']} claims path review with nothing to review and no explanation"


def test_unknown_account_is_a_404(client):
    assert client.get("/api/accounts/99999/view").status_code == 404
