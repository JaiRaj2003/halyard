"""Related activity on the same account, graded by how related it actually is.

Two people working two different buyers at one account are doing parallel work
that should be coordinated — they are not duplicates, and the system never
merges or blocks them. Only an explicit re-ask, or two asks for the same named
person, are treated as the same ask.
"""

from __future__ import annotations

from itertools import combinations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import AccountCoordination, IntroRequest
from ..matching.accounts import canonical_key
from ..matching.normalize import norm_person

SAME_ACCOUNT = "same_canonical_account"
SAME_TITLE_FAMILY = "same_account_same_title_family"
SAME_PERSON = "same_account_same_target_person"
EXPLICIT_REASK = "explicit_reask"

REASK_PHRASES = ("asking again", "same as the one from last month", "did we not already lose this one")


def _is_reask(request: IntroRequest) -> bool:
    text = (request.raw_ask or "").casefold()
    return any(phrase in text for phrase in REASK_PHRASES)


def account_key(request: IntroRequest) -> str:
    """The account a request belongs to, canonical if resolved, raw if not."""
    if request.organization_id is not None and request.organization is not None:
        return request.organization.canonical_key
    return canonical_key(request.target.raw_account_text) if request.target else ""


def _relate(session: Session, left: IntroRequest, right: IntroRequest, key: str, settings: Settings) -> None:
    left_target, right_target = left.target, right.target
    left_person = norm_person(left_target.raw_target_name) if left_target else ""
    right_person = norm_person(right_target.raw_target_name) if right_target else ""
    left_family = left_target.normalized_title_family if left_target else ""
    right_family = right_target.normalized_title_family if right_target else ""

    if _is_reask(left) or _is_reask(right):
        relation = EXPLICIT_REASK
        detail = "one of the two requests explicitly describes itself as a repeat ask"
    elif left_person and left_person == right_person:
        relation = SAME_PERSON
        detail = "both requests name the same target person"
    elif left_family and left_family == right_family:
        relation = SAME_TITLE_FAMILY
        detail = "different named targets, same title family at the same account"
    else:
        relation = SAME_ACCOUNT
        detail = "different targets at the same account: parallel activity to coordinate, not a duplicate"

    days_apart = None
    if left.requested_at and right.requested_at:
        days_apart = abs((left.requested_at - right.requested_at).days)
    session.add(
        AccountCoordination(
            request_id_a=left.id,
            request_id_b=right.id,
            organization_id=left.organization_id or right.organization_id,
            canonical_key=key,
            relation_type=relation,
            days_apart=days_apart,
            within_window=bool(days_apart is not None and days_apart <= settings.coordination_window_days),
            same_requester=left.requester_id == right.requester_id,
            detail=detail,
        )
    )


def build_coordination(session: Session, requests: dict[str, IntroRequest], settings: Settings) -> int:
    groups: dict[str, list[IntroRequest]] = {}
    for request in requests.values():
        key = account_key(request)
        if key:
            groups.setdefault(key, []).append(request)

    created = 0
    for key, members in sorted(groups.items()):
        for left, right in combinations(sorted(members, key=lambda r: r.request_id), 2):
            _relate(session, left, right, key, settings)
            created += 1
    session.flush()
    return created


def link_request(session: Session, request: IntroRequest, settings: Settings) -> int:
    """Relate one live request to whatever else is already open on its account.

    Re-runnable: existing links for this request are replaced, so re-resolving a
    target after an operator corrects the account does not leave stale pairs.
    """
    key = account_key(request)
    for stale in session.scalars(
        select(AccountCoordination).where(
            or_(AccountCoordination.request_id_a == request.id, AccountCoordination.request_id_b == request.id)
        )
    ).all():
        session.delete(stale)
    session.flush()
    if not key:
        return 0

    others = [
        other
        for other in session.scalars(select(IntroRequest).where(IntroRequest.id != request.id)).all()
        if account_key(other) == key
    ]
    for other in sorted(others, key=lambda r: r.request_id):
        left, right = sorted((request, other), key=lambda r: r.request_id)
        _relate(session, left, right, key, settings)
    session.flush()
    return len(others)
