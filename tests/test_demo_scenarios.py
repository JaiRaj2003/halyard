"""The ten demo behaviours, driven through the API against the real corpus.

Every fixture in here is *discovered* from the ingested data — the account with
the most observed relationships, an account whose name is genuinely ambiguous,
a surname several people share — so nothing is hard-coded to make a scenario
come out a particular way. If the supplied data changed, these tests would pick
different rows and still assert the same product behaviour.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from halyard.db.models import Affiliation, Organization, Person, RelationshipEdge
from halyard.db.session import sessionmaker_for


def _scalars(engine, stmt):
    with sessionmaker_for(engine)() as session:
        return session.execute(stmt).all()


@pytest.fixture(scope="module")
def well_connected(engine) -> tuple[int, str]:
    """The account the roster has most observed relationships into."""
    row = _scalars(
        engine,
        select(Organization.id, Organization.name)
        .join(RelationshipEdge, RelationshipEdge.organization_id == Organization.id)
        .group_by(Organization.id)
        .order_by(func.count(RelationshipEdge.id).desc(), Organization.name)
        .limit(1),
    )[0]
    return int(row[0]), str(row[1])


@pytest.fixture(scope="module")
def contact_at(engine, well_connected) -> tuple[str, str]:
    """A named person affiliated with that account, with their observed title."""
    account_id, _ = well_connected
    row = _scalars(
        engine,
        select(Person.display_name, Affiliation.title)
        .join(Affiliation, Affiliation.person_id == Person.id)
        .where(Affiliation.organization_id == account_id)
        .order_by(Person.display_name)
        .limit(1),
    )[0]
    return str(row[0]), str(row[1])


@pytest.fixture(scope="module")
def ambiguous_account_name(engine) -> str:
    """A name that resolves to more than one CRM account."""
    rows = _scalars(
        engine,
        select(Organization.name, func.count(Organization.id))
        .group_by(Organization.canonical_key)
        .having(func.count(Organization.id) > 1)
        .order_by(Organization.name)
        .limit(1),
    )
    if not rows:
        pytest.skip("no ambiguous account names in the corpus")
    return str(rows[0][0])


@pytest.fixture(scope="module")
def shared_forename(engine) -> str:
    rows = _scalars(
        engine,
        select(func.substr(Person.display_name, 1, func.instr(Person.display_name, " ") - 1).label("first"))
        .where(Person.display_name.like("% %"))
        .group_by("first")
        .having(func.count(Person.id) > 2)
        .order_by("first")
        .limit(1),
    )
    if not rows:
        pytest.skip("no shared forenames in the corpus")
    return str(rows[0][0])


@pytest.fixture(scope="module")
def unconnected_account(engine) -> str:
    """A CRM account with no observed relationship into it at all."""
    rows = _scalars(
        engine,
        select(Organization.name)
        .outerjoin(RelationshipEdge, RelationshipEdge.organization_id == Organization.id)
        .where(Organization.is_crm_account.is_(True))
        .group_by(Organization.id)
        .having(func.count(RelationshipEdge.id) == 0)
        .order_by(Organization.name)
        .limit(1),
    )
    if not rows:
        pytest.skip("every CRM account has an observed relationship")
    return str(rows[0][0])


def start(client, ask: str, requester: str = "Demo Operator") -> dict:
    response = client.post("/api/intake/start", json={"raw_ask": ask, "requester_name": requester})
    assert response.status_code == 201, response.text
    return response.json()


def owned_and_actionable(payload: dict) -> None:
    request = payload["request"]
    assert request["operational_owner_id"]
    assert request["next_action"]
    assert request["next_action_due_at"]
    assert request["raw_ask"]


# 1
def test_known_account_and_known_contact(client, well_connected, contact_at):
    _, account = well_connected
    name, title = contact_at
    payload = start(client, f"Can someone introduce us to {name}, {title} at {account}?")
    owned_and_actionable(payload)
    assert payload["parse"]["proposed"]["person_name"] == name
    assert [c for c in payload["account_candidates"] if c["label"] == account]
    assert payload["paths"]["counts"]["total"] > 0


# 2
def test_known_account_without_a_named_contact(client, well_connected):
    _, account = well_connected
    payload = start(client, f"Who can introduce us to the Head of Engineering at {account}?")
    owned_and_actionable(payload)
    assert payload["person_candidates"] == []
    assert payload["request"]["target_title"]
    assert payload["paths"]["counts"]["total"] > 0


# 3
def test_ambiguous_company_name_is_offered_not_guessed(client, ambiguous_account_name):
    payload = start(client, f"Intro to the CTO at {ambiguous_account_name}?")
    owned_and_actionable(payload)
    assert len(payload["account_candidates"]) > 1
    assert payload["next_decision"]["decision"] == "confirm_account"
    assert payload["next_decision"]["blocking"] is True
    assert payload["request"]["account_id"] is None


# 4
def test_ambiguous_person_name_is_offered_not_guessed(client, shared_forename, well_connected):
    _, account = well_connected
    payload = start(client, f"Can you introduce us to {shared_forename} at {account}?")
    owned_and_actionable(payload)
    if len(payload["person_candidates"]) > 1:
        assert payload["next_decision"]["decision"] in {"confirm_person", "confirm_account"}
    assert payload["request"]["target_detail"]["resolved_person"] is None


# 5
def test_duplicate_open_request_surfaces_as_related_activity(client, well_connected):
    _, account = well_connected
    first = start(client, f"Intro to the VP of Engineering at {account}?")
    second = start(client, f"Intro to the VP of Engineering at {account}?", requester="Second Operator")
    assert second["request"]["request_id"] != first["request"]["request_id"]
    related = {row["request"]["request_id"] for row in second["account_activity"]}
    assert first["request"]["request_id"] in related
    assert second["account_activity_note"]


# 6
def test_prior_completed_introduction_is_visible_on_the_account(client, engine):
    completed = client.get("/api/queue", params={"view": "completed", "limit": 500}).json()["items"]
    assert completed, "the corpus contains completed introductions"
    example = completed[0]
    detail = client.get(f"/api/requests/{example['request_id']}").json()
    assert detail["recorded_outcome"] is not None
    assert detail["outcome"] != "UNKNOWN"


# 7
def test_multiple_candidate_connectors_are_ordered_with_one_recommendation(client, well_connected):
    _, account = well_connected
    payload = start(client, f"Anyone know a Director of IT at {account}?")
    paths = payload["paths"]["paths"]
    assert len(paths) > 1
    assert [path["rank"] for path in paths] == sorted(path["rank"] for path in paths)
    assert sum(1 for path in paths if path["recommended"]) == 1
    assert paths[0]["recommendation_label"] == "Recommended to investigate first"
    assert all("score" not in path and "priority" not in path for path in paths)


# 8
def test_routing_a_connector_loads_them_and_moves_them_down_the_next_list(client, well_connected):
    """A confirmed route is an ask: the next request sees that connector as busier."""
    _, account = well_connected
    first = start(client, f"Intro to the Chief Data Officer at {account}?")
    top = first["paths"]["paths"][0]
    assert all(
        factor["key"] != "connector_recent_ask" for factor in top["factors"]
    ), "nothing has been asked of this connector yet"

    client.post(
        f"/api/requests/{first['request']['request_id']}/route",
        json={"path_id": top["id"], "decision": "confirm"},
    ).raise_for_status()

    second = start(client, f"Intro to the Director of IT at {account}?", requester="Another Operator")
    loaded = [
        path for path in second["paths"]["paths"]
        if path["connector"]["name"] == top["connector"]["name"]
    ]
    assert loaded, "the same connector still appears as a lead"
    keys = {factor["key"] for factor in loaded[0]["factors"]}
    assert "connector_recent_ask" in keys
    assert not loaded[0]["recommended"] or len(second["paths"]["paths"]) == 1


def test_factors_explain_without_exposing_a_number(client, well_connected):
    _, account = well_connected
    payload = start(client, f"Intro to the Chief Data Officer at {account}?")
    for path in payload["paths"]["paths"]:
        assert path["factors"]
        for factor in path["factors"]:
            assert factor["statement"]
            assert "weight" not in factor and "score" not in factor


# 9
def test_no_observable_path_stays_owned_and_on_the_queue(client, unconnected_account):
    payload = start(client, f"Can someone introduce us to the CFO at {unconnected_account}?")
    owned_and_actionable(payload)
    assert payload["paths"]["counts"]["total"] == 0
    key = payload["request"]["request_id"]
    queued = client.get("/api/queue", params={"view": "in_flight", "limit": 500}).json()["items"]
    assert key in {item["request_id"] for item in queued}


# 10
def test_new_request_then_a_state_update_keeps_one_request(client, well_connected):
    _, account = well_connected
    payload = start(client, f"Intro to the Engineering Manager at {account}?")
    key = payload["request"]["request_id"]
    top = payload["paths"]["paths"][0]

    routed = client.post(f"/api/requests/{key}/route", json={"path_id": top["id"], "decision": "confirm"})
    assert routed.status_code == 200, routed.text
    body = routed.json()
    assert body["request"]["request_id"] == key
    assert body["request"]["workflow_state"] == "AWAITING_CONNECTOR"
    assert body["request"]["selected_connector"] == top["connector"]["name"]

    sent = client.post(f"/api/requests/{key}/transition", json={"to_state": "INTRO_SENT", "note": "connector sent it"})
    assert sent.status_code == 200, sent.text
    assert sent.json()["workflow_state"] == "INTRO_SENT"
    assert sent.json()["next_action"]

    listed = client.get("/api/requests", params={"q": key}).json()["items"]
    assert [item["request_id"] for item in listed] == [key]
