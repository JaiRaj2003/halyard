"""Search and canonical entity detail.

Results carry their match evidence and review status, so an operator can see
why something matched rather than trusting a ranked list.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db.models import (
    Affiliation,
    Connector,
    IntroRequest,
    Organization,
    Person,
    RelationshipEdge,
    RequestTarget,
)
from ..matching.accounts import canonical_key
from ..matching.normalize import norm_person


def search(session: Session, query: str, limit: int = 20) -> dict:
    term = query.strip()
    if not term:
        return {"query": query, "accounts": [], "people": [], "connectors": []}
    like = f"%{term.casefold()}%"
    key = canonical_key(term)
    person_key = norm_person(term)

    accounts = session.scalars(
        select(Organization)
        .where(
            or_(
                func.lower(Organization.name).like(like),
                Organization.canonical_key == key,
                func.lower(Organization.domain).like(like),
            )
        )
        .order_by(Organization.is_crm_account.desc(), Organization.name)
        .limit(limit)
    ).all()

    people = session.scalars(
        select(Person)
        .where(or_(func.lower(Person.display_name).like(like), Person.normalized_name == person_key))
        .order_by(Person.display_name)
        .limit(limit)
    ).all()

    connectors = session.scalars(
        select(Connector).where(func.lower(Connector.name).like(like)).order_by(Connector.name).limit(limit)
    ).all()

    return {
        "query": query,
        "accounts": [account_summary(account) for account in accounts],
        "people": [person_summary(person) for person in people],
        "connectors": [connector_summary(connector) for connector in connectors],
    }


def account_summary(account: Organization) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "crm_account_id": account.crm_account_id,
        "domain": account.domain,
        "domain_group": account.domain_group,
        "is_crm_account": account.is_crm_account,
        "review_status": account.review_status,
        "match_evidence": account.match_evidence,
        "competing_candidates": _split(account.competing_candidates),
    }


def person_summary(person: Person) -> dict:
    return {
        "id": person.id,
        "display_name": person.display_name,
        "identity_basis": person.identity_basis,
        "is_internal": person.is_internal,
        "source_type": person.source_type,
        "profile_url": person.profile_url,
        "review_status": person.review_status,
        "confidence": person.confidence,
        "competing_candidates": _split(person.competing_candidates),
    }


def connector_summary(connector: Connector) -> dict:
    return {
        "id": connector.id,
        "name": connector.name,
        "on_roster": connector.on_roster,
        "connector_type": connector.connector_type,
        "stated_monthly_capacity": connector.stated_monthly_capacity,
        "observed_in": connector.observed_in,
        "note": (
            ""
            if connector.on_roster
            else "Observed connector not present in the managed connector roster; capacity unknown."
        ),
    }


def account_detail(session: Session, account_id: int) -> dict | None:
    account = session.get(Organization, account_id)
    if account is None:
        return None
    same_domain = []
    if account.domain_group:
        same_domain = session.scalars(
            select(Organization).where(
                Organization.domain_group == account.domain_group, Organization.id != account.id
            )
        ).all()
    #: One person can hold several affiliations to the same account; that is one person.
    people = session.scalars(
        select(Person).join(Affiliation, Affiliation.person_id == Person.id).where(
            Affiliation.organization_id == account.id
        ).distinct().order_by(Person.display_name, Person.id)
    ).all()
    requests = session.scalars(
        select(IntroRequest).where(IntroRequest.organization_id == account.id).order_by(IntroRequest.request_id)
    ).all()
    edges = session.scalars(
        select(RelationshipEdge).where(RelationshipEdge.organization_id == account.id)
    ).all()
    return {
        **account_summary(account),
        "industry": account.industry,
        "hq": account.hq,
        "employee_count": account.employee_count,
        "stage": account.stage,
        "arr_potential_usd": account.arr_potential_usd,
        "crm_owner": account.crm_owner,
        "source_record_id": account.source_record_id,
        "shares_domain_with": [
            {"id": other.id, "name": other.name, "crm_account_id": other.crm_account_id} for other in same_domain
        ],
        "known_people": [person_summary(person) for person in people][:50],
        "known_people_count": len(people),
        "relationship_edge_count": len(edges),
        "requests": [
            {"request_id": request.request_id, "workflow_state": request.workflow_state} for request in requests
        ],
    }


def person_detail(session: Session, person_id: int) -> dict | None:
    person = session.get(Person, person_id)
    if person is None:
        return None
    affiliations = session.scalars(select(Affiliation).where(Affiliation.person_id == person.id)).all()
    orgs = {org.id: org for org in session.scalars(select(Organization)).all()}
    connector = session.scalar(select(Connector).where(Connector.person_id == person.id))
    targeted_by = session.scalars(
        select(RequestTarget).where(RequestTarget.resolved_person_id == person.id)
    ).all()
    return {
        **person_summary(person),
        "raw_value": person.raw_value,
        "match_method": person.match_method,
        "match_evidence": person.match_evidence,
        "source_record_id": person.source_record_id,
        "affiliations": [
            {
                "organization_id": affiliation.organization_id,
                "organization": orgs[affiliation.organization_id].name,
                "title": affiliation.title,
                "title_family": affiliation.title_family,
                "start_date": affiliation.start_date,
                "date_precision": affiliation.date_precision,
                "confidence": affiliation.confidence,
                "raw_value": affiliation.raw_value,
            }
            for affiliation in affiliations
        ],
        "connector": connector_summary(connector) if connector else None,
        "targeted_by_requests": [target.request.request_id for target in targeted_by],
    }


def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]
