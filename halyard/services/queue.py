"""The operator queue: named views over the same rows, each with a definition.

There is no "unowned" view. Every request in this system has an operational
owner by construction, so a queue of ownerless requests would always be empty
and would quietly imply the guarantee can fail. The historical fact that many
requests arrived without an owner is preserved instead as
``was_ownerless_at_ingest`` and surfaced by the **needs ownership review** view:
those requests are owned today, by fallback, and a human should confirm the
fallback was right.

Each view states its own definition so an operator can see what a count means
before acting on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..config import Settings
from ..db.models import AccountCoordination, IntroRequest
from ..domain.states import SETTLED_STATES, WorkflowState
from .requests import request_summary

#: How near a due date has to be before it is "due soon".
DUE_SOON_DAYS = 2


@dataclass(frozen=True)
class View:
    key: str
    label: str
    definition: str
    predicate: Callable[[dict], bool]


def _active(item: dict) -> bool:
    return item["workflow_state"] not in {state.value for state in SETTLED_STATES}


def _state(*states: WorkflowState) -> Callable[[dict], bool]:
    values = {state.value for state in states}
    return lambda item: item["workflow_state"] in values


VIEWS: tuple[View, ...] = (
    View(
        "all",
        "All requests",
        "Every request in the system, historical and live.",
        lambda item: True,
    ),
    View(
        "in_flight",
        "In flight",
        "Requests in an active state — somebody still owes this an action.",
        _active,
    ),
    View(
        "needs_triage",
        "New / needs triage",
        "Accepted but not yet triaged: owner, target and whether the ask is still live.",
        _state(WorkflowState.NEEDS_TRIAGE),
    ),
    View(
        "needs_entity_review",
        "Needs entity review",
        "The target account or person is ambiguous or unresolved; a human has to choose.",
        _state(WorkflowState.NEEDS_ENTITY_REVIEW),
    ),
    View(
        "needs_ownership_review",
        "Needs ownership review",
        (
            "Arrived in the corpus without any evidenced owner and was given a fallback owner at "
            "ingest. Owned today; the fallback still needs confirming."
        ),
        lambda item: item["was_ownerless_at_ingest"] and _active(item),
    ),
    View(
        "path_review",
        "Path review",
        "Candidate paths exist and are waiting on a human route decision.",
        _state(WorkflowState.PATH_REVIEW),
    ),
    View(
        "awaiting_connector",
        "Awaiting connector",
        "A connector has been asked; the request is waiting on their reply.",
        _state(WorkflowState.AWAITING_CONNECTOR),
    ),
    View(
        "no_observable_path",
        "No observable path",
        "No path is visible in the supplied network. Active and owned, not closed.",
        _state(WorkflowState.NO_OBSERVABLE_PATH),
    ),
    View(
        "due_soon",
        "Due soon",
        f"Next action falls due within {DUE_SOON_DAYS} days and is not yet overdue.",
        lambda item: bool(item.get("due_soon")) and not item["is_overdue"],
    ),
    View(
        "overdue",
        "Overdue",
        "The next action passed its due date. Due dates run from when the action was assigned.",
        lambda item: item["is_overdue"],
    ),
    View(
        "stale",
        "Quiet / potentially stale",
        (
            "No activity for longer than the staleness window while still active. Staleness is an "
            "independent flag: it never changes the state or the outcome."
        ),
        lambda item: item["potentially_stale"],
    ),
    View(
        "overlapping",
        "Overlapping activity",
        (
            "Related to at least one other request on the same account. Different targets at one "
            "account are parallel work to coordinate, not duplicates."
        ),
        lambda item: item.get("related_count", 0) > 0,
    ),
    View(
        "completed",
        "Completed",
        "An introduction was made and the request was settled.",
        _state(WorkflowState.COMPLETED),
    ),
    View(
        "outcome_unknown",
        "Outcome unknown",
        (
            "Settled or asked, but no observed outcome was recorded. Unknown is reported as "
            "unknown and never inferred from silence."
        ),
        lambda item: item["outcome"] == "UNKNOWN" and not _active(item),
    ),
)

VIEWS_BY_KEY = {view.key: view for view in VIEWS}


class UnknownView(ValueError):
    def __init__(self, key: str):
        super().__init__(f"unknown queue view '{key}'; known views: {', '.join(VIEWS_BY_KEY)}")


def _decorate(session: Session, items: list[dict], now, settings: Settings) -> list[dict]:
    """Add the two per-row facts the queue needs but a request summary does not carry."""
    ids = [item["id"] for item in items]
    related: dict[int, int] = {}
    if ids:
        for row in session.scalars(
            select(AccountCoordination).where(
                AccountCoordination.request_id_a.in_(ids) | AccountCoordination.request_id_b.in_(ids)
            )
        ).all():
            for side in (row.request_id_a, row.request_id_b):
                related[side] = related.get(side, 0) + 1
    horizon = now + timedelta(days=DUE_SOON_DAYS)
    for item in items:
        due = item["next_action_due_at"]
        item["related_count"] = related.get(item["id"], 0)
        item["due_soon"] = bool(due and not item["is_overdue"] and due <= horizon)
    return items


def queue(
    session: Session,
    settings: Settings,
    clock: Clock,
    view: str = "in_flight",
    owner_id: int | None = None,
    account_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """One view of the queue, with the definition of the view alongside the rows."""
    if view not in VIEWS_BY_KEY:
        raise UnknownView(view)
    now = clock.now()
    stmt = select(IntroRequest)
    if owner_id is not None:
        stmt = stmt.where(IntroRequest.operational_owner_id == owner_id)
    if account_id is not None:
        stmt = stmt.where(IntroRequest.organization_id == account_id)
    items = _decorate(
        session,
        [request_summary(request, now, settings) for request in session.scalars(stmt).all()],
        now,
        settings,
    )
    chosen = VIEWS_BY_KEY[view]
    matched = [item for item in items if chosen.predicate(item)]
    matched.sort(key=lambda item: (item["next_action_due_at"] is None, item["next_action_due_at"], item["request_id"]))
    return {
        "view": {"key": chosen.key, "label": chosen.label, "definition": chosen.definition},
        "counts": {other.key: sum(1 for item in items if other.predicate(item)) for other in VIEWS},
        "total": len(matched),
        "limit": limit,
        "offset": offset,
        "items": matched[offset: offset + limit],
    }


def view_catalogue() -> list[dict]:
    return [{"key": view.key, "label": view.label, "definition": view.definition} for view in VIEWS]


__all__ = ["DUE_SOON_DAYS", "UnknownView", "VIEWS", "VIEWS_BY_KEY", "queue", "view_catalogue"]
