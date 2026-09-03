# How Devin was used

A record of the working method, for the presentation section on AI usage. The
short version: Devin was used to make claims falsifiable, and the operator's job
was to refuse the plausible ones.

## Stages

| stage | mode | what Devin did | what the operator did |
| --- | --- | --- | --- |
| 1. Structure | agent | created the repo skeleton (PR #1) | specified the layout |
| 2. Discovery | ask | first pass over the raw files, proposed a build | rejected building anything yet |
| 3. Audit plan | ask | proposed sources, matching tiers, analyses, tests and eight biasing assumptions | approved subject to four methodological adjustments |
| 4. Forensic audit | agent | ran the audit, ranked four candidate failures on evidence (PR #2) | reviewed the evidence, selected the failure |
| 5. Foundation plan | agent | translated the handoff into a technical plan, surfaced seven unspecified decisions | issued seven authoritative decisions, then three clarifications |
| 6. Foundation build | agent | this implementation | approved scope, held the line on invariants |

## The four audit adjustments that changed the findings

Devin's initial audit plan would have produced wrong answers in four specific
ways. The operator caught each before execution:

1. **Domain is not identity.** Devin was ready to treat a shared normalized
   domain as proof two CRM accounts were the same. That would have collapsed
   subsidiaries and business units. Now: CRM ID is definitive, unique domain is
   strong evidence, shared domain preserves both rows.
2. **Paths must be time-aware.** Devin's "missed path" metric would have counted
   relationships that did not exist when the request was made. Now split into
   `historically_observable` (dated, `connected_on <= request_date`) versus
   `snapshot_only`.
3. **State is not staleness.** Devin was going to infer request state from Slack
   recency, which would have labelled quiet requests as failed. Now state comes
   from explicit evidence only, and staleness is an independent derived axis.
4. **Guard the denominator.** Reconcile Slack against the 200-row spine and
   report out-of-spine activity separately rather than silently inflating the
   denominator.

The audit's headline finding — that ownership, not capacity, is the failure —
survived all four adjustments. Devin's *first instinct* had been capacity and
duplicates, from a quick look at the data. The audit disproved it: 2 of 49
connector-months over capacity.

## The seven decisions Devin got wrong or left open

At the foundation-plan stage, Devin surfaced seven decisions it could not make
alone. The operator's rulings materially changed the build:

- Devin proposed one `owner_id`; the operator split observed from operational
  ownership so that 192 historically ownerless requests stay visible.
- Devin proposed priority-tier SLAs; the operator pointed out the data has no
  priority field.
- Devin proposed defaulting the app clock to the corpus date; the operator
  separated the application, audit and test clocks.
- Devin proposed creating `Person` rows from unresolved request text; the
  operator required a separate `RequestTarget`, preventing 199 fabricated
  people.
- The operator then caught a determinism bug in the approved plan: ingest-time
  fallback owners computed from `now()` would make rebuilds non-reproducible.
  Hence `operationalization_time`.

## What Devin was good at

- Exhaustive, reproducible arithmetic over 5,075 connections, 200 requests, 523
  Slack messages and 85 outcomes, with the script kept as the evidence.
- Holding a large invariant set consistent across ~40 modules and 132 tests.
- Writing the unglamorous parts — staging every row with a parse status, hashing
  every source file, recording every match decision including the failures.
- Catching its own reconciliation errors when forced to reconcile (the Slack
  count 557 vs 523 was a real bug it found and fixed).

## What it needed a human for

- Refusing to build during discovery.
- Every judgement where a plausible simplification would have destroyed a
  finding — all four audit adjustments and D2, D3, D4, D6 in the decision log.
- Noticing that determinism, not correctness, was the risk in the ingest design.
- Deciding that the less impressive product was the right one.

## Verification, not trust

Nothing here rests on Devin asserting it worked:

- 81 application tests plus 51 audit tests, including ten invariant tests that
  encode the product guarantees as executable assertions.
- Every source file hashed and every count reconciled, checked in CI-able tests.
- `make verify` runs lint, a clean rebuild from `data/raw/`, the full suite and
  the audit end to end.
- The audit remains independently runnable: `python analysis/audit/run_audit.py`.
