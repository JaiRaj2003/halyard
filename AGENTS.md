# AGENTS.md

Guidance for anyone — human or agent — working in this repository.

## What this is

Halyard is an operational system of record for warm-introduction requests. The
forensic audit in `docs/DATA_AUDIT.md` found that the bottleneck is not
connector capacity (2 of 49 connector-months exceeded stated capacity) but the
absence of ownership and state: 115 of 200 requests never reached a connector,
159 were unresolved and silent for 30+ days, and 150 contradicted themselves
across sources. The product exists to make every request owned, stated, and
visible.

**Product thesis.** The fastest path into a target account is a warm
introduction, and warm introductions fail operationally rather than
relationally. Give every request an owner, a state, a next action and a due
date, and surface the evidence behind each — the pipeline stops evaporating in
silence.

**Primary user.** The BD operator who runs the intro pipeline day to day.
Leadership is a secondary reader of the same data, not a separate system.

**Core workflow.** Request arrives → triage (owner, target, account) → entity
review if the target or account is ambiguous → path review over candidate
evidence → connector asked → intro sent → outcome recorded, or the request is
explicitly closed with a reason. Nothing leaves the workflow by going quiet.

## Scope

In scope:

- reproducible ingestion of `data/raw/` into a canonical SQLite database
- conservative entity resolution that preserves ambiguity
- request reconstruction with ownership, state, next action and provenance
- candidate-path evidence, time-aware
- account coordination between parallel asks
- backend APIs and tests over all of the above
- live free-text intake that persists and owns the request before routing
- deterministic, explainable ordering of candidate paths
- the operator console in `app/`: intake, queue, request detail, account view,
  leadership metrics

Non-goals: authentication, permissions, paid external APIs, a real CRM or Slack
integration, a cloud database, microservices, a calibrated ranking model, a
marketing page, settings screens and network-graph decoration.

## Commands

```
make bootstrap   # create .venv and install the project
make ingest      # rebuild the database from data/raw/
make dev         # run the API on http://127.0.0.1:8000 (docs at /docs)
cd app && npm run dev   # operator console on http://127.0.0.1:5173, proxies /api
make test        # application tests + forensic audit tests
make audit       # re-run the forensic audit
make reset       # delete the built database
make verify      # lint, clean rebuild, tests and audit end to end
```

## Rules

**Raw data is immutable.** `data/raw/` is read-only. Never edit, overwrite,
reformat or "fix" a file there. Everything derived goes to `data/derived/`,
which is rebuildable and not committed.

**Provenance is required.** Every canonical row records where it came from: the
source record, the match method, the confidence, the relevant raw value, and its
review status. If you cannot say where a value came from, do not persist it.

**Entity resolution is conservative.** An exact CRM account ID is definitive. A
unique normalized domain is strong evidence. A domain shared by several CRM
accounts is a coordination hint and never a merge — subsidiaries and business
units must not be collapsed. Conflicting evidence stays ambiguous and visible.
Shared matching logic lives in `halyard/matching/` and is used by both the audit
and the application; do not fork it.

**No silent discard.** Malformed and unmatched records are persisted with their
error, never dropped. Source counts must reconcile against canonical counts, and
`make ingest` prints the reconciliation.

**No fake precision.** Do not invent an identity, a date or a confidence.
"VP of Security at Acme" is a target persona, not a person: it becomes a
`RequestTarget`, never a `Person`. Undated relationships are labelled
`snapshot_only`, not assumed to have existed at request time.

**Explainable ranking.** Anything ordered or flagged must show its reason.
Candidate paths carry their hop type, observability, limitations and evidence.
Ordering uses integer factor weights from configuration, but the composite is
never serialised or displayed — the operator reads factor sentences, not a
number. No field may imply an introduction is available: a path says where to
investigate, nothing more.

**A request is owned the moment it reaches the server.** Intake persists it and
assigns an owner, state, next action and due date *before* parsing or routing.
Nothing about a request may be modelled as a preview that can disappear.

**Two clocks.** The application uses real time; the forensic audit uses its
documented corpus date of 2026-08-10. Historical facts created at ingest are
stamped with a fixed `operationalization_at` so rebuilds are deterministic. Tests
inject a clock; nothing calls `datetime.now()` directly.

## UI principles

Show the evidence next to the claim. Ambiguity is displayed, not hidden behind a
best guess. Never show a number without its denominator or a state without its
source. Staleness appears as a flag beside the state, never as the state.

## Testing and documentation

Every parser, matching tier, state derivation, transition, metric and endpoint
has a test, and the ten foundation invariants in `tests/test_invariants.py` are
executable promises — if one fails the foundation is wrong. Tests run against
the real supplied data; no behaviour may depend on a hard-coded demo record.

Update `docs/DECISION_LOG.md` when a judgment call is made, and
`docs/KNOWN_LIMITATIONS.md` when you find something the system cannot honestly
claim.
