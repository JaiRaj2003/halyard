# Scoring specification

## There is no score

The foundation deliberately ships **no ranking model, no weights and no
composite path score.** This is a decision, not an omission.

The audit established that every observable path in the corpus is second-hop:
0 of 200 requests have a connector who knows the requested buyer, and 199 of 200
requested buyers cannot be resolved to a person in the connection exports at
all. A numeric score over that evidence would be a confident-looking number
manufactured from an absence — precisely the "fake precision" the product exists
to eliminate. An operator who trusts a 0.82 they cannot interrogate is worse off
than one reading three labelled facts.

## What replaces it

Candidate paths are **ordered by observability and labelled with their
evidence**. Each path carries:

| field | example | why it is there |
| --- | --- | --- |
| `hop_type` | `connector_to_account_colleague` | how indirect the reach actually is |
| `observability` | `historically_observable` / `snapshot_only` / `post_dates_request` | whether the relationship demonstrably existed at request time |
| `relationship_date` + `date_precision` | `2024-03-11`, `day` | the fact behind the label |
| `connector_reachable` | true/false | whether the connector is on the managed roster |
| `same_title_family` | true/false | whether the known contact is in the target's function |
| `confidence` | `high` / `medium` / `low` | how good the underlying entity match was |
| `limitations` | "investor-network edge is undated; existence at request time unknown" | what this path does *not* prove |
| `evidence` | the raw row and source file | so the operator can check |

Ordering is by observability, then confidence — both of which the operator can
see and disagree with.

## Rules any future ranking must obey

1. **No field may imply an introduction is available.** A path says where to
   investigate. `intro_available`, `can_intro` and similar names are banned, and
   a test asserts their absence from the schema and the API payloads.
2. **Every component must be displayable.** If a factor cannot be shown next to
   the result in a sentence an operator understands, it does not go in.
3. **Undated evidence may never be scored as if dated.** `snapshot_only` is a
   ceiling on what can be claimed, not a discount factor.
4. **Ambiguous entity resolution may not be silently resolved by the ranker.**
   An ambiguous target goes to `NEEDS_ENTITY_REVIEW`; it does not become a
   low-scoring path.
5. **Weights are configuration, not code**, and any weight introduced must be
   justified against measured outcomes — which requires outcome data this corpus
   does not yet contain (85 outcome rows, 14 meetings).

## Prioritisation that does exist

The queue is ordered by things that are facts rather than estimates: overdue
status against the configured SLA, deal value as supplied by the CRM, inactivity
bucket, and workflow state. `GET /api/metrics/stale` sorts by value; the
leadership summary reports stalled value alongside its denominator. None of that
is a model — it is arithmetic over recorded fields, and each number can be
traced to the rows behind it.

---

## Amendment (Stage 5): evidence-based investigation priority

Stage 5 introduces a **deterministic ordering** of candidate paths. The rules
above still hold; in particular there is still no score shown to anybody.

### What it is, and what it is not

It answers one question: **which lead should an operator check first?** It is
not relationship strength, not the probability that an introduction happens, and
not a success likelihood. Nothing in the corpus supports those claims — 85
outcome rows and 14 meetings cannot calibrate a probability, and 0/200 requests
have a connector who knows the requested buyer.

### How the order is produced

`halyard/services/ranking.py` sums integer weights from
`Settings.path_factor_weights` (defaults in `halyard/config.py`, one table, no
constants scattered through the code). Ties break on connector name then path
id, so the order is stable across rebuilds.

| factor | default | direction |
| --- | ---: | --- |
| `historically_observable` | +40 | relationship was observable before the ask |
| `snapshot_only` | 0 | undated: no recency signal either way |
| `post_dates_request` | -40 | relationship began after the ask |
| `direct_target_person` | +25 | direct connection to the requested person |
| `same_title_family` | +12 | contact is in the requested function |
| `colleague_at_account` | +6 | contact is a colleague at the account |
| `investor_relationship` | +4 | investor/board edge to the account |
| `connector_on_roster` | +15 | capacity and willingness are known |
| `connector_off_roster` | -10 | observed connector, unmanaged: capacity unknown |
| `corroborated_by_second_source` | +10 | the edge appears in more than one source file |
| `connector_prior_successful_intro` | +12 | connector has an observed intro sent/meeting |
| `connector_over_stated_capacity` | -20 | above the roster's stated monthly capacity |
| `connector_recent_ask` | -3 each, floor -15 | rolling load in the configured window |
| `connector_already_engaged_on_account` | -8 | already carrying a live ask at this account |
| `no_direct_buyer_relationship` | 0 | stated on every indirect path; never a penalty |

Weights that are 0 exist to be *said*, not to move the order: an operator needs
to read "no direct relationship to the requested buyer is verified" on every
second-hop path.

### What the operator sees

The top path is labelled **"Recommended to investigate first"** followed by the
sentence for each factor that fired, then the ordered alternatives. The
composite total is never serialised into an API response and never rendered —
"Priority 75" would imply a calibration these heuristics do not have. A test
asserts no `score`/`priority`/`weight` key reaches the payload.

### Resilience

A factor that has no evidence simply does not fire: an undated edge, a connector
with no roster row, no outcome history, or no load data all narrow the
explanation rather than breaking the ranking. Every factor has a unit test.
