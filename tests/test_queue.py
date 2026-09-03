"""Operator queue views over the real corpus."""

from __future__ import annotations

from halyard.services.queue import VIEWS_BY_KEY


def test_every_view_states_its_definition(client):
    views = client.get("/api/queue/views").json()["views"]
    assert {view["key"] for view in views} == set(VIEWS_BY_KEY)
    assert all(view["definition"] and view["label"] for view in views)


def test_there_is_no_unowned_view_because_every_request_is_owned(client):
    assert "unowned" not in VIEWS_BY_KEY
    items = client.get("/api/queue", params={"view": "all", "limit": 500}).json()["items"]
    assert items
    assert all(item["operational_owner_id"] for item in items)


def test_needs_ownership_review_holds_the_historically_ownerless(client):
    body = client.get("/api/queue", params={"view": "needs_ownership_review", "limit": 500}).json()
    assert body["total"] > 0
    assert all(item["was_ownerless_at_ingest"] for item in body["items"])
    assert all(item["operational_owner_source"] == "fallback_requester" for item in body["items"])


def test_counts_cover_every_view_on_one_pass(client):
    body = client.get("/api/queue", params={"view": "in_flight"}).json()
    assert set(body["counts"]) == set(VIEWS_BY_KEY)
    assert body["counts"]["all"] >= body["counts"]["in_flight"] >= body["total"] - 1


def test_no_observable_path_requests_stay_in_the_working_queue(client):
    body = client.get("/api/queue", params={"view": "no_observable_path", "limit": 500}).json()
    for item in body["items"]:
        assert item["next_action"]
        assert item["operational_owner_id"]
    in_flight = client.get("/api/queue", params={"view": "in_flight", "limit": 500}).json()["items"]
    ids = {item["request_id"] for item in in_flight}
    assert all(item["request_id"] in ids for item in body["items"])


def test_overdue_and_stale_are_independent_axes(client):
    stale = client.get("/api/queue", params={"view": "stale", "limit": 500}).json()["items"]
    assert stale
    assert {item["workflow_state"] for item in stale} != {"CLOSED"}
    for item in stale:
        assert "potentially_stale" in item and "is_overdue" in item


def test_overlapping_view_reports_related_account_activity(client):
    body = client.get("/api/queue", params={"view": "overlapping", "limit": 500}).json()
    assert all(item["related_count"] > 0 for item in body["items"])


def test_rows_carry_what_an_operator_has_to_decide_from(client):
    item = client.get("/api/queue", params={"view": "all", "limit": 1}).json()["items"][0]
    for field in (
        "target", "account", "requester", "operational_owner", "workflow_state", "last_activity_at",
        "next_action", "next_action_due_at", "is_overdue", "potentially_stale", "related_count",
    ):
        assert field in item


def test_unknown_view_is_a_422_listing_the_known_views(client):
    response = client.get("/api/queue", params={"view": "nonsense"})
    assert response.status_code == 422
    assert "needs_ownership_review" in response.json()["detail"]


def test_owner_filter_narrows_the_queue(client):
    items = client.get("/api/queue", params={"view": "all", "limit": 1}).json()["items"]
    owner_id = items[0]["operational_owner_id"]
    body = client.get("/api/queue", params={"view": "all", "owner_id": owner_id, "limit": 500}).json()
    assert body["items"]
    assert all(item["operational_owner_id"] == owner_id for item in body["items"])
