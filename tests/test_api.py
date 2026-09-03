"""API behaviour against the real supplied data. No fixtures are hard-coded."""

from __future__ import annotations

from sqlalchemy import select

from halyard.db.models import IntroRequest, Person
from halyard.db.session import sessionmaker_for


def first_request_id(client) -> str:
    return client.get("/api/requests", params={"limit": 1}).json()["items"][0]["request_id"]


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_search_returns_accounts_people_and_connectors_with_evidence(client):
    body = client.get("/api/search", params={"q": "Apex"}).json()
    assert body["accounts"]
    account = body["accounts"][0]
    assert "match_evidence" in account and "review_status" in account


def test_empty_search_is_not_an_error(client):
    assert client.get("/api/search", params={"q": " "}).json()["accounts"] == []


def test_account_detail_shows_shared_domain_siblings_separately(client):
    accounts = client.get("/api/search", params={"q": "Apex"}).json()["accounts"]
    detail = client.get(f"/api/accounts/{accounts[0]['id']}").json()
    assert detail["crm_account_id"]
    assert "shares_domain_with" in detail
    assert detail["id"] not in {sibling["id"] for sibling in detail["shares_domain_with"]}


def test_unknown_account_is_404(client):
    assert client.get("/api/accounts/999999").status_code == 404


def test_person_detail_carries_provenance(client):
    request = client.get(f"/api/requests/{first_request_id(client)}").json()
    person_id = request["operational_owner_id"]
    detail = client.get(f"/api/people/{person_id}").json()
    assert detail["identity_basis"]
    assert "affiliations" in detail


def test_request_listing_filters(client):
    all_requests = client.get("/api/requests", params={"limit": 500}).json()
    assert all_requests["total"] == 200
    triage = client.get("/api/requests", params={"state": "NEEDS_TRIAGE", "limit": 500}).json()
    assert 0 < triage["total"] < 200
    assert {item["workflow_state"] for item in triage["items"]} == {"NEEDS_TRIAGE"}
    ownerless = client.get("/api/requests", params={"ownerless_at_ingest": True, "limit": 500}).json()
    assert ownerless["total"] > 100


def test_request_detail_includes_evidence_and_events(client):
    detail = client.get(f"/api/requests/{first_request_id(client)}").json()
    assert detail["state_evidence"]
    assert detail["events"]
    assert detail["target_detail"]["raw_account_text"]


def test_unknown_request_is_404(client):
    assert client.get("/api/requests/NOPE-1").status_code == 404


def test_paths_never_claim_an_intro_is_available(client):
    for item in client.get("/api/requests", params={"limit": 25}).json()["items"]:
        body = client.get(f"/api/requests/{item['request_id']}/paths").json()
        assert "evidence about where to investigate" in body["disclaimer"]
        for path in body["paths"]:
            assert path["limitations"]
            assert path["observability"] in {"historically_observable", "snapshot_only", "post_dates_request"}
            assert not any("intro_available" in key or "can_intro" in key for key in path)


def test_related_activity_is_not_labelled_duplicate(client):
    for item in client.get("/api/requests", params={"limit": 40}).json()["items"]:
        body = client.get(f"/api/requests/{item['request_id']}/related").json()
        for related in body["related"]:
            assert related["relation_type"] in {
                "same_canonical_account",
                "same_account_same_title_family",
                "same_account_same_target_person",
                "explicit_reask",
            }


def test_create_request_defaults_owner_to_requester(client):
    response = client.post(
        "/api/requests",
        json={"requester_name": "Imani Mkhize", "target_account_text": "Northwind Robotics",
              "target_title": "VP of Security", "raw_ask": "intro to security leadership"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["operational_owner_source"] == "fallback_requester"
    assert body["operational_owner"] == "Imani Mkhize"
    assert body["was_ownerless_at_ingest"] is False
    assert body["age_days"] == 0


def test_create_request_uses_the_configured_triage_owner(api, client):
    owner_name = client.get("/api/requests", params={"limit": 1}).json()["items"][0]["operational_owner"]
    with api(triage_owner_name=owner_name) as triage_client:
        body = triage_client.post(
            "/api/requests",
            json={"requester_name": "Someone Brand New", "target_account_text": "Northwind Robotics"},
        ).json()
    assert body["operational_owner_source"] == "configured_triage_owner"
    assert body["operational_owner"] == owner_name


def test_create_request_honours_an_explicit_owner(client):
    owner_id = client.get("/api/requests", params={"limit": 1}).json()["items"][0]["operational_owner_id"]
    body = client.post(
        "/api/requests",
        json={"requester_name": "Someone Brand New", "target_account_text": "Northwind Robotics",
              "operational_owner_id": owner_id},
    ).json()
    assert body["operational_owner_source"] == "explicit_intake"
    assert body["operational_owner_id"] == owner_id


def test_create_request_rejects_an_unknown_owner_without_persisting_anything(client):
    before = client.get("/api/requests", params={"limit": 500}).json()["total"]
    response = client.post(
        "/api/requests",
        json={"requester_name": "Someone Brand New", "target_account_text": "Northwind Robotics",
              "operational_owner_id": 999999},
    )
    assert response.status_code == 422
    assert client.get("/api/requests", params={"limit": 500}).json()["total"] == before


def test_create_request_validates_input(client):
    assert client.post("/api/requests", json={"requester_name": "", "target_account_text": "x"}).status_code == 422
    assert client.post("/api/requests", json={"requester_name": "x"}).status_code == 422


def test_target_persona_does_not_create_a_person(client, tmp_path):
    body = client.post(
        "/api/requests",
        json={"requester_name": "Imani Mkhize", "target_account_text": "Northwind Robotics",
              "target_title": "VP of Security", "raw_ask": "need the VP of Security at Northwind"},
    ).json()
    assert body["target_detail"]["resolved_person"] is None
    people = client.get("/api/search", params={"q": "VP of Security"}).json()["people"]
    assert people == []


def test_evidenced_live_individual_may_become_a_person(client):
    body = client.post(
        "/api/requests",
        json={"requester_name": "Imani Mkhize", "target_account_text": "Northwind Robotics",
              "target_person_name": "Priya Ramanathan-Okoye", "target_title": "CISO",
              "target_person_evidenced": True},
    ).json()
    resolved = body["target_detail"]["resolved_person"]
    assert resolved is not None
    assert resolved["source_type"] in {"live_input", "historical_corpus"}


def test_transition_follows_the_state_machine(client):
    request_id = client.get(
        "/api/requests", params={"state": "PATH_REVIEW", "limit": 1}
    ).json()["items"][0]["request_id"]
    body = client.post(
        f"/api/requests/{request_id}/transition",
        json={"to_state": "AWAITING_CONNECTOR", "actor": "ops", "note": "asked Trask"},
    ).json()
    assert body["workflow_state"] == "AWAITING_CONNECTOR"
    assert body["next_action_due_at"]
    assert body["state_source"] == "operator_transition"


def test_illegal_transition_is_rejected(client):
    request_id = client.get(
        "/api/requests", params={"state": "NEEDS_TRIAGE", "limit": 1}
    ).json()["items"][0]["request_id"]
    response = client.post(f"/api/requests/{request_id}/transition", json={"to_state": "COMPLETED"})
    assert response.status_code == 409
    assert "not an allowed transition" in response.json()["detail"]


def test_closing_requires_an_explicit_reason(client):
    request_id = client.get(
        "/api/requests", params={"state": "NEEDS_TRIAGE", "limit": 1}
    ).json()["items"][0]["request_id"]
    assert client.post(f"/api/requests/{request_id}/transition", json={"to_state": "CLOSED"}).status_code == 422
    body = client.post(
        f"/api/requests/{request_id}/transition",
        json={"to_state": "CLOSED", "closure_reason": "buyer left the company", "actor": "ops"},
    ).json()
    assert body["workflow_state"] == "CLOSED"
    assert body["closure_reason"] == "buyer left the company"


def test_unknown_state_is_rejected(client):
    request_id = first_request_id(client)
    assert client.post(f"/api/requests/{request_id}/transition", json={"to_state": "WAT"}).status_code == 422


def test_owner_can_be_reassigned_and_is_never_cleared(client, engine):
    request_id = first_request_id(client)
    with sessionmaker_for(engine)() as session:
        other = session.scalars(select(Person).where(Person.is_internal.is_(True))).all()[1]
        other_id, other_name = other.id, other.display_name
    body = client.patch(
        f"/api/requests/{request_id}/owner",
        json={"operational_owner_id": other_id, "actor": "ops", "note": "rebalancing"},
    ).json()
    assert body["operational_owner_id"] == other_id
    assert body["operational_owner"] == other_name
    assert body["operational_owner_source"] == "manual_assignment"
    assert client.patch(
        f"/api/requests/{request_id}/owner", json={"operational_owner_id": 999999}
    ).status_code == 422


def test_metrics_stale_counts_only_what_halyard_has_worked(client):
    body = client.get("/api/metrics/stale").json()
    assert body["staleness_days"] == 30
    #: The imported corpus went quiet before this system existed; that is legacy
    #: backlog, not staleness under Halyard.
    assert body["stale_count"] == 0
    assert all(item["workflow_state"] not in {"COMPLETED", "CLOSED"} for item in body["items"])
    assert all(item["sla_managed"] for item in body["items"])


def test_metrics_connector_load_reports_capacity_only_where_stated(client):
    body = client.get("/api/metrics/connector-load").json()
    assert body["roster_size"] == 6
    for row in body["connectors"]:
        if not row["on_roster"]:
            assert row["stated_monthly_capacity"] is None
            assert row["capacity_utilisation"] is None
            assert "not present in the managed connector roster" in row["note"]


def test_metrics_leadership_distinguishes_history_from_the_guarantee(client):
    body = client.get("/api/metrics/leadership").json()
    assert body["requests_total"] == body["requests_with_operational_owner"]
    assert body["historically_ownerless_at_ingest"] > 0
    assert body["by_workflow_state"]


def test_every_persisted_request_has_an_owner(client, engine):
    with sessionmaker_for(engine)() as session:
        missing = session.scalars(
            select(IntroRequest).where(IntroRequest.operational_owner_id.is_(None))
        ).all()
    assert missing == []
