# State machine

Defined in `halyard/domain/states.py`; next actions and SLA in
`halyard/domain/workflow.py`.

Four things were conflated in the source data and are separated here:

| axis | question it answers |
| --- | --- |
| `workflow_state` | where is the work? |
| `route_status` | how far did routing get? |
| `outcome` | what actually happened? |
| `potentially_stale` | should someone look at this? (derived, never stored as state) |

## Workflow states

| state | meaning | next action | SLA |
| --- | --- | --- | --- |
| `NEEDS_TRIAGE` | owner, target and liveness unconfirmed | triage | 2d |
| `NEEDS_ENTITY_REVIEW` | the target or account is ambiguous | resolve against candidates | 2d |
| `PATH_REVIEW` | candidate paths exist; a human must choose | review paths, pick a route | 2d |
| `AWAITING_CONNECTOR` | a connector has been asked | follow up | 5d |
| `INTRO_SENT` | the intro went out | confirm the meeting or outcome | 5d |
| `NO_OBSERVABLE_PATH` | no path is visible in the supplied evidence | find another route or escalate | 5d |
| `BLOCKED` | something external is in the way | unblock or escalate | 5d |
| `COMPLETED` | settled: the intro produced its outcome | — | — |
| `CLOSED` | settled: explicitly closed with a reason | — | — |

Only `COMPLETED` and `CLOSED` are settled, and only they have no next action.
`NO_OBSERVABLE_PATH` is an active operational condition — the request keeps its
owner, its next action and its place in the queue.

There is deliberately **no `NO_RESPONSE` state**. Silence is not an outcome; it
is a staleness flag on whatever state the request is actually in.

## Transitions

```
NEEDS_TRIAGE       → NEEDS_ENTITY_REVIEW, PATH_REVIEW, NO_OBSERVABLE_PATH, BLOCKED, CLOSED
NEEDS_ENTITY_REVIEW→ PATH_REVIEW, NO_OBSERVABLE_PATH, NEEDS_TRIAGE, BLOCKED, CLOSED
PATH_REVIEW        → AWAITING_CONNECTOR, NO_OBSERVABLE_PATH, NEEDS_ENTITY_REVIEW, BLOCKED, CLOSED
AWAITING_CONNECTOR → INTRO_SENT, PATH_REVIEW, NO_OBSERVABLE_PATH, BLOCKED, CLOSED
INTRO_SENT         → COMPLETED, PATH_REVIEW, BLOCKED, CLOSED
NO_OBSERVABLE_PATH → PATH_REVIEW, NEEDS_ENTITY_REVIEW, BLOCKED, CLOSED
BLOCKED            → NEEDS_TRIAGE, PATH_REVIEW, AWAITING_CONNECTOR, NO_OBSERVABLE_PATH, CLOSED
COMPLETED          → CLOSED
CLOSED             → NEEDS_TRIAGE  (reopening is deliberate and goes back through triage)
```

An illegal transition returns 409 and names what *is* allowed. Closing requires
an explicit `closure_reason` — a request cannot be disposed of silently.

## Route status and outcome

`route_status`: `NONE` → `CANDIDATES_IDENTIFIED` → `ROUTE_SELECTED` →
`CONNECTOR_CONFIRMED`, or `ROUTE_FAILED`. A connector is only
`CONNECTOR_CONFIRMED` after a human has reviewed the route.

`outcome`: `UNKNOWN`, `INTRO_SENT`, `MEETING_BOOKED`, `OPPORTUNITY_CREATED`,
`DECLINED`, `NO_INTRO`. `UNKNOWN` is a legitimate, common answer — 168 of the
200 historical requests are honestly unknown.

## How historical state was derived

State comes from explicit evidence, in this order:

1. **Outcome evidence** — an `intro_outcomes` row showing an opportunity, a
   meeting, an intro or an ask. `state_source='outcome_evidence'`, high
   confidence.
2. **Explicit Slack statements** — a message that states an intro was sent, was
   declined, or that someone is taking the request.
   `state_source='explicit_statement'`.
3. **Neither** — a triage-family state is derived from what the record supports:
   ambiguous target → `NEEDS_ENTITY_REVIEW`, candidate paths →
   `PATH_REVIEW`, otherwise `NEEDS_TRIAGE`. `state_source='declared_only'`,
   confidence `none`, and the declared status is recorded as a claim rather than
   adopted as truth.

Where the declared status contradicts the evidence, both are kept and a
`data_quality_issues` row records the contradiction — 63 such contradictions
across the corpus.

Resulting distribution over the 200 historical requests: `NEEDS_TRIAGE` 111,
`AWAITING_CONNECTOR` 53, `INTRO_SENT` 18, `COMPLETED` 14, `PATH_REVIEW` 4.

## SLA

Due dates are **product configuration defaults**, not findings from the data,
and live in `halyard/config.py::SLA_DAYS_BY_STATE`. Two days for review states,
five for waiting states. There are no priority tiers, because the supplied data
does not support them.

The clock starts when the action is *assigned*, not at the last historical
activity: `next_action_due_at = next_action_assigned_at + SLA`. Every transition
assigns a fresh action and resets the clock.

## Staleness

`potentially_stale` is computed on read, from
`days_since_activity > staleness_days` (default 30) on a non-settled request. It
never changes `workflow_state` or `outcome`, and settled requests are never
stale. Inactivity is also bucketed (`0-6d`, `7-29d`, `30-59d`, `60-89d`, `90d+`)
so leadership can see the shape of the silence rather than a single flag.
