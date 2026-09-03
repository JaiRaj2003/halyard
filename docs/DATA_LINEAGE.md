# Data lineage

Every canonical row traces back to a line in a file in `data/raw/`. This
document records what each source contributes, how it is transformed, and how
the counts reconcile. `make ingest` prints the same reconciliation.

## Sources

| file | rows | contributes |
| --- | --- | --- |
| `intro_requests.csv` | 200 | the request spine, requester, target text/title/account, declared status and path flag, deal value, urgency |
| `intro_outcomes.csv` | 85 | connector asked, asked/response/intro dates, meeting and opportunity flags |
| `crm_accounts.csv` | 50 | canonical accounts, domain, industry, HQ, stage, ARR potential, owner |
| `connector_roster.csv` | 6 | managed connectors and their stated monthly capacity |
| `investor_network.csv` | 73 | investor/advisor relationships — **undated** |
| `connections_*.csv` (6 files) | 5,075 | connector → person relationships with `connected_on` |
| `slack_threads.jsonl` | 200 threads / 523 messages | request timeline and explicit statements |
| `BD Ops Takehome Assignment.docx` | — | prose brief; not a data source, recorded as unparsed |
| `.gitkeep` | — | placeholder, recorded as unparsed |

## Reconciliation

Printed by `make ingest`, asserted by `tests/test_ingest.py`:

| check | supplied | canonical |
| --- | --- | --- |
| requests in spine | 200 | 200 |
| outcome rows | 85 | 85 |
| CRM accounts | 50 | 50 |
| roster connectors | 6 | 6 |
| connection export rows | 5,075 | 5,075 |
| Slack threads | 200 | 200 |
| Slack messages classified | 523 | 523 |
| non-data files not parsed | 1 | 1 |

The Slack figure is the one that caught a real bug: an early build reported 557
because derived events (`derived:additional_ask_like_message`,
`derived:referral_suggestion`) were being counted alongside actual messages.
Derived events are now classified separately, and the count reconciles exactly.

## Transformations

**Staging.** Each file is hashed (SHA-256), then every row is written to
`source_records` with its raw JSON, its line number and a parse status. Rows
that fail to parse are stored with the error, never skipped.

**Normalization.** Company strings are lowercased, stripped of legal suffixes
and punctuation (`canonical_key`); person names are transliterated and
case-folded (`norm_person`); titles are mapped to a `title_family`; dates are
parsed to a date with an explicit `date_precision`, and an unparseable date
becomes null rather than a guess.

**Accounts.** CRM rows become organizations keyed by `crm_account_id`.
External company strings resolve against them by exact ID, then unique
normalized name, then unique domain. A domain shared by several CRM accounts
produces a `domain_group` and an *ambiguous* verdict — never a merge.

**People.** Connection-export rows become persons keyed by `profile_url` where
present, otherwise by normalized name plus company. Rows without a profile URL
(278) get `identity_basis='name_only_export'` and a `missing_profile_url`
data-quality issue at low severity.

**Connectors.** The roster gives six managed connectors. Connector names
appearing in outcomes but not on the roster (46) are created with
`on_roster=False`, no capacity, and a `coverage_gaps` row.

**Requests.** Each spine row becomes an `IntroRequest` plus a `RequestTarget`.
State is derived from explicit evidence — the outcome row and Slack statements —
and falls back to a triage state where evidence is insufficient. The declared
status is kept as a claim and checked against evidence rather than believed.

**Paths.** For each request, connector relationships to the target account are
emitted as candidate paths and labelled by observability against the request
date. Investor-network edges are undated and therefore always `snapshot_only`.

**Coordination.** Requests at the same canonical account within the
coordination window produce `account_coordination` rows, typed by how closely
they overlap.

## Derived facts created by the system

Fallback ownership, the triage next action and its due date do not exist in the
sources; the system creates them. They are stamped with `operationalization_at`
(default 2026-08-10, configurable via `HALYARD_OPERATIONALIZATION_AT`) rather
than `now()`, so two rebuilds on different days produce identical content. Each
is marked: `operational_owner_source='fallback_requester'` and
`was_ownerless_at_ingest=true` say plainly that the system supplied the owner,
not the record.
