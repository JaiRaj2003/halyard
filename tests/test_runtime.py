"""Runtime primitives: liveness vs readiness, correlation ids, and what the
server logs — and, just as deliberately, what it never logs.

``/api/health`` says the process answers; ``/api/ready`` says the database does.
Every response carries an ``X-Request-ID`` the caller may have chosen, and the
one log line per request names the route and the outcome without ever quoting
an ask, a person or a query.
"""

from __future__ import annotations

import logging
import re

import pytest

from halyard.observability import current_request_id, resolve_request_id

ASK = "Can someone introduce us to the VP of Security at Northwind Traders?"
REQUESTER = "Dana Okafor"
HEX_UUID = re.compile(r"^[0-9a-f]{32}$")


# --- liveness and readiness -------------------------------------------------


def test_health_is_unchanged_and_needs_nothing(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "as_of", "database"}


def test_ready_answers_200_with_a_stable_payload_when_the_database_answers(client):
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_ready_answers_503_when_the_database_cannot_be_opened(client, tmp_path):
    """Pull the file out from under the engine: the next connection must fail,
    readiness must say so, and liveness must keep saying the process is up."""
    db_path = tmp_path / "api.sqlite3"
    client.app.state.engine.dispose()
    db_path.unlink()
    db_path.mkdir()  # a directory where SQLite expects a file: "unable to open database file"

    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "unreachable"}}
    assert "X-Request-ID" in response.headers
    assert client.get("/api/health").status_code == 200


# --- correlation ids ---------------------------------------------------------


def test_a_request_id_is_generated_when_the_caller_sends_none(client):
    response = client.get("/api/health")
    assert HEX_UUID.match(response.headers["X-Request-ID"])


def test_each_request_gets_its_own_generated_id(client):
    first = client.get("/api/health").headers["X-Request-ID"]
    second = client.get("/api/health").headers["X-Request-ID"]
    assert first != second


def test_a_reasonable_caller_id_is_echoed_back_unchanged(client):
    supplied = "trace-7f3a.b2:c1_ok"
    response = client.get("/api/health", headers={"X-Request-ID": supplied})
    assert response.headers["X-Request-ID"] == supplied


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "has space", "x" * 129, "semi;colon", "quote'd", "back\\slash", "<script>"],
)
def test_an_unreasonable_caller_id_is_replaced_not_echoed(client, bad):
    response = client.get("/api/health", headers={"X-Request-ID": bad})
    returned = response.headers["X-Request-ID"]
    assert returned != bad
    assert HEX_UUID.match(returned)


def test_resolve_request_id_refuses_control_characters():
    for candidate in ("a\nb", "a\rb", "tab\tbed", "ünïcode", None):
        assert HEX_UUID.match(resolve_request_id(candidate))
    assert resolve_request_id("019354b1-0a2c-7b7e-9a9c-2d4f5e6a7b8c") == "019354b1-0a2c-7b7e-9a9c-2d4f5e6a7b8c"


def test_error_responses_carry_the_same_id(client):
    supplied = "err-correlation-1"
    not_found = client.get("/api/requests/NOPE-0000", headers={"X-Request-ID": supplied})
    assert not_found.status_code == 404
    assert not_found.headers["X-Request-ID"] == supplied

    invalid = client.post("/api/intake/start", json={"requester_name": REQUESTER}, headers={"X-Request-ID": supplied})
    assert invalid.status_code == 422
    assert invalid.headers["X-Request-ID"] == supplied


def test_the_id_is_available_in_request_context_while_serving(client):
    seen: list[str] = []

    @client.app.get("/api/_test/context")
    def read_context():
        seen.append(current_request_id())
        return {"ok": True}

    response = client.get("/api/_test/context", headers={"X-Request-ID": "ctx-42"})
    assert response.status_code == 200
    assert seen == ["ctx-42"]
    assert current_request_id() == "-"  # reset once the exchange is over


def test_correlation_id_and_idempotency_key_are_independent(client):
    """One identifies a delivery, the other a submission. A retry of the same
    submission under a fresh correlation id still replays; a new correlation id
    never creates a request, and a shared correlation id never replays one."""
    body = {"requester_name": REQUESTER, "raw_ask": ASK}
    first = client.post("/api/intake/start", json=body, headers={"Idempotency-Key": "k-1", "X-Request-ID": "rid-a"})
    retry = client.post("/api/intake/start", json=body, headers={"Idempotency-Key": "k-1", "X-Request-ID": "rid-b"})
    assert first.status_code == retry.status_code == 201
    assert first.json()["request"]["request_id"] == retry.json()["request"]["request_id"]
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert (first.headers["X-Request-ID"], retry.headers["X-Request-ID"]) == ("rid-a", "rid-b")

    other = client.post("/api/intake/start", json=body, headers={"X-Request-ID": "rid-a"})
    assert other.status_code == 201
    assert other.json()["request"]["request_id"] != first.json()["request"]["request_id"]
    assert "Idempotent-Replayed" not in other.headers


# --- unexpected errors -------------------------------------------------------


@pytest.fixture()
def exploding_client(client):
    """The app with one route that fails the way a bug would."""

    @client.app.get("/api/_test/explode")
    def explode():
        raise RuntimeError(f"secret internals about {REQUESTER} and '{ASK}'")

    return client


def test_an_unhandled_error_answers_500_with_the_id_and_no_internals(exploding_client, caplog):
    """The middleware answers, so the exception never reaches the test client;
    the client would otherwise re-raise it, which is what a real caller never sees."""
    with caplog.at_level(logging.INFO, logger="halyard"):
        response = exploding_client.get("/api/_test/explode", headers={"X-Request-ID": "boom-1"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "boom-1"
    assert response.json() == {"detail": "Internal server error", "request_id": "boom-1"}
    assert "secret internals" not in response.text
    assert REQUESTER not in response.text

    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    line = errors[0].getMessage()
    assert "request_id=boom-1" in line and "error=RuntimeError" in line and "route=/api/_test/explode" in line
    assert errors[0].exc_info is not None and errors[0].exc_info[0] is RuntimeError
    access = [r.getMessage() for r in caplog.records if r.getMessage().startswith("request ")]
    assert any("request_id=boom-1" in line and "status=500" in line for line in access)


# --- what is logged, and what is not ----------------------------------------


def test_each_request_logs_route_status_and_duration_under_its_id(client, caplog):
    with caplog.at_level(logging.INFO, logger="halyard.http"):
        response = client.get("/api/requests/NOPE-0000", headers={"X-Request-ID": "log-1"})
    assert response.status_code == 404

    lines = [record.getMessage() for record in caplog.records if record.name == "halyard.http"]
    assert len(lines) == 1
    line = lines[0]
    for fragment in (
        "request_id=log-1",
        "method=GET",
        "route=/api/requests/{request_key}",
        "path=/api/requests/NOPE-0000",
        "status=404",
    ):
        assert fragment in line
    assert re.search(r"duration_ms=\d+\.\d", line)


def test_intake_logging_never_quotes_the_ask_the_requester_or_the_query(client, caplog):
    with caplog.at_level(logging.DEBUG):
        created = client.post("/api/intake/start", json={"requester_name": REQUESTER, "raw_ask": ASK})
        assert created.status_code == 201
        request_key = created.json()["request"]["request_id"]
        assert client.get("/api/search", params={"q": REQUESTER}).status_code == 200
        assert client.get(f"/api/requests/{request_key}").status_code == 200

    everything = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("halyard"))
    assert "request_id=" in everything and "route=/api/intake/start" in everything
    for sensitive in (ASK, "Northwind", REQUESTER, "Dana", "Okafor", "q=", "VP of Security"):
        assert sensitive not in everything, sensitive
    # Nothing the domain records about the request leaks into the process log.
    events = client.get(f"/api/requests/{request_key}").json()["events"]
    assert events, "the request still has its own audit trail"
    for event in events:
        if event["detail"]:
            assert event["detail"] not in everything


def test_ordinary_responses_are_unchanged_apart_from_the_header(client):
    """Same body whether or not the caller sends an id; the header is the only difference."""
    plain = client.get("/api/metrics/leadership")
    tagged = client.get("/api/metrics/leadership", headers={"X-Request-ID": "cmp-1"})
    assert plain.status_code == tagged.status_code == 200
    assert plain.json() == tagged.json()
    assert set(plain.headers) - {"x-request-id"} == set(tagged.headers) - {"x-request-id"}
    assert plain.headers["content-type"] == tagged.headers["content-type"]
