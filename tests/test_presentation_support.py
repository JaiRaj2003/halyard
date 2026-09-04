"""Additive API fields the operator console reads: the structured contact on a
candidate path, the deduplicated needs-attention queue view, the queue search
narrowing and the concrete next action once a route is selected.

None of these change how paths are generated or ordered, how requests move, or
who owns them; they expose facts the database already held.
"""

from __future__ import annotations

from halyard.domain.states import WorkflowState
from halyard.services.queue import VIEWS_BY_KEY

from test_intake_flow import api_engine, connected_account, start


def _paths(client, request_id: str) -> list[dict]:
    return client.get(f"/api/requests/{request_id}/paths").json()["paths"]


def test_candidate_paths_carry_a_structured_contact_or_null(client):
    """The route chain reads connector → contact → account from data, never from
    the evidence string."""
    for request_id in ("R1001", "R1002", "R1003"):
        for path in _paths(client, request_id):
            assert "contact" in path
            contact = path["contact"]
            if contact is None:
                continue
            assert contact["id"] and contact["name"]
            assert "title" in contact and "organization" in contact
            # The contact is quoted in the evidence the ranker already recorded.
            assert contact["name"] in path["evidence"]


def test_r1001_contact_is_the_colleague_named_in_the_evidence(client):
    paths = _paths(client, "R1001")
    named = [path for path in paths if path["contact"] is not None]
    assert named
    first = named[0]
    assert first["contact"]["name"] == "Sabine Dellinger"
    assert first["contact"]["title"] == "Chief Data Officer"
    assert first["contact"]["organization"]["name"] == "Vantage Ridge Utilities"
    off_roster = [path for path in paths if not path["connector"]["on_roster"]]
    assert off_roster and all(path["contact"] is None for path in off_roster)


def test_contact_field_does_not_alter_ordering_or_recommendation(client):
    paths = _paths(client, "R1001")
    assert [path["rank"] for path in paths] == list(range(1, len(paths) + 1))
    assert paths[0]["recommended"] is True
    assert sum(1 for path in paths if path["recommended"]) == 1


def test_needs_attention_lists_each_request_once(client):
    body = client.get("/api/queue", params={"view": "needs_attention", "limit": 500}).json()
    ids = [item["request_id"] for item in body["items"]]
    assert ids
    assert len(ids) == len(set(ids))
    assert body["total"] == body["counts"]["needs_attention"] == len(ids)
    for item in body["items"]:
        assert item["workflow_state"] not in {"COMPLETED", "CLOSED"}
        assert (
            item["workflow_state"] in {"NEEDS_TRIAGE", "NEEDS_ENTITY_REVIEW", "PATH_REVIEW", "BLOCKED"}
            or item["route_signal"] == "unverified_suggested_route"
            or item["sla_breached"]
        )


def test_needs_attention_keeps_origins_distinguishable(client):
    account = connected_account(api_engine(client))
    created = start(client, raw_ask=f"Intro to the CFO at {account.name}?")["request"]["request_id"]
    body = client.get("/api/queue", params={"view": "needs_attention", "limit": 500}).json()
    by_id = {item["request_id"]: item for item in body["items"]}
    assert created in by_id
    assert by_id[created]["origin"] == "live_intake"
    assert by_id[created]["legacy_backlog"] is False
    assert by_id["R1001"]["origin"] == "historical_corpus"
    assert by_id["R1001"]["legacy_backlog"] is True


def test_completed_requests_are_not_needs_attention(client):
    completed = client.get("/api/queue", params={"view": "completed", "limit": 500}).json()["items"]
    assert completed
    attention = {
        item["request_id"]
        for item in client.get("/api/queue", params={"view": "needs_attention", "limit": 500}).json()["items"]
    }
    assert not {item["request_id"] for item in completed} & attention


def test_unverified_route_in_path_review_appears_once_in_needs_attention(client):
    """Path review + unverified route satisfy two conditions and yield one row."""
    unverified = client.get("/api/queue", params={"view": "unverified_route", "limit": 500}).json()["items"]
    both = [item for item in unverified if item["workflow_state"] == "PATH_REVIEW"]
    attention = client.get("/api/queue", params={"view": "needs_attention", "limit": 500}).json()["items"]
    counts = {}
    for item in attention:
        counts[item["request_id"]] = counts.get(item["request_id"], 0) + 1
    for item in both:
        assert counts.get(item["request_id"]) == 1


def test_queue_search_narrows_rows_but_not_view_counts(client):
    everything = client.get("/api/queue", params={"view": "all", "limit": 500}).json()
    narrowed = client.get("/api/queue", params={"view": "all", "limit": 500, "q": "vantage ridge"}).json()
    assert narrowed["q"] == "vantage ridge"
    assert 0 < narrowed["total"] < everything["total"]
    assert all("vantage ridge" in item["account"].casefold() for item in narrowed["items"])
    assert narrowed["counts"] == everything["counts"]

    by_id = client.get("/api/queue", params={"view": "all", "q": "R1001"}).json()
    assert [item["request_id"] for item in by_id["items"]] == ["R1001"]

    by_title = client.get("/api/queue", params={"view": "all", "limit": 500, "q": "chief operating"}).json()
    assert by_title["total"] > 0
    assert all("chief operating" in item["target_title"].casefold() for item in by_title["items"])

    by_owner = client.get("/api/queue", params={"view": "all", "limit": 500, "q": "Imani"}).json()
    assert by_owner["total"] > 0

    nothing = client.get("/api/queue", params={"view": "all", "q": "zzzz-no-such-thing"}).json()
    assert nothing["total"] == 0 and nothing["items"] == []


def test_views_catalogue_includes_needs_attention(client):
    views = {view["key"] for view in client.get("/api/queue/views").json()["views"]}
    assert "needs_attention" in views and "needs_attention" in VIEWS_BY_KEY


def test_selecting_a_route_sets_a_concrete_human_next_action(client):
    account = connected_account(api_engine(client))
    result = start(client, raw_ask=f"Please introduce us to the CISO at {account.name}")
    request_id = result["request"]["request_id"]
    paths = result["paths"]["paths"]
    chosen = paths[0]
    body = client.post(
        f"/api/requests/{request_id}/route",
        json={"path_id": chosen["id"], "decision": "confirm"},
    ).json()["request"]
    assert body["workflow_state"] == WorkflowState.AWAITING_CONNECTOR.value
    connector = chosen["connector"]["name"]
    assert body["next_action"].startswith(f"Ask {connector} to confirm whether they can reach ")
    if chosen["contact"] is not None:
        assert body["next_action"].endswith(chosen["contact"]["name"])
    else:
        assert body["next_action"].endswith(f"a contact at {account.name}")
    assert body["next_action_due_at"]
    # The same wording is what the queue shows.
    row = client.get("/api/queue", params={"view": "awaiting_connector", "q": request_id}).json()["items"]
    assert row and row[0]["next_action"] == body["next_action"]
