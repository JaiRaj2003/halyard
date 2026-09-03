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
