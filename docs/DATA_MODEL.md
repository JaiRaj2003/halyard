# Data model

Defined in `halyard/db/models.py`. Every derived table carries provenance:
the `source_record_id` it came from, the match method, the confidence, the raw
value behind the canonical one, and a review status.

## Provenance layer

**`source_files`** — one row per supplied file: filename, SHA-256, byte size,
row count, parsed count, error count. The hash proves `data/raw/` was not
modified; a test recomputes it.

**`source_records`** — one row per source row: `filename`, `row_index` (the
file's line number), `raw_json` (the row verbatim), `parse_status`
(`ok` / `malformed` / `unsupported`) and `parse_error`. Nothing is dropped, so
every canonical row can be traced back to a line in a file.

## Entities

**`organizations`** — CRM accounts and companies observed only in connection
exports. Keeps `crm_account_id`, `name`, `domain`, `canonical_key`,
`domain_group`, `is_crm_account`, plus CRM attributes. Two CRM accounts sharing
a domain remain two rows in the same `domain_group`, each recording the other as
a competing candidate.

**`persons`** — real individuals only. `identity_basis` is one of
`profile_url` (4,752), `name_only_export` (278), `internal_directory` (35) or
`live_input`. A target persona is never a person: see `request_targets`.

**`affiliations`** — person ↔ organization with title, `title_family`, dates and
`date_precision`.

**`connectors`** — the managed roster (6, with `stated_monthly_capacity`) plus
observed connectors seen in outcomes but absent from the roster (46, with
`on_roster=False` and capacity `None`). The latter are recorded in
`coverage_gaps`, not as data-quality defects.

**`relationship_edges`** — connector → person/organization evidence, with
`relationship_date`, `date_precision` and the source file.

## Requests

**`intro_requests`** — the 200-row spine plus anything created live.

| group | fields |
| --- | --- |
| identity | `request_id`, `origin` (`historical_corpus` / `live_intake`), `source_record_id` |
| people | `requester_id`, `observed_owner_id` (nullable), `operational_owner_id` (**not null**), `operational_owner_source`, `observed_owner_evidence`, `was_ownerless_at_ingest` |
| target | `organization_id`, `raw_ask`, and the `request_targets` row |
| state | `workflow_state`, `route_status`, `outcome`, `state_source`, `state_confidence`, `state_evidence` |
| work | `next_action`, `next_action_assigned_at`, `next_action_due_at`, `selected_connector_id` |
| time | `requested_at`, `last_activity_at`, `operationalized_at`, `closed_at` |
| declared | `declared_status`, `declared_path_found_flag` — kept as claims, checked against evidence, never trusted |

**`request_targets`** — request *intent*, separate from identity: raw target
text, name, title, `normalized_title_family`, account, nullable
`resolved_person_id`, `resolution_status`, method, confidence, evidence and
candidate matches. 199 of 200 historical targets do not resolve to a person, and
that stays visible instead of being papered over.

**`intro_candidate_paths`** — connector → target evidence per request:
`hop_type`, `observability` (`historically_observable` / `snapshot_only` /
`post_dates_request`), `connector_reachable`, `same_title_family`,
`relationship_date`, `confidence`, `limitations`, `evidence`, `source_file`.
There is no field that means "an intro is available".

**`intro_events`** — the timeline: Slack messages, outcome milestones, operator
transitions. `asserted_by` and `is_state_evidence` record whether an event was
used to derive state.

**`intro_outcomes`** — the supplied outcome row, preserved as recorded.

## Cross-cutting

**`entity_matches`** — every match decision, including the ones that failed:
subject, tier, method, evidence, verdict (`resolved` / `ambiguous` /
`unmatched`) and competing candidates. This is what makes ambiguity inspectable
rather than merely absent.

**`data_quality_issues`** — contradictions, e.g. a declared "intro sent" with no
outcome evidence, or a declared "no path" contradicted by a dated connection.

**`coverage_gaps`** — things the operating model does not cover, kept
deliberately apart from defects. Currently: 46 observed connectors not on the
managed roster.

**`account_coordination`** — related activity at one account, typed by
`relation_type`: `same_canonical_account` (203), `same_account_same_title_family`
(21), `same_account_same_target_person` and `explicit_reask` (62), with
`days_apart`, `within_window` and `same_requester`. Nothing here merges or
blocks a request; it exists so an operator can see the other live asks.

**`build_metadata`** — how this database was built: ingestion time,
operationalization instant, raw directory, source hashes.
