"""The request spine: 200 asks, their targets, their evidence and their state.

Three things this module refuses to do:

* invent a ``Person`` from target wording — a persona goes on
  :class:`~halyard.db.models.RequestTarget` and resolves to nobody until real
  evidence says otherwise;
* treat the connector who was asked as the owner of the request;
* let a request that has no observable path fall out of the workflow.

State is derived from evidence in a fixed precedence — recorded outcome, then an
explicit statement, then the declared status field — and inactivity is never
part of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import Settings
from ..domain.ownership import resolve_historical_owner
from ..domain.states import Outcome, RouteStatus, StateSource, WorkflowState
from ..domain.workflow import (
    CORROBORATED_PATH,
    INGEST_ASSIGNED,
    NO_ROUTE_SIGNAL,
    UNVERIFIED_SUGGESTED_ROUTE,
    assign_next_action,
    validate_suggested_route_action,
)
from ..db.models import IntroEvent, IntroOutcome, IntroRequest, Person, RequestTarget
from ..matching.normalize import (
    extract_domains,
    norm_person,
    norm_ws,
    parse_date,
    parse_timestamp,
    title_family,
)
from ..matching.people import T1, T3, T4
from ..matching.slack import (
    EXPLICIT_STATE_INTENTS,
    classify,
    looks_like_ask,
    referred_person,
    suggested_route_person,
)
from .entities import EntityIndex, person_for_name, resolve_account, observed_connector
from .raw import payload

RESOLVED_ACCOUNT_TIERS = {"A_exact_crm_id", "A_exact_unique_domain", "B_probable_name_exact"}
RESOLVED_PERSON_TIERS = {T1, T3, T4}

#: Phrases in which somebody explicitly takes accountability for a request.
#:
#: Deliberately narrower than the ``volunteer_offer`` intent: "happy to reach
#: out" offers a *route* and makes the speaker a connector, whereas "leave it
#: with me" takes the *request*. Only the latter is ownership evidence, and
#: ``connector_asked`` never is.
OWNERSHIP_PHRASES = ("leave it with me", "i'll take this one")


@dataclass
class DerivedState:
    workflow_state: WorkflowState
    route_status: RouteStatus
    outcome: Outcome
    source: StateSource
    confidence: str
    evidence: str
    closure_reason: str = ""


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _as_datetime(value) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def derive_state_from_evidence(outcome: dict | None, slack_intents: list[str]) -> DerivedState | None:
    """State from recorded events, then from explicit statements. ``None`` if neither."""
    if outcome:
        if outcome["opportunity_created"] == "Y":
            return DerivedState(
                WorkflowState.COMPLETED, RouteStatus.CONNECTOR_CONFIRMED, Outcome.OPPORTUNITY_CREATED,
                StateSource.OBSERVED_EVENT, "high", "intro_outcomes row: opportunity_created=Y",
            )
        if outcome["meeting_booked"] == "Y":
            return DerivedState(
                WorkflowState.COMPLETED, RouteStatus.CONNECTOR_CONFIRMED, Outcome.MEETING_BOOKED,
                StateSource.OBSERVED_EVENT, "high", "intro_outcomes row: meeting_booked=Y",
            )
        if outcome["intro_sent"] == "Y":
            return DerivedState(
                WorkflowState.INTRO_SENT, RouteStatus.CONNECTOR_CONFIRMED, Outcome.INTRO_SENT,
                StateSource.OBSERVED_EVENT, "high", "intro_outcomes row: intro_sent=Y",
            )
        if outcome["responded"] == "Y":
            return DerivedState(
                WorkflowState.AWAITING_CONNECTOR, RouteStatus.ROUTE_SELECTED, Outcome.UNKNOWN,
                StateSource.OBSERVED_EVENT, "medium",
                "intro_outcomes row: connector responded but no intro is recorded",
            )
        return DerivedState(
            WorkflowState.AWAITING_CONNECTOR, RouteStatus.ROUTE_SELECTED, Outcome.UNKNOWN,
            StateSource.OBSERVED_EVENT, "medium", "intro_outcomes row: connector asked, no response recorded",
        )

    explicit = [intent for intent in slack_intents if intent in EXPLICIT_STATE_INTENTS]
    if explicit:
        intent = explicit[0]
        if intent == "intro_confirmed":
            return DerivedState(
                WorkflowState.INTRO_SENT, RouteStatus.CONNECTOR_CONFIRMED, Outcome.INTRO_SENT,
                StateSource.EXPLICIT_STATEMENT, "medium", "Slack message states the introduction was made",
            )
        if intent == "declined":
            return DerivedState(
                WorkflowState.BLOCKED, RouteStatus.ROUTE_FAILED, Outcome.DECLINED,
                StateSource.EXPLICIT_STATEMENT, "medium",
                "Slack message declines the ask; the request stays active and needs another route",
            )
        return DerivedState(
            WorkflowState.CLOSED, RouteStatus.NONE, Outcome.NO_INTRO,
            StateSource.EXPLICIT_STATEMENT, "medium", "Slack message explicitly closes the request",
            closure_reason="explicit_closure_stated_in_slack",
        )

    if "volunteer_offer" in slack_intents:
        return DerivedState(
            WorkflowState.PATH_REVIEW, RouteStatus.CANDIDATES_IDENTIFIED, Outcome.UNKNOWN,
            StateSource.EXPLICIT_STATEMENT, "medium",
            "someone offered a route in Slack; the offer needs review before anyone is treated as confirmed",
        )
    return None


def derive_unevidenced_state(
    was_ownerless: bool,
    target_resolved: bool,
    target_ambiguous: bool,
    has_candidate_paths: bool,
    declared_status: str,
    has_suggested_route: bool = False,
) -> DerivedState:
    """State for a request with no recorded event and no explicit statement.

    Every branch lands on an active state with work attached. Nothing here can
    produce silence, and "no observable path" keeps the request in the queue.
    """
    source = StateSource.DECLARED_ONLY if norm_ws(declared_status) else StateSource.NO_EVIDENCE
    declared_note = (
        f"declared status '{norm_ws(declared_status)}' with no corroborating event evidence"
        if norm_ws(declared_status)
        else "no outcome row, no explicit statement and no declared status"
    )
    if target_ambiguous or not target_resolved:
        follow_on = "the target account could not be resolved from the supplied data"
    elif has_candidate_paths:
        follow_on = "candidate paths exist and need review"
    elif has_suggested_route:
        follow_on = "a route was suggested by a person and needs validating"
    else:
        follow_on = "no path to the target is observable in the supplied data"

    if was_ownerless:
        return DerivedState(
            WorkflowState.NEEDS_TRIAGE, RouteStatus.CANDIDATES_IDENTIFIED if has_candidate_paths else RouteStatus.NONE,
            Outcome.UNKNOWN, source, "none",
            f"{declared_note}; nobody is evidenced as having owned it, so it needs triage first ({follow_on})",
        )
    if target_ambiguous or not target_resolved:
        return DerivedState(
            WorkflowState.NEEDS_ENTITY_REVIEW, RouteStatus.NONE, Outcome.UNKNOWN, source, "none",
            f"{declared_note}; the target account could not be resolved from the supplied data",
        )
    if has_candidate_paths:
        return DerivedState(
            WorkflowState.PATH_REVIEW, RouteStatus.CANDIDATES_IDENTIFIED, Outcome.UNKNOWN, source, "low",
            f"{declared_note}; candidate paths exist and need review",
        )
    if has_suggested_route:
        #: Somebody named a person who may hold a route. That is real evidence
        #: about where to look, so the request is not pathless — but it is not a
        #: candidate path either until a human validates it.
        return DerivedState(
            WorkflowState.PATH_REVIEW, RouteStatus.NONE, Outcome.UNKNOWN, source, "low",
            f"{declared_note}; a route was suggested in the source thread and the supplied network does not "
            "corroborate it",
        )
    return DerivedState(
        WorkflowState.NO_OBSERVABLE_PATH, RouteStatus.NONE, Outcome.UNKNOWN, source, "low",
        f"{declared_note}; no path to the target is observable in the supplied data",
    )


def build_requests(
    session: Session,
    staged: dict,
    index: EntityIndex,
    settings: Settings,
) -> dict[str, IntroRequest]:
    outcome_rows = {}
    for record in staged["intro_outcomes.csv"]:
        row = payload(record)
        outcome_rows.setdefault(row["request_id"], []).append((record.id, row))

    threads: dict[str, list[dict]] = {}
    thread_record: dict[str, int] = {}
    for record in staged["slack_threads.jsonl"]:
        if record.parse_status != "ok":
            continue
        thread = json.loads(record.raw_json)
        threads[thread["request_id"]] = thread["messages"]
        thread_record[thread["request_id"]] = record.id

    requests: dict[str, IntroRequest] = {}
    operationalized_at = settings.operationalization_at

    for record in staged["intro_requests.csv"]:
        row = payload(record)
        request_id = row["request_id"]
        messages = threads.get(request_id, [])
        intents = [classify(message["text"]) for message in messages]

        requester = person_for_name(
            session, index, row["requested_by"], is_internal=True,
            source_record_id=record.id, subject_context="intro_requests.requested_by",
        )
        assert requester is not None
        observed_owner = _observed_owner(session, index, messages, record.id)
        decision = resolve_historical_owner(observed_owner.id if observed_owner else None, requester.id)

        thread_text = " ".join(message["text"] for message in messages)
        org, account_match = resolve_account(
            session,
            index,
            row["target_company_raw"],
            domain_hints=extract_domains(f"{row.get('raw_ask', '')} {thread_text}"),
            source_record_id=record.id,
            subject_context="intro_requests.target_company_raw",
        )

        outcome_payloads = outcome_rows.get(request_id, [])
        outcome = _normalize_outcome(outcome_payloads[0][1]) if outcome_payloads else None
        request_date = parse_date(row.get("request_date"))

        request = IntroRequest(
            request_id=request_id,
            origin="historical_corpus",
            requester_id=requester.id,
            requester_role=norm_ws(row.get("requester_role")),
            observed_owner_id=decision.observed_owner_id,
            observed_owner_evidence=observed_owner.match_evidence if observed_owner else "",
            operational_owner_id=decision.owner_id,
            operational_owner_source=decision.source,
            was_ownerless_at_ingest=decision.was_ownerless_at_ingest,
            had_recorded_handling=bool(outcome and outcome["connector_asked"]),
            organization_id=org.id if org else None,
            raw_ask=norm_ws(row.get("raw_ask")),
            deal_value_usd=int(row["deal_value_usd"]) if str(row.get("deal_value_usd", "")).isdigit() else 0,
            urgency=norm_ws(row.get("urgency")),
            declared_status=norm_ws(row.get("status")),
            declared_path_found_flag=norm_ws(row.get("path_found_flag")),
            workflow_state=WorkflowState.NEEDS_TRIAGE.value,
            requested_at=_as_datetime(request_date),
            operationalized_at=operationalized_at,
            source_record_id=record.id,
        )
        request.suggested_route_person, request.suggested_route_evidence = _suggested_route(messages)
        session.add(request)
        session.flush()
        requests[request_id] = request

        _build_target(session, index, request, row, record.id)
        activity = [_as_datetime(request_date)]
        activity += _build_slack_events(session, request, messages, thread_record.get(request_id))
        activity += _build_outcome(session, index, request, outcome_payloads)

        request.last_activity_at = max((ts for ts in activity if ts), default=None)

        state = derive_state_from_evidence(outcome, intents)
        if state is not None:
            _apply_state(request, state, operationalized_at, settings)
        # Requests with no event evidence are finalized after path discovery.

    session.flush()
    return requests


def _suggested_route(messages: list[dict]) -> tuple[str, str]:
    """Who a thread says may hold a route, and the sentence that says so.

    An offer names its speaker ("happy to reach out"); a referral names somebody
    else ("adding Dana who might know"). Either way this is a person to ask, not
    a path: nothing here is promoted into a candidate path.
    """
    for message in messages:
        text = norm_ws(message["text"])
        if classify(text) == "volunteer_offer":
            return norm_ws(message["user"]), f"Slack: '{text}'"
        named = referred_person(text) or suggested_route_person(text)
        if named:
            return norm_ws(named), f"Slack: '{text}'"
    return "", ""


def _observed_owner(session: Session, index: EntityIndex, messages: list[dict], record_id: int) -> Person | None:
    """The only ownership the corpus actually evidences: somebody saying they took it."""
    for message in messages:
        lowered = message["text"].casefold()
        if any(phrase in lowered for phrase in OWNERSHIP_PHRASES):
            person = person_for_name(
                session, index, message["user"], is_internal=True,
                source_record_id=record_id, subject_context="slack_ownership_statement",
            )
            if person is not None:
                person.match_evidence = f"Slack: '{norm_ws(message['text'])}'"
                return person
    return None


def _normalize_outcome(row: dict) -> dict:
    return {
        "connector_asked": norm_ws(row.get("connector_asked")),
        "asked_date": parse_date(row.get("asked_date")),
        "responded": norm_ws(row.get("responded")),
        "response_date": parse_date(row.get("response_date")),
        "intro_sent": norm_ws(row.get("intro_sent")),
        "intro_date": parse_date(row.get("intro_date")),
        "meeting_booked": norm_ws(row.get("meeting_booked")),
        "opportunity_created": norm_ws(row.get("opportunity_created")),
        "opportunity_value_usd": norm_ws(row.get("opportunity_value_usd")),
    }


def _build_target(session: Session, index: EntityIndex, request: IntroRequest, row: dict, record_id: int) -> None:
    """Record what the request is trying to reach, resolved only as far as evidence allows."""
    assert index.person_resolver is not None
    name = norm_ws(row.get("target_person_raw"))
    match = index.person_resolver.resolve(name, row.get("target_company_raw"), row.get("target_title_raw"))
    resolved = index.persons_by_key.get(match.person_key) if match.tier in RESOLVED_PERSON_TIERS else None
    target_org = request.organization_id
    persona_only = not name
    method = "target_persona_only" if persona_only else match.method
    evidence = (
        "the ask describes a role at an account, not an identified individual"
        if persona_only
        else match.evidence
    )
    session.add(
        RequestTarget(
            request_id=request.id,
            raw_target_text=norm_ws(row.get("raw_ask")),
            raw_target_name=name,
            raw_target_title=norm_ws(row.get("target_title_raw")),
            normalized_title_family=title_family(row.get("target_title_raw")),
            raw_account_text=norm_ws(row.get("target_company_raw")),
            organization_id=target_org,
            resolved_person_id=resolved.id if resolved else None,
            resolution_status=(
                "resolved" if resolved else ("ambiguous" if match.tier.startswith(("T2", "T5")) else "unresolved")
            ),
            resolution_method=method,
            resolution_confidence="high" if match.tier == T1 else ("medium" if resolved else "none"),
            resolution_evidence=evidence,
            candidate_matches="; ".join(match.candidates),
            source_record_id=record_id,
        )
    )


def _build_slack_events(
    session: Session, request: IntroRequest, messages: list[dict], record_id: int | None
) -> list[datetime | None]:
    stamps: list[datetime | None] = []
    for index_, message in enumerate(messages):
        intent = classify(message["text"])
        occurred = _utc(parse_timestamp(message["ts"]))
        stamps.append(occurred)
        session.add(
            IntroEvent(
                request_id=request.id,
                event_type=f"slack:{intent}",
                occurred_at=occurred,
                recorded_at=request.operationalized_at,
                actor=norm_ws(message["user"]),
                detail=norm_ws(message["text"]),
                asserted_by="slack_threads.jsonl",
                confidence="medium" if intent != "unclassified" else "none",
                is_state_evidence=intent in EXPLICIT_STATE_INTENTS,
                source_record_id=record_id,
            )
        )
        if index_ > 0 and looks_like_ask(message["text"]):
            session.add(
                IntroEvent(
                    request_id=request.id,
                    event_type="derived:additional_ask_like_message",
                    occurred_at=occurred,
                    recorded_at=request.operationalized_at,
                    actor=norm_ws(message["user"]),
                    detail=norm_ws(message["text"]),
                    asserted_by="slack_threads.jsonl",
                    confidence="low",
                    is_state_evidence=False,
                    source_record_id=record_id,
                )
            )
        referred = referred_person(message["text"])
        if referred:
            session.add(
                IntroEvent(
                    request_id=request.id,
                    event_type="derived:referral_suggestion",
                    occurred_at=occurred,
                    recorded_at=request.operationalized_at,
                    actor=norm_ws(message["user"]),
                    detail=f"suggested {referred}",
                    asserted_by="slack_threads.jsonl",
                    confidence="low",
                    is_state_evidence=False,
                    source_record_id=record_id,
                )
            )
    return stamps


def _build_outcome(
    session: Session, index: EntityIndex, request: IntroRequest, outcome_payloads: list[tuple[int, dict]]
) -> list[datetime | None]:
    stamps: list[datetime | None] = []
    for position, (record_id, raw) in enumerate(outcome_payloads):
        row = _normalize_outcome(raw)
        connector = observed_connector(session, index, row["connector_asked"], record_id, "intro_outcomes.csv")
        if position == 0:
            session.add(
                IntroOutcome(
                    request_id=request.id,
                    connector_id=connector.id if connector else None,
                    connector_name=row["connector_asked"],
                    asked_date=row["asked_date"],
                    responded=row["responded"],
                    response_date=row["response_date"],
                    intro_sent=row["intro_sent"],
                    intro_date=row["intro_date"],
                    meeting_booked=row["meeting_booked"],
                    opportunity_created=row["opportunity_created"],
                    opportunity_value_usd=row["opportunity_value_usd"],
                    source_record_id=record_id,
                )
            )
            if connector is not None:
                request.selected_connector_id = connector.id
        milestones = [
            ("connector_asked", row["asked_date"], row["connector_asked"]),
            ("connector_responded", row["response_date"], row["responded"]),
            ("intro_sent", row["intro_date"], row["intro_sent"]),
        ]
        for event_type, occurred, value in milestones:
            if not value or value == "N":
                continue
            stamp = _as_datetime(occurred)
            stamps.append(stamp)
            session.add(
                IntroEvent(
                    request_id=request.id,
                    event_type=event_type,
                    occurred_at=stamp,
                    recorded_at=request.operationalized_at,
                    actor=row["connector_asked"],
                    detail=f"{event_type}={value}",
                    asserted_by="intro_outcomes.csv",
                    confidence="high",
                    is_state_evidence=True,
                    source_record_id=record_id,
                )
            )
        for flag, event_type in (("meeting_booked", "meeting_booked"), ("opportunity_created", "opportunity_created")):
            if row[flag] == "Y":
                session.add(
                    IntroEvent(
                        request_id=request.id,
                        event_type=event_type,
                        occurred_at=None,
                        recorded_at=request.operationalized_at,
                        actor=row["connector_asked"],
                        detail=f"{flag}=Y (no date recorded in the corpus)",
                        asserted_by="intro_outcomes.csv",
                        confidence="high",
                        is_state_evidence=True,
                        source_record_id=record_id,
                    )
                )
    return stamps


def _apply_state(
    request: IntroRequest,
    state: DerivedState,
    assigned_at: datetime,
    settings: Settings,
    next_action_source: str = INGEST_ASSIGNED,
) -> None:
    request.workflow_state = state.workflow_state.value
    request.route_status = state.route_status.value
    request.outcome = state.outcome.value
    request.state_source = state.source.value
    request.state_confidence = state.confidence
    request.state_evidence = state.evidence
    if state.closure_reason:
        request.closure_reason = state.closure_reason
        request.closed_at = request.last_activity_at or assigned_at
    action = assign_next_action(state.workflow_state, assigned_at, settings)
    request.next_action = action.action
    request.next_action_assigned_at = action.assigned_at
    request.next_action_due_at = action.due_at
    request.next_action_source = next_action_source


def finalize_route_signals(session: Session, requests: dict[str, IntroRequest], path_counts: dict[int, int]) -> None:
    """Record what kind of route evidence each request actually has.

    Three distinct facts, never collapsed: the network corroborates a path, a
    person suggested one and the network does not, or nothing suggests one at
    all. Only the first is a candidate path.
    """
    for request in requests.values():
        if path_counts.get(request.id, 0) > 0:
            request.route_signal = CORROBORATED_PATH
        elif request.suggested_route_person:
            request.route_signal = UNVERIFIED_SUGGESTED_ROUTE
            if request.workflow_state == WorkflowState.PATH_REVIEW.value:
                #: Nothing was identified; somebody said they might be able to.
                request.route_status = RouteStatus.NONE.value
                request.next_action = validate_suggested_route_action(request.suggested_route_person)
        else:
            request.route_signal = NO_ROUTE_SIGNAL
    session.flush()


def finalize_unevidenced_states(
    session: Session,
    requests: dict[str, IntroRequest],
    path_counts: dict[int, int],
    settings: Settings,
) -> None:
    """Second pass, once candidate paths exist, for requests with no event evidence."""
    for request in requests.values():
        if request.state_source in {StateSource.OBSERVED_EVENT.value, StateSource.EXPLICIT_STATEMENT.value}:
            continue
        target = request.target
        state = derive_unevidenced_state(
            was_ownerless=request.was_ownerless_at_ingest,
            target_resolved=request.organization_id is not None,
            target_ambiguous=bool(target and target.resolution_status == "ambiguous"),
            has_candidate_paths=path_counts.get(request.id, 0) > 0,
            declared_status=request.declared_status,
            has_suggested_route=bool(request.suggested_route_person),
        )
        _apply_state(request, state, settings.operationalization_at, settings)
    session.flush()


def connector_person_names(index: EntityIndex) -> set[str]:
    return {norm_person(connector.name) for connector in index.connectors_by_norm_name.values()}
