# Decision log

Who decided what, on what evidence, and what was deliberately deferred.
"Operator" is the human owner of this take-home; "Devin" is the agent.

---

### D1 — Which failure to build against

- **Decided by:** operator, after the audit.
- **Devin proposed:** four candidate failures, each tested against the corpus.
- **Evidence:** 159/200 unresolved and silent 30+ days ($106.5M of $137.8M);
  115/200 never reached a connector; 150/200 self-contradictory; only 2/49
  connector-months over stated capacity; 46/109 "no path" requests actually had
  a pre-dating connection.
- **Decision:** build against *ownership and state of record*. Connector
  overload was rejected on the numbers; missed paths ranked second because every
  observable path is second-hop and 0/200 requests have a connector who knows
  the buyer.
- **Tradeoff:** the more visually impressive product is the path finder. The
  data does not support it as the primary failure.

### D2 — Observed ownership vs operational ownership

- **Decided by:** operator (authoritative decision 1).
- **Devin proposed:** populating a single `owner_id`, falling back to the
  requester.
- **Why rejected:** that would have made the historical process look healthier
  than it was and erased the finding the product exists to fix.
- **Decision:** `observed_owner_id` (nullable, evidence only),
  `operational_owner_id` (never null), `operational_owner_source`,
  `was_ownerless_at_ingest`. `connector_asked` is explicitly *not* ownership.
- **Result:** 192/200 ownerless at ingest, all 200 owned operationally.

### D3 — SLA model

- **Decided by:** operator (decision 2).
- **Devin proposed:** priority tiers (Critical/High/Medium/Low).
- **Why rejected:** the supplied data has no priority field that supports them.
- **Decision:** state-based defaults in configuration — 2 days for review
  states, 5 for waiting states — documented as product configuration, not
  findings. The clock starts when the action is assigned, not at historical last
  activity.

### D4 — Two clocks

- **Decided by:** operator (decision 3).
- **Devin proposed:** defaulting the application clock to the corpus date
  2026-08-10.
- **Why rejected:** a request entered today would have been born 0 days old only
  by accident, and every live metric would have been wrong.
- **Decision:** `SystemClock` for the application, injectable `HALYARD_AS_OF`
  for tests and demos, `audit_clock()` pinned to 2026-08-10 for the audit alone.

### D5 — Deterministic operationalization

- **Decided by:** operator (clarification 1).
- **Problem Devin's plan had:** fallback owners and triage due dates computed
  from `now()` at ingest, so two rebuilds produced different content.
- **Decision:** an explicit `operationalization_time`
  (`HALYARD_OPERATIONALIZATION_AT`, default 2026-08-10) stamps every
  system-created remediation. Historical timestamps stay verbatim; live requests
  use the application clock.

### D6 — Unresolved targets are not people

- **Decided by:** operator (decision 4).
- **Devin proposed:** `Person(identity_basis='unresolved_request_text')`.
- **Why rejected:** it would turn "VP of Security at Acme" into an apparently
  canonical individual — 199 times over.
- **Decision:** a separate `RequestTarget` holding intent (raw text, title
  family, account, nullable resolved person, candidates, confidence).
- **Amended (clarification 3):** live input *may* create a `Person` when a named
  individual is supplied with identifying evidence, recorded as
  `source_type='live_input'`.

### D7 — Owner required in the database, optional in the API

- **Decided by:** operator (clarification 2).
- **Decision:** `POST /api/requests` may omit the owner; the server resolves
  explicit → configured triage owner → requester, and the transaction does not
  commit without one. Slack-style intake should not push ownership
  administration onto the requester.
- **Tested:** all three fallback paths, plus the unresolvable case.

### D8 — Non-roster connectors are coverage gaps

- **Decided by:** operator (decision 5).
- **Decision:** ingest with `on_roster=False` and no capacity, record in
  `coverage_gaps`, and describe them as "observed connector not present in the
  managed roster". 46 of them. Not a defect, not an invalid person — a fact
  about the operating model.

### D9 — Shared domains never merge accounts

- **Decided by:** operator (decision 6), from the audit's methodology.
- **Decision:** distinct CRM account IDs stay distinct rows in a shared
  `domain_group`. 12 shared-domain records preserved. Subsidiaries and
  intentionally similar entities are protected by the `C_similar_but_distinct`
  tier.

### D10 — One matching implementation

- **Decided by:** operator (decision 7).
- **Decision:** the audit's matching primitives moved to `halyard/matching/`;
  both the audit and the application import them. Requirement: all 51 audit
  tests still pass and the audit reproduces semantically identical output.
- **Result:** 51/51 pass, audit output unchanged.

### D11 — No score in the foundation

- **Decided by:** Devin, within approved scope; operator's path-semantics
  ruling made it explicit.
- **Evidence:** every observable path is second-hop; 199/200 buyers unresolvable.
- **Decision:** ordered, labelled path evidence with stated limitations instead
  of a composite score. No field may imply an intro is available. See
  `SCORING_SPEC.md` for the rules a future ranker must obey.

### D12 — No Alembic

- **Decided by:** Devin; deviation from the stated default stack, flagged in the
  plan and approved.
- **Reasoning:** the SQLite database is a derived artifact rebuilt by
  `make ingest`. Migrations would version something that is never migrated.
- **Tradeoff:** once live rows must survive a schema change, migrations become
  necessary. A `--force` guard refuses to destroy a database containing live
  requests in the meantime.

### D13 — Silence is not an outcome

- **Decided by:** operator (audit adjustment 3, reaffirmed in the state-machine
  ruling).
- **Decision:** no `NO_RESPONSE` state. `potentially_stale` is derived on read
  and never alters state or outcome; `NO_OBSERVABLE_PATH` keeps its owner and
  next action rather than terminating.

### D14 — Coordination, not deduplication

- **Decided by:** operator.
- **Decision:** parallel asks at one account surface as related activity typed
  by closeness (`same_canonical_account` → `explicit_reask`). Nothing is
  auto-merged, auto-closed or labelled a duplicate.

---

## Deferred

| deferred | why | what would settle it |
| --- | --- | --- |
| Path ranking / score | no outcome volume to calibrate against (85 outcomes, 14 meetings) | measured outcomes per path type over time |
| Alembic migrations | the DB is currently disposable | the first schema change with live rows to preserve |
| Auth and permissions | explicitly out of scope | multi-user deployment |
| Real Slack / CRM integration | explicitly out of scope | production adoption |
| Whether missing outcome rows mean "never routed" or off-system routing | unanswered by the corpus; affects the interpretation of 115 requests | asking the BD team |
| Second-hop introduction chains (connector → colleague → buyer) | needs a UI to be useful and a human to judge | Stage 5 |
