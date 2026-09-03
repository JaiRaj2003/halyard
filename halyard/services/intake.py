"""Atomic live intake: persist and own the ask, then work out what it means.

The order here is the product guarantee. A free-text ask becomes a persisted,
owned, stateful request with a due next action *before* anything is parsed,
resolved, coordinated or routed. Everything after that point is enrichment: if
the parser recognises nothing, if the account is ambiguous, or if there is no
observable path at all, the request is still there, still owned, and still has
somebody's name against a next action. An operator who closes the tab has not
lost an ask.

Nothing here decides a route. Account and person candidates are surfaced for a
human to confirm, and candidate paths are ordered evidence about where to look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..config import Settings
from ..db.models import IntroRequest, Organization, Person, RequestTarget
from ..ingest.coordination import link_request
from ..intake.parse import ParsedAsk, parse_ask
from ..matching.accounts import canonical_key
from ..matching.normalize import norm_person, norm_ws
from .requests import (
    NewRequest,
    ValidationProblem,
    apply_target_and_paths,
    candidate_path_payload,
    get_request,
    log_event,
    persist_owned_request,
    related_requests,
    request_detail,
)
from .search import account_summary, person_summary

#: Beyond this, an operator is choosing from a list rather than confirming a match.
MAX_CANDIDATES = 8


class _FrozenClock:
    """Reuse the intake instant for every derived read in one response."""

    def __init__(self, now: datetime):
        self._now = now

    def now(self) -> datetime:
        return self._now


@dataclass
class IntakeSubmission:
    """What arrives from a Slack-style box. Only the ask is really required."""

    raw_ask: str = ""
    requester_name: str = ""
    account_text: str = ""
    target_person_name: str = ""
    target_title: str = ""
    deal_value_usd: int = 0
    urgency: str = ""
    operational_owner_id: int | None = None
    request_id: str | None = None
    #: Set by an operator confirming the named individual really exists.
    target_person_evidenced: bool = False


@dataclass
class Candidate:
    """One thing the ask might mean, with why it is on the list."""

    id: int
    label: str
    detail: str
    method: str
    confidence: str
    extra: dict = field(default_factory=dict)

    def payload(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "detail": self.detail,
            "method": self.method,
            "confidence": self.confidence,
            **self.extra,
        }


def account_candidates(session: Session, text: str, domains: tuple[str, ...] = ()) -> list[Candidate]:
    """Accounts this text could mean. Several means ambiguous, never a guess."""
    term = norm_ws(text)
    if not term and not domains:
        return []
    key = canonical_key(term)
    found: dict[int, Candidate] = {}

    if key:
        for org in session.scalars(select(Organization).where(Organization.canonical_key == key)).all():
            found[org.id] = Candidate(
                id=org.id,
                label=org.name,
                detail=f"CRM account {org.crm_account_id}" if org.crm_account_id else "known organization",
                method="exact_canonical_name",
                confidence="high",
                extra={"account": account_summary(org)},
            )
    for domain in domains:
        for org in session.scalars(select(Organization).where(Organization.domain == domain)).all():
            found.setdefault(
                org.id,
                Candidate(
                    id=org.id,
                    label=org.name,
                    detail=f"domain {domain}",
                    method="domain_match",
                    confidence="high",
                    extra={"account": account_summary(org)},
                ),
            )
    if not found and term:
        like = f"%{term.casefold()}%"
        for org in session.scalars(
            select(Organization)
            .where(or_(func.lower(Organization.name).like(like), func.lower(Organization.domain).like(like)))
            .order_by(Organization.is_crm_account.desc(), Organization.name)
            .limit(MAX_CANDIDATES)
        ).all():
            found[org.id] = Candidate(
                id=org.id,
                label=org.name,
                detail="name contains the requested text",
                method="substring",
                confidence="low",
                extra={"account": account_summary(org)},
            )

    ordered = sorted(found.values(), key=lambda candidate: (candidate.confidence != "high", candidate.label))
    return ordered[:MAX_CANDIDATES]


def person_candidates(session: Session, name: str) -> list[Candidate]:
    """People who share the requested name. Two of them is an ambiguity, not a pick."""
    term = norm_ws(name)
    if not term:
        return []
    key = norm_person(term)
    people = session.scalars(select(Person).where(Person.normalized_name == key)).all()
    method, confidence = "exact_normalized_name", "high"
    if not people:
        like = f"%{term.casefold()}%"
        people = session.scalars(
            select(Person).where(func.lower(Person.display_name).like(like)).order_by(Person.display_name).limit(
                MAX_CANDIDATES
            )
        ).all()
        method, confidence = "substring", "low"
    return [
        Candidate(
            id=person.id,
            label=person.display_name,
            detail=person.match_evidence or person.identity_basis,
            method=method,
            confidence="low" if person.review_status == "needs_review" else confidence,
            extra={"person": person_summary(person)},
        )
        for person in people[:MAX_CANDIDATES]
    ]


def _account_text(submission: IntakeSubmission, parsed: ParsedAsk) -> str:
    return norm_ws(submission.account_text) or parsed.account_text


def _person_text(submission: IntakeSubmission, parsed: ParsedAsk) -> str:
    return norm_ws(submission.target_person_name) or parsed.person_name


def _title_text(submission: IntakeSubmission, parsed: ParsedAsk) -> str:
    return norm_ws(submission.target_title) or parsed.title


def _confirmed_only(candidates: list[Candidate], resolved_id: int | None) -> list[Candidate]:
    """Once a human has answered, the alternatives stop being open questions."""
    if resolved_id is None:
        return []
    return [candidate for candidate in candidates if candidate.id == resolved_id]


def _confirmed_accounts(session: Session, candidates: list[Candidate], account_id: int | None) -> list[Candidate]:
    """The confirmed account, even when the resolver never proposed it."""
    kept = _confirmed_only(candidates, account_id)
    if kept or account_id is None:
        return kept
    org = session.get(Organization, account_id)
    if org is None:  # pragma: no cover - referential integrity
        return []
    return [
        Candidate(
            id=org.id,
            label=org.name,
            detail=f"CRM account {org.crm_account_id}" if org.crm_account_id else "known organization",
            method="human_confirmation",
            confidence="high",
            extra={"account": account_summary(org)},
        )
    ]


def _next_decision(
    request: IntroRequest,
    accounts: list[Candidate],
    people: list[Candidate],
    path_count: int,
) -> dict:
    """The one thing the operator should do next, and why.

    A human answer outranks the resolver: once the target has been confirmed the
    remaining candidates are history, and once a route is confirmed the decision
    is the follow-up, not the review that produced it.
    """
    if request.selected_connector_id is not None:
        return {
            "decision": "follow_up_connector",
            "prompt": (
                f"{request.next_action} Due {request.next_action_due_at:%Y-%m-%d}."
                if request.next_action_due_at
                else request.next_action
            ),
            "blocking": False,
        }
    if len(accounts) > 1:
        return {
            "decision": "confirm_account",
            "prompt": f"{len(accounts)} accounts match this ask. Confirm which one is meant.",
            "blocking": True,
        }
    if not accounts:
        return {
            "decision": "identify_account",
            "prompt": "No account could be resolved from the ask. Identify the target account.",
            "blocking": True,
        }
    if len(people) > 1:
        return {
            "decision": "confirm_person",
            "prompt": f"{len(people)} people share that name. Confirm which individual is meant.",
            "blocking": True,
        }
    if path_count == 0:
        return {
            "decision": "no_observable_path",
            "prompt": (
                "No observable path to this account. Decide whether to source a new connector, "
                "approach cold, or close with a reason — the request stays open and owned until then."
            ),
            "blocking": False,
        }
    return {
        "decision": "confirm_route",
        "prompt": "Review the ordered candidate paths and confirm or reject the recommended route.",
        "blocking": False,
    }


def intake_payload(
    session: Session,
    request: IntroRequest,
    parsed: ParsedAsk,
    settings: Settings,
    now: datetime,
) -> dict:
    """Everything the operator needs, hung off a request that already exists."""
    target: RequestTarget | None = request.target
    accounts = account_candidates(
        session,
        target.raw_account_text if target else "",
        parsed.domains,
    )
    people = person_candidates(session, target.raw_target_name if target else "")
    if target is not None and target.resolution_method == "human_confirmation":
        accounts = _confirmed_accounts(session, accounts, target.organization_id)
        people = _confirmed_only(people, target.resolved_person_id)
    paths = candidate_path_payload(session, request, settings, now)
    related = related_requests(session, request.request_id, settings, _FrozenClock(now))
    return {
        "request": request_detail(session, request.request_id, settings, _FrozenClock(now)),
        "parse": {
            "grammar": parsed.grammar,
            "confidence": parsed.confidence,
            "evidence": parsed.evidence,
            "warnings": list(parsed.warnings),
            "proposed": {
                "account_text": parsed.account_text,
                "person_name": parsed.person_name,
                "title": parsed.title,
                "normalized_title_family": parsed.normalized_title_family,
                "domains": list(parsed.domains),
            },
        },
        "account_candidates": [candidate.payload() for candidate in accounts],
        "person_candidates": [candidate.payload() for candidate in people],
        "account_activity": related["related"],
        "account_activity_note": related["note"],
        "paths": paths,
        "next_decision": _next_decision(request, accounts, people, paths["counts"]["total"]),
    }


def start_intake(
    session: Session,
    submission: IntakeSubmission,
    settings: Settings,
    clock: Clock,
) -> dict:
    """Persist the ask, then enrich it. Returns the full intake result.

    The persist step is committed on its own before enrichment runs, so a bug or
    a failure anywhere in parsing, resolution or path discovery cannot take the
    ask down with it: the request survives in triage, owned, with the operator's
    original words intact and a note saying enrichment failed.
    """
    if not norm_ws(submission.raw_ask) and not norm_ws(submission.account_text):
        raise ValidationProblem("a free-text ask or an account is required")

    now = clock.now()
    request = persist_owned_request(
        session,
        NewRequest(
            requester_name=submission.requester_name,
            target_account_text="",
            raw_ask=submission.raw_ask,
            deal_value_usd=submission.deal_value_usd,
            urgency=submission.urgency,
            request_id=submission.request_id,
            operational_owner_id=submission.operational_owner_id,
        ),
        settings,
        clock,
    )

    session.commit()
    request_key = request.request_id

    parsed = parse_ask(submission.raw_ask)
    try:
        apply_target_and_paths(
            session,
            request,
            NewRequest(
                requester_name=submission.requester_name,
                target_account_text=_account_text(submission, parsed),
                raw_ask=submission.raw_ask,
                target_person_name=_person_text(submission, parsed),
                target_title=_title_text(submission, parsed),
                target_person_evidenced=submission.target_person_evidenced,
            ),
            settings,
            now,
        )
        if parsed.warnings and request.target is not None:
            request.target.resolution_evidence = "; ".join(
                filter(None, [request.target.resolution_evidence, *parsed.warnings])
            )
        link_request(session, request, settings)
        session.flush()
    except Exception as exc:  # enrichment is best-effort; the ask is already safe
        session.rollback()
        request = get_request(session, request_key)
        log_event(
            session,
            request,
            "enrichment_failed",
            now,
            actor="system",
            detail=f"{type(exc).__name__}: {exc}. Request stays in triage with the original ask preserved.",
        )
        session.flush()
    return intake_payload(session, request, parsed, settings, now)


def reintake(session: Session, request_key: str, settings: Settings, clock: Clock) -> dict:
    """Re-run enrichment for an existing request without touching its identity."""
    request = get_request(session, request_key)
    parsed = parse_ask(request.raw_ask)
    return intake_payload(session, request, parsed, settings, clock.now())


__all__ = [
    "Candidate",
    "IntakeSubmission",
    "MAX_CANDIDATES",
    "account_candidates",
    "intake_payload",
    "person_candidates",
    "reintake",
    "start_intake",
]
