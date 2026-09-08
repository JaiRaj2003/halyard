"""Transport reliability of live intake: retried deliveries and concurrent asks.

Two properties, kept deliberately separate from anything about business
duplicates. First, a client that retries ``POST /api/intake/start`` with the
same ``Idempotency-Key`` gets the request its first delivery created, and never
a second row. Second, asks that arrive at the same moment each get their own
``LIVE-nnnn`` id. Identical asks under different keys remain two requests: two
people asking the same thing is a coordination fact, not a transport error.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from halyard.db.models import IntakeIdempotencyKey, IntroRequest
from halyard.db.session import sessionmaker_for
from halyard.services import intake as intake_module
from halyard.services.intake import IntakeSubmission, submission_fingerprint

ASK = "Can someone introduce us to the VP of Security at Northwind Traders?"
LIVE_ID = re.compile(r"^LIVE-\d{4}$")


def post(client, key: str | None = None, **body):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/api/intake/start", json={"requester_name": "Dana Okafor", "raw_ask": ASK, **body}, headers=headers)


def live_requests(client) -> list[IntroRequest]:
    with sessionmaker_for(client.app.state.engine)() as session:
        return session.scalars(
            select(IntroRequest).where(IntroRequest.origin == "live_intake").order_by(IntroRequest.id)
        ).all()


def key_rows(client) -> int:
    with sessionmaker_for(client.app.state.engine)() as session:
        return session.scalar(select(func.count()).select_from(IntakeIdempotencyKey)) or 0


def test_same_key_twice_creates_exactly_one_request(client):
    first = post(client, key="retry-abc")
    second = post(client, key="retry-abc")
    assert first.status_code == 201 and second.status_code == 201, (first.text, second.text)

    assert first.json()["request"]["request_id"] == second.json()["request"]["request_id"]
    assert first.json()["request"]["id"] == second.json()["request"]["id"]
    assert "Idempotent-Replayed" not in first.headers
    assert second.headers["Idempotent-Replayed"] == "true"

    assert len(live_requests(client)) == 1
    assert key_rows(client) == 1


def test_replay_returns_the_enriched_original_not_a_bare_row(client):
    first = post(client, key="retry-enriched").json()
    second = post(client, key="retry-enriched").json()
    assert second["request"]["workflow_state"] == first["request"]["workflow_state"]
    assert second["request"]["operational_owner_id"] == first["request"]["operational_owner_id"]
    assert second["request"]["next_action"] == first["request"]["next_action"]
    assert [p["id"] for p in second["paths"]["paths"]] == [p["id"] for p in first["paths"]["paths"]]


def test_same_payload_under_different_keys_is_two_requests(client):
    a = post(client, key="operator-one").json()["request"]
    b = post(client, key="operator-two").json()["request"]
    assert a["request_id"] != b["request_id"]
    assert a["raw_ask"] == b["raw_ask"]
    assert len(live_requests(client)) == 2


def test_key_reuse_with_a_different_body_is_refused_and_creates_nothing(client):
    first = post(client, key="reused")
    assert first.status_code == 201

    conflict = post(client, key="reused", raw_ask="Totally different ask about the CFO at Contoso")
    assert conflict.status_code == 409, conflict.text
    assert first.json()["request"]["request_id"] in conflict.json()["detail"]

    subtle = post(client, key="reused", deal_value_usd=250_000)
    assert subtle.status_code == 409, subtle.text

    rows = live_requests(client)
    assert len(rows) == 1
    assert rows[0].raw_ask == ASK
    assert rows[0].deal_value_usd == 0


def test_fingerprint_is_stable_and_field_sensitive():
    def fp(**fields) -> str:
        return submission_fingerprint(IntakeSubmission(requester_name="Dana Okafor", **fields))

    assert fp(raw_ask=ASK) == fp(raw_ask=ASK)
    assert fp(raw_ask=ASK) != fp(raw_ask=ASK, urgency="high")
    assert fp(raw_ask=ASK) != fp(raw_ask=ASK + " ")


def test_idempotency_survives_a_fresh_engine_and_session(api):
    """A retry lands on another worker with its own connection pool: still one request."""
    with api() as first_process:
        original = post(first_process, key="cross-process").json()["request"]
    with api() as second_process:
        assert second_process.app.state.engine is not first_process.app.state.engine
        replay = post(second_process, key="cross-process")
        assert replay.status_code == 201
        assert replay.headers["Idempotent-Replayed"] == "true"
        assert replay.json()["request"]["request_id"] == original["request_id"]
        assert len(live_requests(second_process)) == 1


def test_no_key_preserves_existing_behaviour(client):
    a = post(client)
    b = post(client)
    assert a.status_code == 201 and b.status_code == 201
    assert "Idempotent-Replayed" not in a.headers and "Idempotent-Replayed" not in b.headers
    assert a.json()["request"]["request_id"] != b.json()["request"]["request_id"]
    assert len(live_requests(client)) == 2
    assert key_rows(client) == 0


def test_live_ids_are_human_readable_unique_and_never_collide_with_history(client):
    ids = [post(client).json()["request"]["request_id"] for _ in range(3)]
    assert all(LIVE_ID.match(i) for i in ids), ids
    assert len(set(ids)) == 3
    with sessionmaker_for(client.app.state.engine)() as session:
        all_ids = session.scalars(select(IntroRequest.request_id)).all()
    assert len(all_ids) == len(set(all_ids))
    assert not any(i.startswith("LIVE-pending") for i in all_ids)


def test_an_operator_supplied_live_id_does_not_break_the_next_generated_one(client):
    rows = live_requests(client)
    with sessionmaker_for(client.app.state.engine)() as session:
        next_row_id = (session.scalar(select(func.max(IntroRequest.id))) or 0) + 1
    assert not rows
    taken = f"LIVE-{next_row_id + 1:04d}"
    explicit = post(client, request_id=taken)
    assert explicit.status_code == 201 and explicit.json()["request"]["request_id"] == taken

    generated = post(client).json()["request"]["request_id"]
    assert LIVE_ID.match(generated) and generated != taken
    assert len({r.request_id for r in live_requests(client)}) == 2


def test_simultaneous_deliveries_of_one_key_yield_one_request(api):
    """Two workers, one database file, the same retried delivery at once. The
    unique key constraint decides who created it; the other returns that request.
    The requester is new to the system too, so the two also collide on her row."""
    clients = [api() for _ in range(2)]
    assert clients[0].app.state.engine is not clients[1].app.state.engine
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda c: post(c, key="burst"), clients))
        assert {r.status_code for r in responses} == {201}, [r.text for r in responses]
        assert len({r.json()["request"]["request_id"] for r in responses}) == 1
        assert len(live_requests(clients[0])) == 1
        assert key_rows(clients[0]) == 1
    finally:
        for c in clients:
            c.close()


def test_losing_the_key_race_at_commit_returns_the_winner(client, monkeypatch):
    """Deterministic version of the burst: the other delivery commits between our
    key lookup and our commit, so the unique constraint, not the lookup, catches it."""
    engine = client.app.state.engine
    settings, clock = client.app.state.settings, client.app.state.clock
    submission = IntakeSubmission(requester_name="Dana Okafor", raw_ask=ASK)
    real_persist = intake_module.persist_owned_request
    winner: dict = {}

    def persist_after_the_other_worker_wins(session, payload, *args):
        if "entered" not in winner:
            winner["entered"] = True
            with sessionmaker_for(engine)() as other:
                result, replayed = intake_module.start_intake(other, submission, settings, clock, idempotency_key="race")
                other.commit()
                winner["request_id"], winner["replayed"] = result["request"]["request_id"], replayed
        return real_persist(session, payload, *args)

    monkeypatch.setattr(intake_module, "persist_owned_request", persist_after_the_other_worker_wins)
    with sessionmaker_for(engine)() as session:
        result, replayed = intake_module.start_intake(session, submission, settings, clock, idempotency_key="race")

    assert winner["replayed"] is False
    assert replayed is True
    assert result["request"]["request_id"] == winner["request_id"]
    assert len(live_requests(client)) == 1
    assert key_rows(client) == 1


def test_a_collision_on_a_shared_row_is_retried_once_not_surfaced(client, monkeypatch):
    """Two intakes from a requester nobody has seen both try to record her; the
    loser's transaction is rolled back and done again, and nothing half-written
    survives. Simulated at the persist boundary so the collision is certain."""
    real_persist = intake_module.persist_owned_request
    calls: list[int] = []

    def persist_then_lose_the_write_lock(session, payload, *args):
        request = real_persist(session, payload, *args)
        calls.append(request.id)
        if len(calls) == 1:
            raise IntegrityError("INSERT INTO persons", {}, Exception("UNIQUE constraint failed: persons.person_key"))
        return request

    monkeypatch.setattr(intake_module, "persist_owned_request", persist_then_lose_the_write_lock)
    response = post(client)
    assert response.status_code == 201, response.text
    assert len(calls) == 2
    rows = live_requests(client)
    assert [r.id for r in rows] == [calls[1]]
    assert rows[0].request_id == response.json()["request"]["request_id"]
    assert LIVE_ID.match(rows[0].request_id)


def test_simultaneous_distinct_asks_each_get_their_own_live_id(api):
    """Four asks land at once, without keys, from a requester nobody has seen.
    Under the old row-count scheme two of them derived the same LIVE id and one
    failed; now each gets its own and all four are persisted."""
    clients = [api() for _ in range(4)]
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda c: post(c, key=None, account_text="Contoso"), clients))
        assert {r.status_code for r in responses} == {201}, [r.text for r in responses]
        ids = [r.json()["request"]["request_id"] for r in responses]
        assert len(set(ids)) == 4, ids
        assert all(LIVE_ID.match(i) for i in ids)
        assert len(live_requests(clients[0])) == 4
    finally:
        for c in clients:
            c.close()
