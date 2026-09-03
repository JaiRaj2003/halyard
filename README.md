# Halyard

An operational system of record for warm-introduction requests.

A year of Halyard Systems' intro requests was audited before any product was
built (`docs/DATA_AUDIT.md`). The finding: connector capacity is not the
bottleneck — 2 of 49 connector-months exceeded stated capacity — but **115 of
200 requests never reached a connector, 159 were unresolved and silent for 30+
days ($106.5M of $137.8M pipeline), and 150 contradicted themselves across
sources.** Requests were not being rejected. They were being lost.

This repository is the system that fixes that: ingestion, conservative entity
resolution, request reconstruction, path evidence, workflow state, a backend
API, and an operator console over all of it.

## Quick start

```bash
make bootstrap    # .venv + install
make ingest       # build data/derived/halyard.sqlite3 from data/raw/
make test         # 164 application tests + 51 audit tests
make dev          # API on http://127.0.0.1:8000, interactive docs at /docs

cd app && npm install && npm run dev    # console on http://127.0.0.1:5173
```

The console proxies `/api` to the backend, so run `make dev` alongside it.
`make verify` does the whole thing from a clean database: lint, rebuild, tests,
and a re-run of the forensic audit.

## The hero workflow

A free-text ask becomes an owned operational object *before* anything is parsed
or routed. `POST /api/intake/start` writes the request, resolves its operational
owner server-side, gives it a state, a next action and a due date, and only then
parses the text, resolves the account and target, checks what else is already in
flight at that account, and generates candidate paths. If parsing fails or no
path is observable, the request still exists, still has an owner, and still has
a next action — abandoning the flow cannot lose it.

The operator then confirms the target (if it was ambiguous) and confirms or
rules out a route. Every one of those calls updates the *same* request and
advances its state, next action and due date.

## What it does

**Ingestion** (`halyard/ingest/`) reads the twelve supplied files, keeps every
row as a `SourceRecord` with its raw JSON and a SHA-256 of the file it came
from, and rebuilds the canonical model from scratch each time. `data/raw/` is
never written to. Re-running produces byte-identical content: facts created by
the system itself are stamped with a fixed `operationalization_at` rather than
`now()`.

**Entity resolution** (`halyard/matching/`) is shared with the forensic audit —
one implementation, two consumers. It is deliberately conservative: an exact CRM
account ID is definitive, a unique normalized domain is strong evidence, and a
domain shared by several CRM accounts is *never* a merge. Apex Logistics, Inc.
(A91001) and Apex Logistics (A1001) share a domain and stay separate rows with
their competing candidates recorded.

**Requests** carry two kinds of ownership, because the audit's central finding
depends on the difference:

| field | meaning |
| --- | --- |
| `observed_owner_id` | ownership actually evidenced in the source data — usually null |
| `operational_owner_id` | who is accountable now — never null |
| `operational_owner_source` | `observed_owner`, `fallback_requester`, `configured_triage_owner`, `explicit_intake`, `manual_assignment` |
| `was_ownerless_at_ingest` | preserves the historical fact after remediation |

192 of the 200 historical requests evidence no owner. All 200 have one now, and
leadership metrics report both numbers rather than quietly making the past look
healthy.

**Paths** are evidence, not availability. Each candidate path records whether
the relationship was `historically_observable` (dated on or before the request),
`snapshot_only` (undated, so its existence at request time is unknown) or
`post_dates_request`. No field anywhere means "an intro is available".

**Workflow** separates three things that were previously conflated: the
workflow state (where the work is), the route status (how far routing got), and
the outcome (what happened). Staleness is a fourth, independent axis — a flag
for attention, never a state. A request that goes quiet is still owned, still
stated, and still has a next action.

## API

```
GET   /api/health
GET   /api/search?q=
GET   /api/accounts/{id}                    GET /api/people/{id}
GET   /api/requests?state=&owner_id=&stale=&overdue=&ownerless_at_ingest=&q=
POST  /api/requests                         # owner optional in, never null out
GET   /api/requests/{id}                    GET /api/requests/{id}/paths
GET   /api/requests/{id}/related            # account coordination, not duplicates
POST  /api/requests/{id}/transition         PATCH /api/requests/{id}/owner
GET   /api/metrics/stale                    GET /api/metrics/connector-load
GET   /api/metrics/leadership               # every metric states its denominator and window

POST  /api/intake/start                     # persists and owns first, then routes
GET   /api/intake/{id}                      # the same working payload, re-fetched
POST  /api/requests/{id}/target             # human confirms the account/person
POST  /api/requests/{id}/route              # human confirms or rules out a path
GET   /api/queue?view=&limit=               GET /api/queue/views
GET   /api/accounts/{id}/view               # account workspace
```

Intake does not require the caller to name an owner — Slack-style asks
shouldn't push administration onto the requester. The server resolves it
(explicit → configured triage owner → requester) inside the transaction that
writes the row, and rolls back rather than persist an ownerless request.

## Layout

```
halyard/matching/   entity resolution, shared with the audit
halyard/ingest/     raw staging, entities, requests, paths, coordination, quality
halyard/domain/     states, ownership, workflow and SLA rules
halyard/intake/     deterministic free-text ask parser
halyard/services/   search, requests, ranking, routing, queue, accounts, metrics
halyard/api/        FastAPI surface
app/                React + TypeScript operator console
analysis/audit/     the forensic audit that chose this product
tests/              application tests, including the ten foundation invariants
docs/               spec, architecture, data model, lineage, decisions, limits
```

## Documentation

Start with `docs/PRODUCT_SPEC.md` for what is being built and why, and
`docs/DATA_AUDIT.md` for the evidence behind it. `docs/DECISION_LOG.md` records
which calls were made by whom and what was traded away;
`docs/KNOWN_LIMITATIONS.md` records what this system cannot honestly claim.
