"""Operational and leadership metrics, all on the application clock.

Every number here is computed against ``clock.now()`` — the live application
clock, never the audit's 2026-08-10 corpus date. A request entered today is a
day old, not two years old.

Staleness is reported as a flag beside the state, never folded into it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..config import Settings
from ..db.models import (
    BuildMetadata,
    Connector,
    CoverageGap,
    DataQualityIssue,
    IntroCandidatePath,
    IntroOutcome,
    IntroRequest,
    Organization,
    Person,
    RequestTarget,
    SourceFile,
)
from ..db.session import sessionmaker_for
from ..domain.states import SETTLED_STATES, WorkflowState
from ..domain.workflow import days_since_activity, inactivity_bucket, is_overdue, is_potentially_stale
from .queue import queue as queue_view
from .requests import request_summary


def stale_requests(session: Session, settings: Settings, clock: Clock, limit: int = 100) -> dict:
    now = clock.now()
    requests = session.scalars(select(IntroRequest)).all()
    stale = [
        request
        for request in requests
        if is_potentially_stale(request.workflow_state, request.last_activity_at, now, settings)
    ]
    buckets: dict[str, int] = defaultdict(int)
    for request in stale:
        buckets[inactivity_bucket(days_since_activity(request.last_activity_at, now))] += 1
    stale.sort(key=lambda request: (-request.deal_value_usd, request.request_id))
    return {
        "as_of": now,
        "staleness_days": settings.staleness_days,
        "note": (
            "Staleness is a flag for attention, not an outcome. These requests are still in their derived workflow "
            "state and still have an owner and a next action."
        ),
        "total_requests": len(requests),
        "stale_count": len(stale),
        "stale_value_usd": sum(request.deal_value_usd for request in stale),
        "by_inactivity_bucket": dict(sorted(buckets.items())),
        "overdue_next_actions": sum(1 for request in requests if is_overdue(request.next_action_due_at, now)),
        "items": [request_summary(request, now, settings) for request in stale[:limit]],
    }


def connector_load(session: Session, settings: Settings, clock: Clock) -> dict:
    """Rolling load per connector, against stated capacity where one exists."""
    now = clock.now()
    window_start = now - timedelta(days=settings.connector_load_window_days)
    connectors = session.scalars(select(Connector).order_by(Connector.name)).all()
    outcomes = session.scalars(select(IntroOutcome)).all()
    requests = {request.id: request for request in session.scalars(select(IntroRequest)).all()}

    asks_in_window: dict[int, int] = defaultdict(int)
    asks_total: dict[int, int] = defaultdict(int)
    open_asks: dict[int, int] = defaultdict(int)
    for outcome in outcomes:
        if outcome.connector_id is None:
            continue
        asks_total[outcome.connector_id] += 1
        if outcome.asked_date and datetime(
            outcome.asked_date.year, outcome.asked_date.month, outcome.asked_date.day, tzinfo=now.tzinfo
        ) >= window_start:
            asks_in_window[outcome.connector_id] += 1
        request = requests.get(outcome.request_id)
        if request and request.workflow_state not in {state.value for state in SETTLED_STATES}:
            open_asks[outcome.connector_id] += 1
    for request in requests.values():
        connector_id = request.selected_connector_id
        if connector_id is None:
            continue
        if request.route_confirmed_at is not None:
            asks_total[connector_id] += 1
            if request.route_confirmed_at >= window_start:
                asks_in_window[connector_id] += 1
        if request.workflow_state == WorkflowState.AWAITING_CONNECTOR.value:
            open_asks.setdefault(connector_id, 0)

    rows = []
    for connector in connectors:
        capacity = connector.stated_monthly_capacity
        in_window = asks_in_window.get(connector.id, 0)
        rows.append(
            {
                "connector_id": connector.id,
                "connector": connector.name,
                "on_roster": connector.on_roster,
                "connector_type": connector.connector_type,
                "stated_monthly_capacity": capacity,
                "asks_in_window": in_window,
                "asks_total_observed": asks_total.get(connector.id, 0),
                "open_asks": open_asks.get(connector.id, 0),
                "capacity_utilisation": None if not capacity else round(in_window / capacity, 2),
                "over_capacity": bool(capacity and in_window > capacity),
                "note": (
                    ""
                    if connector.on_roster
                    else "Observed connector not present in the managed connector roster; capacity unknown."
                ),
            }
        )
    rows.sort(key=lambda row: (-row["asks_in_window"], row["connector"]))
    return {
        "as_of": now,
        "window_days": settings.connector_load_window_days,
        "roster_size": sum(1 for connector in connectors if connector.on_roster),
        "off_roster_observed": sum(1 for connector in connectors if not connector.on_roster),
        "connectors": rows,
    }


def leadership(session: Session, settings: Settings, clock: Clock) -> dict:
    now = clock.now()
    requests = session.scalars(select(IntroRequest)).all()
    total = len(requests)
    by_state: dict[str, int] = defaultdict(int)
    by_owner: dict[str, dict] = {}
    stale_value = 0
    stale_count = 0
    overdue = 0
    for request in requests:
        by_state[request.workflow_state] += 1
        owner = request.operational_owner.display_name
        bucket = by_owner.setdefault(owner, {"owner": owner, "open": 0, "overdue": 0, "value_usd": 0})
        settled = request.workflow_state in {state.value for state in SETTLED_STATES}
        if not settled:
            bucket["open"] += 1
            bucket["value_usd"] += request.deal_value_usd
        if is_overdue(request.next_action_due_at, now):
            overdue += 1
            bucket["overdue"] += 1
        if is_potentially_stale(request.workflow_state, request.last_activity_at, now, settings):
            stale_count += 1
            stale_value += request.deal_value_usd

    ownerless_at_ingest = sum(1 for request in requests if request.was_ownerless_at_ingest)
    #: Anything with a drill-down is counted by the queue view it drills into, so a
    #: leadership number and the list behind it can never disagree.
    counts = queue_view(session, settings, clock, view="all", limit=1)["counts"]
    in_flight = counts["in_flight"]
    load = connector_load(session, settings, clock)
    over_capacity = sum(1 for row in load["connectors"] if row["over_capacity"])
    #: Only roster connectors state a capacity, so only they can be over it.
    with_stated_capacity = sum(1 for row in load["connectors"] if row["stated_monthly_capacity"])
    observable = session.scalar(
        select(func.count(func.distinct(IntroCandidatePath.request_id))).where(
            IntroCandidatePath.observability == "historically_observable"
        )
    )
    unresolved_targets = session.scalar(
        select(func.count()).select_from(RequestTarget).where(RequestTarget.resolution_status != "resolved")
    )
    return {
        "as_of": now,
        "clock": "application clock (live time); the 2026-08-10 corpus date is used only by the forensic audit",
        "requests_total": total,
        "requests_with_operational_owner": sum(1 for r in requests if r.operational_owner_id is not None),
        "historically_ownerless_at_ingest": ownerless_at_ingest,
        "ownership_note": (
            f"{ownerless_at_ingest} of {total} requests had no evidenced owner in the source data; every one of them "
            "has an operational owner now. The historical fact is preserved, not overwritten."
        ),
        "by_workflow_state": dict(sorted(by_state.items())),
        "by_outcome": _counts(session, IntroRequest.outcome),
        "by_route_status": _counts(session, IntroRequest.route_status),
        "open_value_usd": sum(
            request.deal_value_usd
            for request in requests
            if request.workflow_state not in {state.value for state in SETTLED_STATES}
        ),
        "stale_count": stale_count,
        "stale_value_usd": stale_value,
        "overdue_next_actions": overdue,
        "requests_with_observable_path": int(observable or 0),
        "targets_unresolved": int(unresolved_targets or 0),
        "coverage_gaps": int(session.scalar(select(func.count()).select_from(CoverageGap)) or 0),
        "data_quality_issues": int(session.scalar(select(func.count()).select_from(DataQualityIssue)) or 0),
        "by_owner": sorted(by_owner.values(), key=lambda row: (-row["open"], row["owner"])),
        "metrics": [
            _metric(
                "in_flight", "Requests in flight", counts["in_flight"], total,
                "Requests in a non-settled workflow state.", "as of now", "in_flight",
            ),
            _metric(
                "stale", "Quiet / potentially stale", counts["stale"], in_flight,
                f"Active requests with no activity for more than {settings.staleness_days} days. A flag, never an "
                "outcome.", f"rolling {settings.staleness_days} days", "stale",
            ),
            _metric(
                "overdue", "Overdue next actions", counts["overdue"], total,
                "The assigned next action passed its due date. Due dates run from when the action was assigned.",
                "as of now", "overdue",
            ),
            _metric(
                "needs_ownership_review", "Needs ownership review", counts["needs_ownership_review"], in_flight,
                f"Active requests that arrived with no evidenced owner and hold a fallback owner "
                f"({ownerless_at_ingest} of {total} across the whole corpus). No current request is ownerless.",
                "as of now", "needs_ownership_review",
            ),
            _metric(
                "overlapping", "Overlapping account activity", counts["overlapping"], total,
                "Requests sharing a canonical account with at least one other request. Related work to coordinate, "
                "not duplicates.", "whole corpus", "overlapping",
            ),
            _metric(
                "outcome_unknown", "Outcome unknown", counts["outcome_unknown"], total,
                "Settled with no recorded outcome. Unknown is reported as unknown, never inferred from silence.",
                "whole corpus", "outcome_unknown",
            ),
            _metric(
                "no_observable_path", "No observable path", counts["no_observable_path"], total,
                "No path is visible in the supplied network. Active and owned, not closed.",
                "as of now", "no_observable_path",
            ),
            _metric(
                "connectors_over_capacity", "Connectors above stated capacity", over_capacity,
                with_stated_capacity,
                "Connectors whose asks in the rolling window exceed their stated monthly capacity, out of the "
                f"{with_stated_capacity} roster connectors that state one; the other "
                f"{load['off_roster_observed']} observed connectors have no stated capacity to exceed.",
                f"rolling {settings.connector_load_window_days} days", None,
            ),
        ],
    }


def _metric(
    key: str,
    label: str,
    value: int,
    denominator: int | None,
    definition: str,
    window: str,
    drill_down_view: str | None,
) -> dict:
    """One leadership number, with the denominator and window it is true for."""
    return {
        "key": key,
        "label": label,
        "value": value,
        "denominator": denominator,
        "definition": definition,
        "window": window,
        "drill_down_view": drill_down_view,
    }


def _counts(session: Session, column) -> dict[str, int]:
    rows = session.execute(select(column, func.count()).group_by(column)).all()
    return {str(value): int(count) for value, count in sorted(rows)}


def ingestion_snapshot(engine: Engine) -> dict:
    """What the current database was built from — printed by ``make report``."""
    with sessionmaker_for(engine)() as session:
        files = session.scalars(select(SourceFile).order_by(SourceFile.filename)).all()
        return {
            "build_metadata": {
                row.key: row.value for row in session.scalars(select(BuildMetadata).order_by(BuildMetadata.key)).all()
            },
            "source_files": [
                {
                    "filename": source.filename,
                    "sha256": source.sha256[:16],
                    "records": source.record_count,
                    "parsed": source.parsed_count,
                    "errors": source.error_count,
                }
                for source in files
            ],
            "canonical_counts": {
                "organizations": int(session.scalar(select(func.count()).select_from(Organization)) or 0),
                "persons": int(session.scalar(select(func.count()).select_from(Person)) or 0),
                "connectors": int(session.scalar(select(func.count()).select_from(Connector)) or 0),
                "requests": int(session.scalar(select(func.count()).select_from(IntroRequest)) or 0),
                "candidate_paths": int(session.scalar(select(func.count()).select_from(IntroCandidatePath)) or 0),
            },
        }
