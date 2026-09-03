"""Human decisions on a live request: entity confirmation and route review.

Both operations update the *same* request created at intake. Neither creates a
new one, and neither can leave it ownerless or without a next action.

Confirming a route is the only way a connector becomes selected. Path discovery
proposes; a person decides. Rejecting every candidate does not delete the
request — it moves to ``NO_OBSERVABLE_PATH``, which is an active state with an
owner and an escalation action.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..config import Settings
from ..db.models import IntroCandidatePath, IntroRequest, Organization, Person, RequestTarget
from ..domain.states import ALLOWED_TRANSITIONS, RouteStatus, StateSource, WorkflowState, check_transition
from ..domain.workflow import assign_next_action
from ..ingest.coordination import link_request
from ..ingest.paths import build_candidate_paths
from ..intake.parse import parse_ask
from ..matching.normalize import norm_ws, title_family
from .intake import intake_payload
from .requests import ValidationProblem, get_request, log_event

SELECTED = "selected"
REJECTED = "rejected"
UNREVIEWED = "unreviewed"


def _move(
    session: Session,
    request: IntroRequest,
    to_state: WorkflowState,
    settings: Settings,
    now: datetime,
    actor: str,
    evidence: str,
) -> None:
    """Advance the workflow, going through PATH_REVIEW when the machine requires it."""
    current = WorkflowState(request.workflow_state)
    if current is not to_state:
        if to_state not in _reachable(current):
            if WorkflowState.PATH_REVIEW in _reachable(current) and to_state in _reachable(WorkflowState.PATH_REVIEW):
                _apply_state(session, request, WorkflowState.PATH_REVIEW, settings, now, actor, evidence)
            current = WorkflowState(request.workflow_state)
        check_transition(current, to_state)
        _apply_state(session, request, to_state, settings, now, actor, evidence)
    else:
        action = assign_next_action(to_state, now, settings)
        request.next_action = action.action
        request.next_action_assigned_at = action.assigned_at
        request.next_action_due_at = action.due_at
        request.last_activity_at = now


def _reachable(state: WorkflowState) -> set[WorkflowState]:
    return ALLOWED_TRANSITIONS[state]


def _apply_state(
    session: Session,
    request: IntroRequest,
    to_state: WorkflowState,
    settings: Settings,
    now: datetime,
    actor: str,
    evidence: str,
) -> None:
    previous = request.workflow_state
    request.workflow_state = to_state.value
    request.state_source = StateSource.OPERATOR_TRANSITION.value
    request.state_confidence = "high"
    request.state_evidence = evidence
    request.last_activity_at = now
    action = assign_next_action(to_state, now, settings)
    request.next_action = action.action
    request.next_action_assigned_at = action.assigned_at
    request.next_action_due_at = action.due_at
    log_event(session, request, f"transition:{previous}->{to_state.value}", now, actor=actor, detail=evidence)
    session.flush()


def confirm_target(
    session: Session,
    request_key: str,
    settings: Settings,
    clock: Clock,
    account_id: int | None = None,
    person_id: int | None = None,
    target_title: str = "",
    actor: str = "operator",
    note: str = "",
) -> dict:
    """Record the human's answer to an ambiguous or unresolved target.

    Re-resolves paths and account coordination against the confirmed entities;
    the request keeps its id, its owner and its history.
    """
    request = get_request(session, request_key)
    now = clock.now()
    target: RequestTarget | None = request.target
    if target is None:
        raise ValidationProblem(f"request '{request_key}' has no target to confirm")

    parts: list[str] = []
    if account_id is not None:
        account = session.get(Organization, account_id)
        if account is None:
            raise ValidationProblem(f"account {account_id} does not exist")
        request.organization_id = account.id
        target.organization_id = account.id
        target.raw_account_text = target.raw_account_text or account.name
        parts.append(f"account confirmed as {account.name}")
    if person_id is not None:
        person = session.get(Person, person_id)
        if person is None:
            raise ValidationProblem(f"person {person_id} does not exist")
        target.resolved_person_id = person.id
        target.raw_target_name = target.raw_target_name or person.display_name
        parts.append(f"target person confirmed as {person.display_name}")
    if norm_ws(target_title):
        target.raw_target_title = norm_ws(target_title)
        target.normalized_title_family = title_family(target_title)
        parts.append(f"target role recorded as {norm_ws(target_title)}")
    if not parts:
        raise ValidationProblem("nothing to confirm: supply an account, a person or a title")

    target.resolution_status = "resolved" if target.organization_id or target.resolved_person_id else "unresolved"
    target.resolution_method = "human_confirmation"
    target.resolution_confidence = "high"
    target.resolution_evidence = f"{actor}: {'; '.join(parts)}. {norm_ws(note)}".strip()
    session.flush()

    session.query(IntroCandidatePath).filter(
        IntroCandidatePath.request_id == request.id,
        IntroCandidatePath.review_status == UNREVIEWED,
    ).delete(synchronize_session=False)
    session.flush()
    counts = build_candidate_paths(session, {request.request_id: request})
    link_request(session, request, settings)

    has_paths = counts.get(request.id, 0) > 0 or bool(
        session.scalars(
            select(IntroCandidatePath).where(
                IntroCandidatePath.request_id == request.id,
                IntroCandidatePath.review_status != REJECTED,
            )
        ).first()
    )
    log_event(session, request, "target_confirmed", now, actor=actor, detail="; ".join(parts))
    _move(
        session,
        request,
        WorkflowState.PATH_REVIEW if has_paths else WorkflowState.NO_OBSERVABLE_PATH,
        settings,
        now,
        actor,
        f"{actor} confirmed the target: {'; '.join(parts)}",
    )
    session.flush()
    return _payload(session, request, settings, now)


def review_route(
    session: Session,
    request_key: str,
    path_id: int,
    decision: str,
    settings: Settings,
    clock: Clock,
    actor: str = "operator",
    note: str = "",
) -> dict:
    """Confirm or reject one candidate path. A rejection is evidence, not a delete."""
    request = get_request(session, request_key)
    now = clock.now()
    verdict = decision.strip().casefold()
    if verdict not in {"confirm", "reject"}:
        raise ValidationProblem("decision must be 'confirm' or 'reject'")

    path = session.get(IntroCandidatePath, path_id)
    if path is None or path.request_id != request.id:
        raise ValidationProblem(f"path {path_id} does not belong to request '{request.request_id}'")

    path.review_note = norm_ws(note)
    path.reviewed_at = now
    path.reviewed_by = actor

    if verdict == "confirm":
        for other in session.scalars(
            select(IntroCandidatePath).where(
                IntroCandidatePath.request_id == request.id,
                IntroCandidatePath.review_status == SELECTED,
                IntroCandidatePath.id != path.id,
            )
        ).all():
            other.review_status = UNREVIEWED
        path.review_status = SELECTED
        request.selected_connector_id = path.connector_id
        request.route_confirmed_at = now
        request.route_status = RouteStatus.CONNECTOR_CONFIRMED.value
        detail = f"route confirmed via {path.connector.name}: {path.evidence}"
        log_event(session, request, "route_confirmed", now, actor=actor, detail=f"{detail}. {norm_ws(note)}".strip())
        _move(session, request, WorkflowState.AWAITING_CONNECTOR, settings, now, actor, detail)
        session.flush()
        return _payload(session, request, settings, now)

    path.review_status = REJECTED
    remaining = session.scalars(
        select(IntroCandidatePath).where(
            IntroCandidatePath.request_id == request.id,
            IntroCandidatePath.review_status != REJECTED,
        )
    ).all()
    if path.connector_id == request.selected_connector_id:
        request.selected_connector_id = None
        request.route_confirmed_at = None
    detail = f"route via {path.connector.name} rejected: {norm_ws(note) or 'no reason given'}"
    log_event(session, request, "route_rejected", now, actor=actor, detail=detail)
    if remaining:
        request.route_status = RouteStatus.CANDIDATES_IDENTIFIED.value
        _move(session, request, WorkflowState.PATH_REVIEW, settings, now, actor, detail)
    else:
        request.route_status = RouteStatus.ROUTE_FAILED.value
        _move(
            session,
            request,
            WorkflowState.NO_OBSERVABLE_PATH,
            settings,
            now,
            actor,
            f"{detail}; every candidate path has now been rejected",
        )
    session.flush()
    return _payload(session, request, settings, now)


def _payload(session: Session, request: IntroRequest, settings: Settings, now: datetime) -> dict:
    return intake_payload(session, request, parse_ask(request.raw_ask), settings, now)


__all__ = ["REJECTED", "SELECTED", "UNREVIEWED", "confirm_target", "review_route"]
