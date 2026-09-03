"""Candidate paths: where to investigate, never proof that an intro is available.

Three honest labels, and nothing stronger:

``historically_observable``
    The relationship is dated and the date pre-dates the request, so it
    demonstrably existed when the ask was made.
``snapshot_only``
    The relationship is visible in the supplied snapshot but carries no date.
    Whether it existed at the time of the request is unknown.
``post_dates_request``
    The relationship began after the ask, so it cannot have been a missed path.

No field here says an introduction can be made. Every path states its
limitations, and a human reviews the route before any connector is treated as
confirmed.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Connector, IntroCandidatePath, IntroRequest, Organization, Person, RelationshipEdge
from ..matching.accounts import canonical_key
from ..matching.normalize import norm_person, title_family

SNAPSHOT_NOTE = "Visible in the supplied snapshot only; whether the relationship existed at request time is unknown."
COLLEAGUE_NOTE = (
    "Connection is to a colleague at the target account, not to the requested person; onward reachability inside "
    "the account is unknown."
)
DIRECT_NOTE = "Name match to the requested target person; no signal about the strength of the relationship."
NOT_REACHABLE_NOTE = " Connector is not on the managed roster, so their willingness and capacity are unknown."

HOP_DIRECT = "direct_target_person"
HOP_COLLEAGUE = "colleague_at_target_account"
HOP_INVESTOR = "investor_relationship_to_account"

HISTORICALLY_OBSERVABLE = "historically_observable"
SNAPSHOT_ONLY = "snapshot_only"
POST_DATES_REQUEST = "post_dates_request"


def _observability(relationship_date, request_date) -> str:
    if relationship_date is None or request_date is None:
        return SNAPSHOT_ONLY
    return HISTORICALLY_OBSERVABLE if relationship_date <= request_date.date() else POST_DATES_REQUEST


def build_candidate_paths(session: Session, requests: dict[str, IntroRequest]) -> dict[int, int]:
    """One row per (request, connector, edge). Returns path counts per request id."""
    edges = session.scalars(select(RelationshipEdge)).all()
    persons = {person.id: person for person in session.scalars(select(Person)).all()}
    orgs = {org.id: org for org in session.scalars(select(Organization)).all()}
    connectors = {connector.id: connector for connector in session.scalars(select(Connector)).all()}

    by_person_name: dict[str, list[RelationshipEdge]] = {}
    by_org_key: dict[str, list[RelationshipEdge]] = {}
    for edge in edges:
        if edge.person_id is not None:
            by_person_name.setdefault(persons[edge.person_id].normalized_name, []).append(edge)
        if edge.organization_id is not None:
            by_org_key.setdefault(orgs[edge.organization_id].canonical_key, []).append(edge)

    counts: dict[int, int] = {}
    for request in requests.values():
        target = request.target
        if target is None:  # pragma: no cover - every request gets a target
            continue
        target_person_key = norm_person(target.raw_target_name)
        account_key = canonical_key(target.raw_account_text)
        if not account_key and request.organization_id is not None:
            account_key = orgs[request.organization_id].canonical_key
        family = target.normalized_title_family
        seen: set[tuple[int, int]] = set()

        for edge in by_person_name.get(target_person_key, []) if target_person_key else []:
            _add_path(session, request, edge, connectors, persons, orgs, HOP_DIRECT, family, seen, counts)

        for edge in by_org_key.get(account_key, []) if account_key else []:
            if edge.person_id is not None and persons[edge.person_id].normalized_name == target_person_key:
                continue
            hop = HOP_COLLEAGUE if edge.person_id is not None else HOP_INVESTOR
            _add_path(session, request, edge, connectors, persons, orgs, hop, family, seen, counts)

    session.flush()
    return counts


def _add_path(
    session: Session,
    request: IntroRequest,
    edge: RelationshipEdge,
    connectors: dict[int, Connector],
    persons: dict[int, Person],
    orgs: dict[int, Organization],
    hop_type: str,
    target_family: str,
    seen: set[tuple[int, int]],
    counts: dict[int, int],
) -> None:
    key = (edge.connector_id, edge.id)
    if key in seen:
        return
    seen.add(key)
    connector = connectors[edge.connector_id]
    contact = persons.get(edge.person_id) if edge.person_id else None
    org = orgs.get(edge.organization_id) if edge.organization_id else None
    observability = _observability(edge.relationship_date, request.requested_at)

    contact_family = ""
    if contact is not None:
        titles = [affiliation.title for affiliation in contact.affiliations]
        contact_family = title_family(titles[0]) if titles else ""
    same_family = bool(target_family and contact_family == target_family)

    if hop_type == HOP_DIRECT:
        limitations = DIRECT_NOTE
        confidence = "medium"
    elif hop_type == HOP_COLLEAGUE:
        limitations = COLLEAGUE_NOTE
        confidence = "medium" if same_family else "low"
    else:
        limitations = f"{SNAPSHOT_NOTE} Relationship is to the account, not to any named person at it."
        confidence = "medium" if edge.edge_type == "investor_board_seat" else "low"
    if observability == SNAPSHOT_ONLY and SNAPSHOT_NOTE not in limitations:
        limitations = f"{SNAPSHOT_NOTE} {limitations}"
    if observability == POST_DATES_REQUEST:
        limitations = f"Relationship began after the request date, so it was not available at the time. {limitations}"
    if not connector.on_roster:
        limitations += NOT_REACHABLE_NOTE

    evidence_subject = contact.display_name if contact is not None else (org.name if org is not None else "")
    session.add(
        IntroCandidatePath(
            request_id=request.id,
            connector_id=connector.id,
            relationship_edge_id=edge.id,
            hop_type=hop_type,
            observability=observability,
            connector_reachable=connector.on_roster,
            same_title_family=same_family,
            relationship_date=edge.relationship_date,
            confidence=confidence,
            limitations=limitations,
            evidence=f"{connector.name} -> {evidence_subject} ({edge.edge_type}); {edge.raw_value}",
            source_file=edge.source_file,
            source_record_id=edge.source_record_id,
        )
    )
    counts[request.id] = counts.get(request.id, 0) + 1
