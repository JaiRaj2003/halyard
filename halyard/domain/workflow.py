"""Next actions, their SLA clock, and staleness.

The SLA clock starts when a next action is *assigned*, not at some earlier
historical timestamp — so a request that has just been re-triaged is not
instantly overdue because the underlying ask is old. Assigning a new next action
resets the clock.

Staleness is derived, never stored, and never touches state or outcome: a quiet
request is a quiet request, not a failed one.

An SLA can only be missed by a system that was there to meet it. The legacy
corpus was imported with next actions stamped at the operationalization instant;
those are remediation targets for a backlog, not evidence that Halyard breached
anything, so they are reported separately until an operator actually works the
request here and a new action is assigned under this system.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import Settings
from .states import NEXT_ACTIONS, SETTLED_STATES, WorkflowState


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


#: Where the current next action came from.
INGEST_ASSIGNED = "ingest_operationalization"
LIVE_INTAKE_ASSIGNED = "live_intake"
OPERATOR_ASSIGNED = "operator"

#: Route evidence, kept apart from the workflow state.
CORROBORATED_PATH = "corroborated_path"
UNVERIFIED_SUGGESTED_ROUTE = "unverified_suggested_route"
NO_ROUTE_SIGNAL = "none"


def is_sla_managed(next_action_source: str) -> bool:
    """Whether this system assigned the action whose due date is being judged."""
    return next_action_source in {LIVE_INTAKE_ASSIGNED, OPERATOR_ASSIGNED}


def validate_suggested_route_action(person: str) -> str:
    """The next action for a route somebody offered but nothing corroborates."""
    who = person or "the person who suggested it"
    return f"Validate the suggested route with {who} before treating it as a candidate path."


@dataclass(frozen=True)
class NextAction:
    action: str
    assigned_at: datetime | None
    due_at: datetime | None


def assign_next_action(state: WorkflowState, assigned_at: datetime, settings: Settings) -> NextAction:
    """Next action for a state, with its due date measured from now-of-assignment."""
    if state in SETTLED_STATES:
        return NextAction("", None, None)
    return NextAction(NEXT_ACTIONS[state], assigned_at, settings.sla_due(state, assigned_at))


def age_days(request_time: datetime | None, now: datetime) -> float | None:
    request_time = _aware(request_time)
    if request_time is None:
        return None
    return (now - request_time).total_seconds() / 86400.0


def is_overdue(due_at: datetime | None, now: datetime) -> bool:
    due_at = _aware(due_at)
    return due_at is not None and now > due_at


def days_since_activity(last_activity_at: datetime | None, now: datetime) -> float | None:
    return age_days(last_activity_at, now)


def is_potentially_stale(
    workflow_state: str,
    last_activity_at: datetime | None,
    now: datetime,
    settings: Settings,
) -> bool:
    """Flag only. Says nothing about whether the request succeeded or failed."""
    if workflow_state in {s.value for s in SETTLED_STATES}:
        return False
    since = days_since_activity(last_activity_at, now)
    return since is not None and since >= settings.staleness_days


def inactivity_bucket(days: float | None) -> str:
    if days is None:
        return "unknown"
    if days < 7:
        return "0-6d"
    if days < 30:
        return "7-29d"
    if days < 60:
        return "30-59d"
    if days < 90:
        return "60-89d"
    return "90d+"
