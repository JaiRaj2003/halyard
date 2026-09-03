# Product specification

## The problem, as evidenced

The forensic audit (`DATA_AUDIT.md`, `INITIAL_PROBLEM_RANKING.md`) tested four
candidate failures against the supplied year of data. The ranking was decided by
evidence, not intuition:

| candidate failure | verdict |
| --- | --- |
| **No owner and no state of record** | **selected** — 159/200 unresolved and silent 30+ days, $106.5M of $137.8M pipeline; 115/200 never reached a connector; 150/200 self-contradictory |
| Missed warm paths | second — 46/109 "no path" requests had a pre-dating connection, but every observable path is second-hop and 0/200 requests have a connector who knows the requested buyer |
| Connector overload | rejected — 2/49 connector-months exceeded stated capacity |
| Duplicate asks | real but downstream — 200 requests over 52 target companies, which is a symptom of nobody being able to see existing activity |

Requests were not being declined. They were going quiet, and nothing in the
system noticed or cared.

## Thesis

The fastest path into a target account is a warm introduction, and warm
introductions fail operationally rather than relationally. If every request has
an owner, a state, a next action and a due date — each traceable to its
evidence — the pipeline stops evaporating in silence.

## Users

**Primary: the BD operator.** Runs the intro pipeline. Needs to know what is
mine, what is overdue, what has gone quiet, what is already happening at this
account, and who might be able to reach this target.

**Secondary: leadership.** Reads the same data. Needs coverage, ownership,
stalled value and connector load — with history and present state distinguished,
not blended.

## Core workflow

```
intake → NEEDS_TRIAGE
         ↳ ambiguous target/account → NEEDS_ENTITY_REVIEW
         ↳ candidate paths exist     → PATH_REVIEW      (a human chooses)
         ↳ none exist                → NO_OBSERVABLE_PATH (still owned, still active)
       → AWAITING_CONNECTOR → INTRO_SENT → COMPLETED
       anything → BLOCKED, or CLOSED with an explicit reason
```

Nothing leaves the workflow by going quiet. `CLOSED` requires a reason;
`NO_OBSERVABLE_PATH` is an active condition with a next action, not a grave.

## Scope of the foundation

Delivered here:

1. **Reproducible ingestion.** `data/raw/` → SQLite, idempotent, reconciled,
   nothing discarded.
2. **Canonical model with provenance.** Every derived row traces to a source
   record, a match method, a confidence and a review status.
3. **Conservative entity resolution** with ambiguity preserved and shared with
   the audit.
4. **Request reconstruction** — the 200-row spine, with ownership, state, route
   status, outcome, next action and evidence.
5. **Time-aware path evidence.**
6. **Account coordination** between parallel asks at one account.
7. **Backend APIs** for search, detail, intake, listing, transitions, ownership,
   duplicates/overlap, staleness, connector load and leadership metrics.
8. **Tests**, including ten executable invariants.
9. **Documentation**, including what the system cannot claim.

Explicitly not in the foundation: the polished frontend, authentication,
permissions, a ranking model or score, external APIs, and any live CRM or Slack
integration.

## Product guarantees

These are enforced in code and tested in `tests/test_invariants.py`:

1. Historical ownerlessness stays measurable after ingestion.
2. Every live request has an operational owner from the moment it exists.
3. Connector and workflow owner are separate concepts; being asked is not owning.
4. A request with no observable path keeps its owner and its next action.
5. A candidate path never implies an introduction is available.
6. Unresolved target intent never creates a canonical person.
7. Parallel activity at one account is coordinated, not labelled a duplicate.
8. The live application clock is not the audit's corpus date.
9. Staleness never determines state or outcome.
10. The forensic audit still reproduces from the shared matching code.

## What "done" looks like for the next stage

An operator opens their queue, sees eleven overdue requests with reasons, opens
one, sees the ask, the account, three candidate paths with their observability
labels and limitations, notices two other live asks at the same account, picks a
connector, and moves the request forward — with every claim on the screen
showing where it came from.
