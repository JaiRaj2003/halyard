"""The ten foundation invariants, one test each.

These are the promises the product makes. If one of them fails the foundation
is wrong, however green everything else is.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone

from sqlalchemy import func, select

from halyard.config import REPO_ROOT
from halyard.db.models import (
    IntroCandidatePath,
    IntroRequest,
    Person,
    RequestTarget,
)
from halyard.domain.states import SETTLED_STATES, WorkflowState
from halyard.domain.workflow import is_potentially_stale


def test_1_historical_ownerlessness_remains_measurable(session):
    ownerless = session.scalar(
        select(func.count()).select_from(IntroRequest).where(IntroRequest.was_ownerless_at_ingest.is_(True))
    )
    total = session.scalar(select(func.count()).select_from(IntroRequest))
    assert 0 < ownerless < total
    fallback = session.scalar(
        select(func.count())
        .select_from(IntroRequest)
        .where(IntroRequest.operational_owner_source == "fallback_requester")
    )
    assert fallback == ownerless
    observed = session.scalars(
        select(IntroRequest).where(IntroRequest.observed_owner_id.isnot(None))
    ).all()
    assert observed, "some historical requests do evidence an owner"
    for request in observed:
        assert request.was_ownerless_at_ingest is False
        assert request.observed_owner_evidence


def test_2_every_request_has_an_operational_owner_immediately(session, client):
    assert session.scalar(
        select(func.count()).select_from(IntroRequest).where(IntroRequest.operational_owner_id.is_(None))
    ) == 0
    body = client.post(
        "/api/requests",
        json={"requester_name": "Brand New Person", "target_account_text": "Northwind Robotics"},
    ).json()
    assert body["operational_owner_id"] is not None
    assert body["operational_owner_source"] == "fallback_requester"


def test_3_connector_and_workflow_owner_are_separate(session):
    """Being asked as a connector never makes somebody the owner.

    A connector who *says* they are taking the request does become the observed
    owner — but on the strength of that statement, which the record has to
    carry, never on the strength of appearing in ``connector_asked``.
    """
    handled = session.scalars(select(IntroRequest).where(IntroRequest.had_recorded_handling.is_(True))).all()
    assert handled
    assert {request.selected_connector_id for request in handled if request.selected_connector_id}

    routed_without_a_statement = [
        request for request in handled if request.observed_owner_id is None
    ]
    assert routed_without_a_statement, "most routed requests evidence no owner at all"
    for request in routed_without_a_statement:
        assert request.was_ownerless_at_ingest is True
        assert request.operational_owner_source == "fallback_requester"
        assert request.operational_owner_id == request.requester_id

    for request in session.scalars(select(IntroRequest).where(IntroRequest.observed_owner_id.isnot(None))).all():
        assert "Slack" in request.observed_owner_evidence


def test_4_a_no_path_request_keeps_an_owner_and_a_next_action(session, client):
    body = client.post(
        "/api/requests",
        json={"requester_name": "Brand New Person", "target_account_text": "A Company With No Observable Path Ltd"},
    ).json()
    assert body["workflow_state"] in {
        WorkflowState.NO_OBSERVABLE_PATH.value,
        WorkflowState.NEEDS_ENTITY_REVIEW.value,
    }
    assert body["operational_owner_id"] is not None
    assert body["next_action"] and body["next_action_due_at"]

    without_paths = [
        request
        for request in session.scalars(select(IntroRequest)).all()
        if session.scalar(
            select(func.count()).select_from(IntroCandidatePath).where(IntroCandidatePath.request_id == request.id)
        )
        == 0
    ]
    assert without_paths
    for request in without_paths:
        assert request.operational_owner_id is not None
        if request.workflow_state not in {state.value for state in SETTLED_STATES}:
            assert request.next_action and request.next_action_due_at


def test_5_a_candidate_path_never_implies_an_intro_is_available(session, client):
    banned = ("intro_available", "can_intro", "intro_possible", "guaranteed")
    for path in session.scalars(select(IntroCandidatePath).limit(200)).all():
        assert path.limitations
        assert path.observability in {"historically_observable", "snapshot_only", "post_dates_request"}
    columns = {column.name for column in IntroCandidatePath.__table__.columns}
    assert not any(term in column for column in columns for term in banned)
    request_id = client.get("/api/requests", params={"limit": 1}).json()["items"][0]["request_id"]
    body = client.get(f"/api/requests/{request_id}/paths").json()
    assert "never" not in body["disclaimer"].split(".")[0] or "evidence" in body["disclaimer"]
    assert not any(term in str(body) for term in banned)


def test_6_unresolved_target_intent_does_not_create_a_person(session):
    personas = session.scalars(
        select(RequestTarget).where(RequestTarget.resolution_status != "resolved")
    ).all()
    assert personas
    for target in personas:
        assert target.resolved_person_id is None
    titles = {target.raw_target_title.casefold() for target in personas if target.raw_target_title}
    assert titles
    for title in list(titles)[:20]:
        assert session.scalar(
            select(func.count()).select_from(Person).where(func.lower(Person.display_name) == title)
        ) == 0


def test_7_same_account_activity_is_not_automatically_a_duplicate(client):
    seen = set()
    for item in client.get("/api/requests", params={"limit": 60}).json()["items"]:
        body = client.get(f"/api/requests/{item['request_id']}/related").json()
        assert "parallel activity to coordinate" in body["note"]
        for related in body["related"]:
            seen.add(related["relation_type"])
            assert "duplicate" not in related["relation_type"]
    assert "same_canonical_account" in seen


def test_8_live_application_time_is_not_the_audit_clock(client):
    now = datetime.fromisoformat(client.get("/api/health").json()["as_of"].replace("Z", "+00:00"))
    assert now != datetime(2026, 8, 10, tzinfo=timezone.utc)
    body = client.post(
        "/api/requests",
        json={"requester_name": "Brand New Person", "target_account_text": "Northwind Robotics"},
    ).json()
    assert body["age_days"] == 0
    assert body["potentially_stale"] is False


def test_9_staleness_does_not_determine_state_or_outcome(session, settings):
    now = datetime(2026, 12, 31, tzinfo=timezone.utc)
    stale_states = set()
    for request in session.scalars(select(IntroRequest)).all():
        if is_potentially_stale(request.workflow_state, request.last_activity_at, now, settings):
            stale_states.add(request.workflow_state)
            assert request.outcome != "NO_INTRO" or request.state_source in {
                "explicit_statement",
                "operator_transition",
            }
    assert len(stale_states) > 1, "staleness cuts across states rather than defining one"
    completed = session.scalars(
        select(IntroRequest).where(IntroRequest.workflow_state == WorkflowState.COMPLETED.value)
    ).all()
    for request in completed:
        assert not is_potentially_stale(request.workflow_state, request.last_activity_at, now, settings)


def test_10_the_forensic_audit_still_reproduces(tmp_path):
    """The audit and the product share one matching implementation, and it still works."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "analysis/tests", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-2000:]
