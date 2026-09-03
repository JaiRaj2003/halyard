"""Next actions, their SLA clock, and staleness.

The SLA clock starts when a next action is *assigned*, not at some earlier
historical timestamp — so a request that has just been re-triaged is not
instantly overdue because the underlying ask is old. Assigning a new next action
resets the clock.

Staleness is derived, never stored, and never touches state or outcome: a quiet
request is a quiet request, not a failed one.
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
