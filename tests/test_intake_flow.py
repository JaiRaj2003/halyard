"""The hero flow, end to end over the API, against the real supplied data.

The invariant under test throughout: from the first byte of a free-text ask
onward there is a persisted, owned request with a next action, and every later
step updates that same request rather than creating another one.
"""

from __future__ import annotations

from sqlalchemy import func, select

from halyard.db.models import IntroCandidatePath, IntroRequest, Organization, RelationshipEdge
from halyard.db.session import sessionmaker_for
from halyard.domain.states import WorkflowState


def api_engine(client):
    """The client writes to a throwaway copy of the database; read from that one."""
    return client.app.state.engine


def known_account(engine) -> Organization:
    with sessionmaker_for(engine)() as session:
        return session.scalars(
            select(Organization).where(Organization.is_crm_account.is_(True)).order_by(Organization.name)
        ).first()


def connected_account(engine) -> Organization:
    """The account the network actually reaches, so path tests exercise real paths."""
    with sessionmaker_for(engine)() as session:
        row = session.execute(
            select(Organization)
            .join(RelationshipEdge, RelationshipEdge.organization_id == Organization.id)
            .group_by(Organization.id)
            .order_by(func.count(RelationshipEdge.id).desc(), Organization.name)
            .limit(1)
        ).scalars().first()
        session.expunge(row)
        return row


def start(client, **kwargs) -> dict:
    body = {"requester_name": "Dana Okafor", **kwargs}
    response = client.post("/api/intake/start", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_free_text_ask_is_persisted_and_owned_before_anything_is_resolved(client, engine):
    account = known_account(engine)
    result = start(client, raw_ask=f"Can someone introduce us to the VP of Security at {account.name}?")

    request = result["request"]
    assert request["request_id"]
    assert request["operational_owner_id"] and request["operational_owner"]
    assert request["next_action"] and request["next_action_due_at"]
    assert request["raw_ask"].startswith("Can someone introduce us")

    with sessionmaker_for(api_engine(client))() as session:
        stored = session.scalars(
            select(IntroRequest).where(IntroRequest.request_id == request["request_id"])
        ).one()
        assert stored.operational_owner_id is not None
        assert stored.raw_ask == request["raw_ask"]


def test_unparseable_ask_still_leaves_an_owned_actionable_request(client):
    result = start(client, raw_ask="hey, any chance we can get in front of someone useful this quarter?")
    request = result["request"]
    assert request["operational_owner_id"] and request["operational_owner"]
    assert request["next_action"]
    assert request["workflow_state"] in {
        WorkflowState.NEEDS_TRIAGE.value,
        WorkflowState.NEEDS_ENTITY_REVIEW.value,
        WorkflowState.NO_OBSERVABLE_PATH.value,
    }
    assert result["next_decision"]["decision"] in {"identify_account", "confirm_account"}


def test_intake_returns_parse_evidence_without_inventing_a_person(client, engine):
    account = known_account(engine)
    result = start(client, raw_ask=f"Need an intro to the VP of Security at {account.name}")
    assert result["parse"]["grammar"]
    assert result["parse"]["proposed"]["title"] == "VP of Security"
    assert result["parse"]["warnings"] or result["parse"]["proposed"]["normalized_title_family"]
    assert not result["request"]["target_detail"]["resolved_person"]


def test_known_account_yields_candidates_and_a_route_decision(client, engine):
    account = known_account(engine)
    result = start(client, raw_ask=f"Intro to the Head of Engineering at {account.name}?")
    labels = {candidate["label"] for candidate in result["account_candidates"]}
    assert account.name in labels
    assert result["next_decision"]["decision"] in {"confirm_route", "no_observable_path", "confirm_account"}


def test_paths_are_ordered_without_exposing_a_composite_score(client):
    account = connected_account(api_engine(client))
    result = start(client, raw_ask=f"Intro to the VP of Sales at {account.name}?")
    paths = result["paths"]["paths"]
    assert paths
    for path in paths:
        assert "score" not in path and "priority" not in path
        for factor in path["factors"]:
            assert "weight" not in factor
    assert paths[0]["recommendation_label"] == "Recommended to investigate first"
    assert all(path["factors"] for path in paths)
    assert [path["rank"] for path in paths] == sorted(path["rank"] for path in paths)


def test_confirming_a_route_updates_the_same_request(client):
    account = connected_account(api_engine(client))
    result = start(client, raw_ask=f"Please introduce us to the CISO at {account.name}")
    request_id = result["request"]["request_id"]
    paths = result["paths"]["paths"]
    assert paths
    response = client.post(
        f"/api/requests/{request_id}/route",
        json={"path_id": paths[0]["id"], "decision": "confirm", "note": "best evidence"},
    )
    assert response.status_code == 200, response.text
    body = response.json()["request"]
    assert body["request_id"] == request_id
    assert body["workflow_state"] == WorkflowState.AWAITING_CONNECTOR.value
    assert body["selected_connector"]
    assert body["next_action"]

    with sessionmaker_for(api_engine(client))() as session:
        stored = session.get(IntroCandidatePath, paths[0]["id"])
        assert stored.review_status == "selected"
        assert stored.reviewed_at is not None


def test_a_reviewed_path_carries_its_verdict_and_the_ask_moves_on(client):
    """The operator must see the decision they just made, on the row they made it on."""
    account = connected_account(api_engine(client))
    result = start(client, raw_ask=f"Warm intro to the Head of Security at {account.name}?")
    request_id = result["request"]["request_id"]
    paths = result["paths"]["paths"]
    assert len(paths) > 1
    assert all(path["review_status"] == "unreviewed" for path in paths)

    rejected = client.post(
        f"/api/requests/{request_id}/route",
        json={"path_id": paths[-1]["id"], "decision": "reject", "note": "left the company"},
    ).json()
    by_id = {path["id"]: path for path in rejected["paths"]["paths"]}
    assert by_id[paths[-1]["id"]]["review_status"] == "rejected"
    assert by_id[paths[-1]["id"]]["review_note"] == "left the company"
    assert rejected["next_decision"]["decision"] == "confirm_route"

    confirmed = client.post(
        f"/api/requests/{request_id}/route",
        json={"path_id": paths[0]["id"], "decision": "confirm"},
    ).json()
    selected = {path["id"]: path for path in confirmed["paths"]["paths"]}[paths[0]["id"]]
    assert selected["review_status"] == "selected"
    assert confirmed["next_decision"]["decision"] == "follow_up_connector"
    assert confirmed["request"]["next_action"] in confirmed["next_decision"]["prompt"]


def test_rejecting_every_path_leaves_the_request_active_and_owned(client):
    account = connected_account(api_engine(client))
    result = start(client, raw_ask=f"Intro to the CFO at {account.name}")
    request_id = result["request"]["request_id"]
    paths = result["paths"]["paths"]
    assert paths
    for path in paths:
        body = client.post(
            f"/api/requests/{request_id}/route",
            json={"path_id": path["id"], "decision": "reject", "note": "not viable"},
        )
        assert body.status_code == 200, body.text
    final = body.json()["request"]
    assert final["workflow_state"] == WorkflowState.NO_OBSERVABLE_PATH.value
    assert final["operational_owner_id"]
    assert final["next_action"]
    assert final["route_status"] == "ROUTE_FAILED"


def test_confirming_the_account_resolves_the_target_on_the_same_request(client, engine):
    account = known_account(engine)
    result = start(client, raw_ask="Can we get an intro to the VP of Security somewhere in fintech?")
    request_id = result["request"]["request_id"]
    response = client.post(
        f"/api/requests/{request_id}/target",
        json={"account_id": account.id, "note": "requester clarified in thread"},
    )
    assert response.status_code == 200, response.text
    body = response.json()["request"]
    assert body["request_id"] == request_id
    assert body["target_detail"]["resolution_method"] == "human_confirmation"
    assert body["workflow_state"] in {
        WorkflowState.PATH_REVIEW.value,
        WorkflowState.NO_OBSERVABLE_PATH.value,
    }


def test_confirming_the_account_stops_the_ask_being_reported_as_ambiguous(client, engine):
    """A human answer settles the question; the losing candidates stop being asked about."""
    account = known_account(engine)
    result = start(client, raw_ask="Intro to the VP of Security please")
    request_id = result["request"]["request_id"]
    confirmed = client.post(
        f"/api/requests/{request_id}/target",
        json={"account_id": account.id, "note": "confirmed with the requester"},
    ).json()
    assert [candidate["id"] for candidate in confirmed["account_candidates"]] == [account.id]
    assert confirmed["next_decision"]["decision"] != "confirm_account"


def test_duplicate_asks_surface_as_account_activity_not_merges(client, engine):
    account = known_account(engine)
    first = start(client, raw_ask=f"Intro to the VP of Platform at {account.name}")
    second = start(client, raw_ask=f"Intro to the VP of Platform at {account.name}")
    assert first["request"]["request_id"] != second["request"]["request_id"]
    assert second["account_activity"]
    assert second["account_activity_note"]


def test_intake_view_reruns_enrichment_without_creating_a_request(client, engine):
    account = known_account(engine)
    result = start(client, raw_ask=f"Intro to the COO at {account.name}")
    request_id = result["request"]["request_id"]
    again = client.get(f"/api/intake/{request_id}")
    assert again.status_code == 200
    assert again.json()["request"]["request_id"] == request_id


def test_route_decision_on_a_foreign_path_is_rejected(client):
    account = connected_account(api_engine(client))
    first = start(client, raw_ask=f"Intro to the CTO at {account.name}")
    second = start(client, raw_ask=f"Intro to the CTO at {account.name}")
    paths = first["paths"]["paths"]
    assert paths
    response = client.post(
        f"/api/requests/{second['request']['request_id']}/route",
        json={"path_id": paths[0]["id"], "decision": "confirm"},
    )
    assert response.status_code == 422


def test_intake_requires_something_to_work_with(client):
    assert client.post("/api/intake/start", json={"requester_name": "Dana Okafor"}).status_code == 422
