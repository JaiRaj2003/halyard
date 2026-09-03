"""Request intake, listing, detail, transitions and ownership.

The product guarantee lives here: a request cannot be persisted without an
operational owner. The caller may omit one — Slack-style intake should not push
ownership administration onto the person asking for help — and the server
resolves it (explicit → configured triage owner → requester) inside the same
transaction that writes the row. If none of the three yields an owner the
transaction is rolled back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..config import Settings
from ..db.models import (
    AccountCoordination,
    Connector,
    IntroEvent,
    IntroOutcome,
    IntroRequest,
    Organization,
    Person,
    RequestTarget,
)
from ..domain.ownership import MANUAL_ASSIGNMENT, OwnershipError, resolve_live_owner
from ..domain.states import Outcome, RouteStatus, StateSource, TransitionError, WorkflowState, check_transition
from ..domain.workflow import (
    assign_next_action,
    age_days,
    days_since_activity,
    inactivity_bucket,
    is_overdue,
    is_potentially_stale,
)
from ..ingest.paths import build_candidate_paths
from ..ingest.requests import derive_unevidenced_state
from ..matching.accounts import canonical_key
from ..matching.normalize import norm_person, norm_ws, title_family
from .ranking import factor_payload, rank_paths
from .search import _split, account_summary, connector_summary, person_summary


class RequestNotFound(LookupError):
    pass


class ValidationProblem(ValueError):
    pass


@dataclass
class NewRequest:
    requester_name: str
    target_account_text: str
    raw_ask: str = ""
    target_person_name: str = ""
    target_title: str = ""
    deal_value_usd: int = 0
    urgency: str = ""
    request_id: str | None = None
    operational_owner_id: int | None = None
    #: Set only when live input genuinely evidences a real, named individual.
    #: Persona wording never creates a person, whatever this says.
    target_person_evidenced: bool = False


def create_request(
    session: Session,
    payload: NewRequest,
    settings: Settings,
    clock: Clock,
) -> IntroRequest:
    now = clock.now()
    if not norm_ws(payload.requester_name):
        raise ValidationProblem("requester_name is required")
    if not norm_ws(payload.target_account_text):
        raise ValidationProblem("target_account_text is required")

    requester = _live_person(session, payload.requester_name, is_internal=True, now=now)
    triage_owner = _triage_owner(session, settings)
    owner_id, owner_source = resolve_live_owner(
        explicit_owner_id=payload.operational_owner_id,
        triage_owner_id=triage_owner.id if triage_owner else None,
        requester_id=requester.id,
    )
    if session.get(Person, owner_id) is None:
        raise OwnershipError(f"operational owner {owner_id} does not exist")

    request_id = norm_ws(payload.request_id) or _next_request_id(session)
    if session.scalar(select(IntroRequest).where(IntroRequest.request_id == request_id)):
        raise ValidationProblem(f"request_id '{request_id}' already exists")

    org = _resolve_live_account(session, payload.target_account_text)
    request = IntroRequest(
        request_id=request_id,
        origin="live_intake",
        requester_id=requester.id,
        observed_owner_id=None,
        operational_owner_id=owner_id,
        operational_owner_source=owner_source,
        was_ownerless_at_ingest=False,
        had_recorded_handling=False,
        organization_id=org.id if org else None,
        raw_ask=norm_ws(payload.raw_ask),
        deal_value_usd=int(payload.deal_value_usd or 0),
        urgency=norm_ws(payload.urgency),
        workflow_state=WorkflowState.NEEDS_TRIAGE.value,
        state_source=StateSource.LIVE_INTAKE.value,
        requested_at=now,
        last_activity_at=now,
        operationalized_at=now,
    )
    session.add(request)
    session.flush()

    resolved_person = None
    if payload.target_person_evidenced and norm_ws(payload.target_person_name):
        resolved_person = _live_person(session, payload.target_person_name, is_internal=False, now=now)
    session.add(
        RequestTarget(
            request_id=request.id,
            raw_target_text=norm_ws(payload.raw_ask) or norm_ws(payload.target_person_name),
            raw_target_name=norm_ws(payload.target_person_name),
            raw_target_title=norm_ws(payload.target_title),
            normalized_title_family=title_family(payload.target_title),
            raw_account_text=norm_ws(payload.target_account_text),
            organization_id=org.id if org else None,
            resolved_person_id=resolved_person.id if resolved_person else None,
            resolution_status="resolved" if resolved_person else "unresolved",
            resolution_method="live_input_evidenced_individual" if resolved_person else "target_persona_only",
            resolution_confidence="medium" if resolved_person else "none",
            resolution_evidence=(
                "named individual supplied and confirmed at intake"
                if resolved_person
                else "request describes a target persona, not an identified individual"
            ),
        )
    )
    session.flush()

    path_counts = build_candidate_paths(session, {request.request_id: request})
    state = derive_unevidenced_state(
        was_ownerless=False,
        target_resolved=org is not None,
        target_ambiguous=org is not None and org.review_status == "needs_review",
        has_candidate_paths=path_counts.get(request.id, 0) > 0,
        declared_status="",
    )
    request.workflow_state = state.workflow_state.value
    request.route_status = state.route_status.value
    request.state_source = StateSource.LIVE_INTAKE.value
    request.state_confidence = state.confidence
    request.state_evidence = f"created at intake; {state.evidence}"
    action = assign_next_action(state.workflow_state, now, settings)
    request.next_action = action.action
    request.next_action_assigned_at = action.assigned_at
    request.next_action_due_at = action.due_at

    _log(session, request, "request_created", now, actor=requester.display_name,
         detail=f"intake; operational owner resolved via {owner_source}")
    session.flush()
    return request


def _next_request_id(session: Session) -> str:
    count = session.scalar(select(func.count()).select_from(IntroRequest)) or 0
    candidate = f"LIVE-{count + 1:04d}"
    while session.scalar(select(IntroRequest).where(IntroRequest.request_id == candidate)):
        count += 1
        candidate = f"LIVE-{count + 1:04d}"
    return candidate


def _triage_owner(session: Session, settings: Settings) -> Person | None:
    if not settings.triage_owner_name:
        return None
    return session.scalar(select(Person).where(Person.normalized_name == norm_person(settings.triage_owner_name)))


def _live_person(session: Session, name: str, is_internal: bool, now: datetime) -> Person:
    """Reuse a known person, or record a new one with live-input provenance."""
    key = norm_person(name)
    existing = session.scalars(select(Person).where(Person.normalized_name == key)).all()
    if len(existing) == 1:
        return existing[0]
    if existing:
        internal = [person for person in existing if person.is_internal == is_internal]
        if len(internal) == 1:
            return internal[0]
    person = Person(
        person_key=f"live::{key}::{now.timestamp():.0f}" if existing else f"live::{key}",
        display_name=norm_ws(name),
        normalized_name=key,
        identity_basis="live_input",
        is_internal=is_internal,
        source_type="live_input",
        match_tier="L1_live_input",
        match_method="supplied_at_intake",
        match_evidence="named individual supplied through the operational API",
        confidence="medium",
        competing_candidates="; ".join(sorted({person.display_name for person in existing})),
        review_status="needs_review" if existing else "resolved",
        raw_value=norm_ws(name),
    )
    session.add(person)
    session.flush()
    return person


def _resolve_live_account(session: Session, text: str) -> Organization | None:
    key = canonical_key(text)
    if not key:
        return None
    matches = session.scalars(select(Organization).where(Organization.canonical_key == key)).all()
    if len(matches) == 1:
        return matches[0]
    if matches:
        crm = [org for org in matches if org.is_crm_account]
        if len(crm) == 1:
            return crm[0]
        return None
    return None


def list_requests(
    session: Session,
    settings: Settings,
    clock: Clock,
    state: str | None = None,
    owner_id: int | None = None,
    account_id: int | None = None,
    origin: str | None = None,
    overdue: bool | None = None,
    stale: bool | None = None,
    ownerless_at_ingest: bool | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    stmt = select(IntroRequest)
    if state:
        stmt = stmt.where(IntroRequest.workflow_state == state)
    if owner_id is not None:
        stmt = stmt.where(IntroRequest.operational_owner_id == owner_id)
    if account_id is not None:
        stmt = stmt.where(IntroRequest.organization_id == account_id)
    if origin:
        stmt = stmt.where(IntroRequest.origin == origin)
    if ownerless_at_ingest is not None:
        stmt = stmt.where(IntroRequest.was_ownerless_at_ingest.is_(ownerless_at_ingest))
    if query:
        like = f"%{query.casefold()}%"
        stmt = stmt.where(or_(func.lower(IntroRequest.raw_ask).like(like), func.lower(IntroRequest.request_id).like(like)))

    rows = session.scalars(stmt.order_by(IntroRequest.request_id)).all()
    now = clock.now()
    items = [request_summary(request, now, settings) for request in rows]
    if overdue is not None:
        items = [item for item in items if item["is_overdue"] == overdue]
    if stale is not None:
        items = [item for item in items if item["potentially_stale"] == stale]
    return {"total": len(items), "limit": limit, "offset": offset, "items": items[offset: offset + limit]}


def request_summary(request: IntroRequest, now: datetime, settings: Settings) -> dict:
    stale = is_potentially_stale(request.workflow_state, request.last_activity_at, now, settings)
    since = days_since_activity(request.last_activity_at, now)
    return {
        "id": request.id,
        "request_id": request.request_id,
        "origin": request.origin,
        "requester": request.requester.display_name,
        "operational_owner": request.operational_owner.display_name,
        "operational_owner_id": request.operational_owner_id,
        "operational_owner_source": request.operational_owner_source,
        "observed_owner": request.observed_owner.display_name if request.observed_owner else None,
        "was_ownerless_at_ingest": request.was_ownerless_at_ingest,
        "account": request.organization.name if request.organization else (
            request.target.raw_account_text if request.target else ""
        ),
        "account_id": request.organization_id,
        "target": request.target.raw_target_name if request.target else "",
        "target_title": request.target.raw_target_title if request.target else "",
        "target_resolution_status": request.target.resolution_status if request.target else "",
        "workflow_state": request.workflow_state,
        "route_status": request.route_status,
        "outcome": request.outcome,
        "state_source": request.state_source,
        "state_confidence": request.state_confidence,
        "next_action": request.next_action,
        "next_action_due_at": request.next_action_due_at,
        "is_overdue": is_overdue(request.next_action_due_at, now),
        "deal_value_usd": request.deal_value_usd,
        "urgency": request.urgency,
        "requested_at": request.requested_at,
        "last_activity_at": request.last_activity_at,
        "age_days": _round(age_days(request.requested_at, now)),
        "days_since_activity": _round(since),
        "inactivity_bucket": inactivity_bucket(since),
        "potentially_stale": stale,
        "selected_connector": request.selected_connector.name if request.selected_connector else None,
    }


def get_request(session: Session, request_key: str) -> IntroRequest:
    request = session.scalar(select(IntroRequest).where(IntroRequest.request_id == request_key))
    if request is None and request_key.isdigit():
        request = session.get(IntroRequest, int(request_key))
    if request is None:
        raise RequestNotFound(request_key)
    return request


def request_detail(session: Session, request_key: str, settings: Settings, clock: Clock) -> dict:
    request = get_request(session, request_key)
    now = clock.now()
    events = session.scalars(
        select(IntroEvent).where(IntroEvent.request_id == request.id).order_by(IntroEvent.id)
    ).all()
    outcome = session.scalar(select(IntroOutcome).where(IntroOutcome.request_id == request.id))
    target = request.target
    return {
        **request_summary(request, now, settings),
        "raw_ask": request.raw_ask,
        "declared_status": request.declared_status,
        "declared_path_found_flag": request.declared_path_found_flag,
        "state_evidence": request.state_evidence,
        "operationalized_at": request.operationalized_at,
        "closed_at": request.closed_at,
        "closure_reason": request.closure_reason,
        "source_record_id": request.source_record_id,
        "target_detail": None if target is None else {
            "raw_target_text": target.raw_target_text,
            "raw_target_name": target.raw_target_name,
            "raw_target_title": target.raw_target_title,
            "normalized_title_family": target.normalized_title_family,
            "raw_account_text": target.raw_account_text,
            "account": account_summary(target.organization) if target.organization else None,
            "resolved_person": person_summary(target.resolved_person) if target.resolved_person else None,
            "resolution_status": target.resolution_status,
            "resolution_method": target.resolution_method,
            "resolution_confidence": target.resolution_confidence,
            "resolution_evidence": target.resolution_evidence,
            "candidate_matches": _split(target.candidate_matches),
        },
        "recorded_outcome": None if outcome is None else {
            "connector": outcome.connector_name,
            "asked_date": outcome.asked_date,
            "responded": outcome.responded,
            "response_date": outcome.response_date,
            "intro_sent": outcome.intro_sent,
            "intro_date": outcome.intro_date,
            "meeting_booked": outcome.meeting_booked,
            "opportunity_created": outcome.opportunity_created,
            "opportunity_value_usd": outcome.opportunity_value_usd,
        },
        "events": [
            {
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "recorded_at": event.recorded_at,
                "actor": event.actor,
                "detail": event.detail,
                "asserted_by": event.asserted_by,
                "is_state_evidence": event.is_state_evidence,
            }
            for event in events
        ],
    }


def request_paths(session: Session, request_key: str, settings: Settings, clock: Clock) -> dict:
    request = get_request(session, request_key)
    return candidate_path_payload(session, request, settings, clock.now())


def candidate_path_payload(session: Session, request: IntroRequest, settings: Settings, now: datetime) -> dict:
    """Candidate paths in investigation order.

    The ordering is deterministic and every position is explained by the factor
    sentences on the path; the composite weight behind it is never serialised,
    because it would read as a precision these heuristics do not have.
    """
    ranked = rank_paths(session, request, settings, now)
    paths = [entry.path for entry in ranked]
    return {
        "request_id": request.request_id,
        "disclaimer": (
            "Candidate paths are evidence about where to investigate. None of them means an introduction is "
            "available; a human reviews the route before any connector is asked."
        ),
        "ordering": (
            "Ordered by evidence-based investigation priority: which lead is worth checking first, not how strong "
            "a relationship is or how likely an introduction is to happen."
        ),
        "counts": {
            "total": len(paths),
            "historically_observable": sum(1 for p in paths if p.observability == "historically_observable"),
            "snapshot_only": sum(1 for p in paths if p.observability == "snapshot_only"),
            "post_dates_request": sum(1 for p in paths if p.observability == "post_dates_request"),
        },
        "paths": [
            {
                "id": entry.path.id,
                "rank": entry.rank,
                "recommended": entry.recommended,
                "recommendation_label": "Recommended to investigate first" if entry.recommended else "",
                "factors": [factor_payload(factor) for factor in entry.factors],
                "connector": connector_summary(entry.path.connector),
                "hop_type": entry.path.hop_type,
                "observability": entry.path.observability,
                "connector_reachable": entry.path.connector_reachable,
                "same_title_family": entry.path.same_title_family,
                "relationship_date": entry.path.relationship_date,
                "confidence": entry.path.confidence,
                "limitations": entry.path.limitations,
                "evidence": entry.path.evidence,
                "source_file": entry.path.source_file,
            }
            for entry in ranked
        ],
    }


def related_requests(session: Session, request_key: str, settings: Settings, clock: Clock) -> dict:
    request = get_request(session, request_key)
    rows = session.scalars(
        select(AccountCoordination).where(
            or_(AccountCoordination.request_id_a == request.id, AccountCoordination.request_id_b == request.id)
        )
    ).all()
    now = clock.now()
    related = []
    for row in rows:
        other_id = row.request_id_b if row.request_id_a == request.id else row.request_id_a
        other = session.get(IntroRequest, other_id)
        if other is None:  # pragma: no cover
            continue
        related.append(
            {
                "relation_type": row.relation_type,
                "detail": row.detail,
                "days_apart": row.days_apart,
                "within_window": row.within_window,
                "same_requester": row.same_requester,
                "request": request_summary(other, now, settings),
            }
        )
    order = {"explicit_reask": 0, "same_account_same_target_person": 1, "same_account_same_title_family": 2}
    related.sort(key=lambda item: (order.get(item["relation_type"], 3), item["request"]["request_id"]))
    return {
        "request_id": request.request_id,
        "note": (
            "Different targets at the same account are parallel activity to coordinate. Only an explicit re-ask or "
            "the same named target is treated as the same ask, and nothing here blocks or merges a request."
        ),
        "related": related,
    }


def transition(
    session: Session,
    request_key: str,
    to_state: str,
    settings: Settings,
    clock: Clock,
    actor: str = "operator",
    note: str = "",
    route_status: str | None = None,
    outcome: str | None = None,
    connector_id: int | None = None,
    closure_reason: str = "",
) -> IntroRequest:
    request = get_request(session, request_key)
    try:
        current = WorkflowState(request.workflow_state)
        requested = WorkflowState(to_state)
    except ValueError as exc:
        raise ValidationProblem(str(exc)) from exc
    check_transition(current, requested)
    if requested is WorkflowState.CLOSED and not norm_ws(closure_reason):
        raise ValidationProblem("closing a request requires an explicit closure_reason")
    if route_status is not None:
        try:
            request.route_status = RouteStatus(route_status).value
        except ValueError as exc:
            raise ValidationProblem(str(exc)) from exc
    if outcome is not None:
        try:
            request.outcome = Outcome(outcome).value
        except ValueError as exc:
            raise ValidationProblem(str(exc)) from exc
    if connector_id is not None:
        if session.get(Connector, connector_id) is None:
            raise ValidationProblem(f"connector {connector_id} does not exist")
        request.selected_connector_id = connector_id

    now = clock.now()
    request.workflow_state = requested.value
    request.state_source = StateSource.OPERATOR_TRANSITION.value
    request.state_confidence = "high"
    request.state_evidence = f"{actor}: {norm_ws(note) or 'no note supplied'}"
    request.last_activity_at = now
    if requested is WorkflowState.CLOSED:
        request.closed_at = now
        request.closure_reason = norm_ws(closure_reason)
    action = assign_next_action(requested, now, settings)
    request.next_action = action.action
    request.next_action_assigned_at = action.assigned_at
    request.next_action_due_at = action.due_at
    _log(session, request, f"transition:{current.value}->{requested.value}", now, actor=actor, detail=norm_ws(note))
    session.flush()
    return request


def set_owner(
    session: Session,
    request_key: str,
    owner_id: int,
    clock: Clock,
    actor: str = "operator",
    note: str = "",
) -> IntroRequest:
    request = get_request(session, request_key)
    owner = session.get(Person, owner_id)
    if owner is None:
        raise ValidationProblem(f"person {owner_id} does not exist")
    now = clock.now()
    previous = request.operational_owner.display_name
    request.operational_owner_id = owner.id
    request.operational_owner_source = MANUAL_ASSIGNMENT
    request.last_activity_at = now
    _log(
        session,
        request,
        "owner_changed",
        now,
        actor=actor,
        detail=f"{previous} -> {owner.display_name}. {norm_ws(note)}".strip(),
    )
    session.flush()
    return request


def _log(session: Session, request: IntroRequest, event_type: str, now: datetime, actor: str, detail: str) -> None:
    session.add(
        IntroEvent(
            request_id=request.id,
            event_type=event_type,
            occurred_at=now,
            recorded_at=now,
            actor=actor,
            detail=detail,
            asserted_by="operator",
            confidence="high",
            is_state_evidence=True,
        )
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


__all__ = [
    "NewRequest",
    "OwnershipError",
    "RequestNotFound",
    "TransitionError",
    "ValidationProblem",
    "create_request",
    "get_request",
    "list_requests",
    "related_requests",
    "request_detail",
    "request_paths",
    "request_summary",
    "set_owner",
    "transition",
]
