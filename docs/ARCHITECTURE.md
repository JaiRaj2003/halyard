# Architecture

## Shape

```
data/raw/  (immutable)
    │
    ▼
halyard/ingest/raw.py          stage every row as a SourceRecord (+ SHA-256 of the file)
    │
    ├── halyard/matching/      shared with analysis/audit/ — one implementation
    │
    ▼
halyard/ingest/{entities,requests,paths,coordination,quality}.py
    │                          canonical rows, each carrying its provenance
    ▼
data/derived/halyard.sqlite3   rebuildable, never committed
    │
    ▼
halyard/services/              search · requests · metrics   (all real logic lives here)
    │
    ▼
halyard/api/                   FastAPI: validation, wiring, error mapping only
```

The forensic audit (`analysis/audit/`) reads `data/raw/` directly and writes
CSV/JSON to `analysis/output/`. It shares `halyard/matching/` with the
application and nothing else, so the audit stays reproducible while the product
evolves.

## Stack and why

| choice | reason |
| --- | --- |
| Python 3.12 | the audit is already Python; sharing the matching code was the point |
| SQLAlchemy 2.0 + SQLite | a file the reviewer can rebuild in seconds and open with any tool |
| **no Alembic** | the database is a *derived artifact* — `make ingest` drops and rebuilds it, so migrations would version something that is never migrated. The model is the schema. |
| pandas | already the audit's idiom for the tabular sources |
| RapidFuzz | transparent, thresholded similarity; every score is recorded as evidence |
| FastAPI + Pydantic | validation and an interactive `/docs` for the demo |
| pytest | one suite for the application and the audit |

## Module responsibilities

**`halyard/matching/`** — normalization, account resolution and person
resolution. Pure functions over dataframes, no database. Both consumers depend
on it and neither forks it.

**`halyard/ingest/raw.py`** — reads each supplied file, records its SHA-256 and
row count, and persists every row as a `SourceRecord` with its raw JSON and
parse status. Malformed rows are stored with their error rather than skipped.

**`halyard/ingest/entities.py`** — organizations, people, affiliations,
connectors and relationship edges, each with match tier, method, evidence and
review status. Every match decision, including rejections, is written to
`entity_matches`.

**`halyard/ingest/requests.py`** — reconstructs the 200-request spine: derives
state from explicit evidence where it exists, resolves ownership, builds the
`RequestTarget`, and stamps system-created remediation with
`operationalization_at`.

**`halyard/ingest/paths.py`** — candidate paths, labelled by observability
against the request date.

**`halyard/ingest/coordination.py`** / **`quality.py`** — account coordination
rows and contradiction records.

**`halyard/domain/`** — the rules that must not live in the API: `states.py`
(workflow, route, outcome and the legal transitions), `ownership.py` (the two
resolution orders) and `workflow.py` (next actions, SLA, staleness, age).

**`halyard/services/`** — everything the API can do, callable without HTTP. The
tests exercise both layers.

**`halyard/clock.py`** — `SystemClock` for the application, `FixedClock` for
tests and demos (`HALYARD_AS_OF`), and a separate `audit_clock()` pinned to
2026-08-10. No module calls `datetime.now()` directly.

## Two clocks, three time concepts

- **Historical time** — what the corpus says happened. Preserved verbatim.
- **Operationalization time** — when the legacy backlog came under management.
  Fixed and configurable (`HALYARD_OPERATIONALIZATION_AT`, default 2026-08-10),
  so a rebuild produces identical content whenever it runs.
- **Application time** — real `now()`, used for age, overdue, staleness and
  rolling windows. A request entered today is zero days old.

## Rebuild semantics

`make ingest` drops and recreates the schema. That is idempotent by
construction, and cheaper to reason about than incremental upserts across
sources that contradict each other. Live rows are protected: the pipeline
refuses to destroy a database containing `live_intake` requests unless `--force`
is passed. When live data outgrows that guard, the answer is a real migration
strategy — see `KNOWN_LIMITATIONS.md`.
