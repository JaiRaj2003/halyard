"""Canonical entities: organizations, people, connectors, affiliations, edges.

All matching goes through :mod:`halyard.matching`, the same code the forensic
audit runs, so the product and the audit can never drift apart on what counts as
the same account or the same person.

Where the evidence does not support a decision, the row is written anyway with
``review_status='needs_review'`` and the competing candidates attached. Nothing
is dropped for being ambiguous.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.orm import Session

from ..db.models import (
    Affiliation,
    Connector,
    CoverageGap,
    DataQualityIssue,
    EntityMatch,
    Organization,
    Person,
    RelationshipEdge,
    SourceRecord,
)
from ..matching.accounts import (
    TIER_AMBIGUOUS,
    TIER_EXACT_ID,
    TIER_PROBABLE_DOMAIN_GROUP,
    TIER_UNMATCHED,
    AccountMatch,
    AccountResolver,
    canonical_key,
)
from ..matching.normalize import (
    is_malformed_name,
    norm_company,
    norm_domain,
    norm_person,
    norm_url,
    norm_ws,
    parse_date,
    parse_partial_date,
    title_family,
)
from ..matching.people import T1, T3, T4, PersonResolver
from .raw import CONNECTION_FILES, payload

RESOLVED_ACCOUNT_TIERS = {TIER_EXACT_ID, "A_exact_unique_domain", "B_probable_name_exact"}
RESOLVED_PERSON_TIERS = {T1, T3, T4}


@dataclass
class EntityIndex:
    """Everything later stages need to look entities up by their natural keys."""

    organizations_by_key: dict[str, Organization] = field(default_factory=dict)
    organizations_by_crm_id: dict[str, Organization] = field(default_factory=dict)
    persons_by_key: dict[str, Person] = field(default_factory=dict)
    persons_by_norm_name: dict[str, list[Person]] = field(default_factory=dict)
    connectors_by_norm_name: dict[str, Connector] = field(default_factory=dict)
    edges_by_connector: dict[int, list[RelationshipEdge]] = field(default_factory=dict)
    affiliation_keys: set[tuple[int, int, str]] = field(default_factory=set)
    account_resolver: AccountResolver | None = None
    person_resolver: PersonResolver | None = None
    account_match_cache: dict[str, AccountMatch] = field(default_factory=dict)

    def person_by_name(self, name: object) -> Person | None:
        matches = self.persons_by_norm_name.get(norm_person(name), [])
        return matches[0] if len(matches) == 1 else None


def frame_from(records: list[SourceRecord], extra: dict[str, str] | None = None) -> pd.DataFrame:
    rows = []
    for record in records:
        row = payload(record)
        row["record_id"] = record.id
        row["source_file_name"] = record.filename
        row["parse_status"] = record.parse_status
        if extra:
            row.update(extra)
        rows.append(row)
    return pd.DataFrame(rows)


def connections_frame(staged: dict[str, list[SourceRecord]]) -> pd.DataFrame:
    frames = []
    for connector, filename in CONNECTION_FILES.items():
        frame = frame_from(staged[filename], {"connector": connector})
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def build_entities(session: Session, staged: dict[str, list[SourceRecord]]) -> EntityIndex:
    index = EntityIndex()
    crm = frame_from(staged["crm_accounts.csv"])
    connections = connections_frame(staged)
    index.account_resolver = AccountResolver(crm)
    index.person_resolver = PersonResolver(connections)

    _build_crm_organizations(session, crm, index)
    _build_export_people(session, connections, index)
    _build_connectors(session, staged, index)
    _build_connection_edges(session, connections, index)
    _build_investor_edges(session, staged, index)
    session.flush()
    return index


# -- organizations ------------------------------------------------------------


def _build_crm_organizations(session: Session, crm: pd.DataFrame, index: EntityIndex) -> None:
    domain_counts: dict[str, int] = {}
    for row in crm.itertuples():
        domain_counts[norm_domain(row.domain)] = domain_counts.get(norm_domain(row.domain), 0) + 1

    for row in crm.itertuples():
        domain = norm_domain(row.domain)
        shared = domain_counts.get(domain, 0) > 1
        org = _get_or_create_org(
            session,
            index,
            key=canonical_key(row.account_name),
            crm_account_id=row.account_id,
            name=row.account_name,
            raw_name=row.account_name,
            normalized_name=norm_company(row.account_name),
            domain=domain,
            domain_group=f"DG_{domain}" if shared else "",
            is_crm_account=True,
            industry=row.industry,
            hq=row.hq,
            employee_count=row.employee_count,
            stage=row.stage,
            arr_potential_usd=int(row.arr_potential_usd) if str(row.arr_potential_usd).isdigit() else None,
            crm_owner=row.owner,
            match_tier=TIER_EXACT_ID,
            match_method="crm_account_id",
            match_evidence=f"CRM row for account_id {row.account_id}",
            confidence="definitive",
            review_status="needs_review" if shared else "resolved",
            competing_candidates=(
                f"shares domain {domain} with {domain_counts[domain] - 1} other CRM account(s); kept separate"
                if shared
                else ""
            ),
            source_record_id=row.record_id,
        )
        index.organizations_by_crm_id[row.account_id] = org
        if shared:
            session.add(
                DataQualityIssue(
                    check="crm_shared_domain",
                    severity="medium",
                    subject=f"{row.account_id}:{row.account_name}",
                    detail=(
                        f"domain {domain} is used by {domain_counts[domain]} CRM accounts; the accounts are kept "
                        "separate because no identifier proves they are the same entity"
                    ),
                    source_record_id=row.record_id,
                )
            )


def _get_or_create_org(session: Session, index: EntityIndex, key: str, **kwargs) -> Organization:
    crm_id = kwargs.get("crm_account_id")
    if crm_id and crm_id in index.organizations_by_crm_id:
        return index.organizations_by_crm_id[crm_id]
    if not crm_id and key in index.organizations_by_key:
        return index.organizations_by_key[key]
    org = Organization(canonical_key=key, **kwargs)
    session.add(org)
    session.flush()
    index.organizations_by_key.setdefault(key, org)
    if crm_id:
        index.organizations_by_crm_id[crm_id] = org
    return org


def resolve_account(
    session: Session,
    index: EntityIndex,
    raw_name: object,
    domain_hints: list[str] | None = None,
    source_record_id: int | None = None,
    subject_context: str = "",
    record_match: bool = True,
) -> tuple[Organization | None, AccountMatch]:
    """Resolve a company string to a canonical organization, or to nothing.

    A non-CRM company that the exports mention is still a real organization, so
    it gets its own row — flagged as non-CRM rather than forced onto a CRM
    account it merely resembles.
    """
    assert index.account_resolver is not None
    raw = norm_ws(raw_name)
    cache_key = f"{raw.casefold()}|{','.join(domain_hints or [])}"
    match = index.account_match_cache.get(cache_key)
    if match is None:
        match = index.account_resolver.resolve(raw, domain_hints)
        index.account_match_cache[cache_key] = match

    org: Organization | None = None
    if match.account_id:
        org = index.organizations_by_crm_id.get(match.account_id)
    elif raw and match.tier not in {TIER_AMBIGUOUS, TIER_PROBABLE_DOMAIN_GROUP}:
        org = _get_or_create_org(
            session,
            index,
            key=canonical_key(raw),
            crm_account_id=None,
            name=raw,
            raw_name=raw,
            normalized_name=norm_company(raw),
            domain="",
            domain_group="",
            is_crm_account=False,
            match_tier=match.tier,
            match_method=match.method or "non_crm_observed_company",
            match_evidence=match.evidence or "company observed in supplied network data with no CRM account",
            confidence="low" if match.tier == TIER_UNMATCHED else "medium",
            review_status="resolved",
            competing_candidates="; ".join(match.competing_candidates),
            source_record_id=source_record_id,
        )

    if record_match:
        session.add(
            EntityMatch(
                subject_type="account",
                subject_value=raw,
                subject_context=subject_context,
                tier=match.tier,
                method=match.method,
                evidence=match.evidence,
                verdict=(
                    "resolved"
                    if match.tier in RESOLVED_ACCOUNT_TIERS
                    else ("ambiguous" if match.tier in {TIER_AMBIGUOUS, TIER_PROBABLE_DOMAIN_GROUP} else "unmatched")
                ),
                resolved_organization_id=(
                    org.id if org is not None and match.tier in RESOLVED_ACCOUNT_TIERS else None
                ),
                competing_candidates="; ".join(match.competing_candidates),
                source_record_id=source_record_id,
            )
        )
    return org, match


# -- people -------------------------------------------------------------------


def _add_person(session: Session, index: EntityIndex, person_key: str, **kwargs) -> Person:
    existing = index.persons_by_key.get(person_key)
    if existing is not None:
        return existing
    person = Person(person_key=person_key, **kwargs)
    session.add(person)
    session.flush()
    index.persons_by_key[person_key] = person
    index.persons_by_norm_name.setdefault(person.normalized_name, []).append(person)
    return person


def _build_export_people(session: Session, connections: pd.DataFrame, index: EntityIndex) -> None:
    assert index.person_resolver is not None
    identities = index.person_resolver.identities()
    first_record: dict[str, int] = {}
    for row in connections.itertuples():
        first_record.setdefault(norm_person(row.name), row.record_id)

    for row in identities.itertuples():
        malformed = is_malformed_name(row.display_name)
        person = _add_person(
            session,
            index,
            person_key=row.person_key,
            display_name=row.display_name,
            normalized_name=row.normalized_name,
            identity_basis="profile_url" if row.identity_basis == "profile_url" else "name_only_export",
            profile_url=row.profile_urls.split("; ")[0] if row.profile_urls else "",
            is_internal=False,
            source_type="historical_corpus",
            match_tier=T1 if row.identity_basis == "profile_url" else "T2_name_only_identity",
            match_method=row.identity_basis,
            match_evidence=(
                f"{row.export_rows} export row(s) across {row.appears_in_exports or 'no'} export(s)"
            ),
            confidence="high" if row.identity_basis == "profile_url" else "medium",
            competing_candidates=row.organizations if row.conflicting_affiliation else "",
            review_status="needs_review" if (row.conflicting_affiliation or malformed) else "resolved",
            raw_value=row.display_name,
            source_record_id=first_record.get(row.normalized_name),
        )
        if malformed:
            session.add(
                DataQualityIssue(
                    check="malformed_person_name",
                    severity="medium",
                    subject=row.display_name,
                    detail="name in a connection export does not look like a person name; kept and flagged",
                    source_record_id=person.source_record_id,
                )
            )
        if row.conflicting_affiliation:
            session.add(
                DataQualityIssue(
                    check="conflicting_affiliation",
                    severity="low",
                    subject=row.display_name,
                    detail=f"appears at several organizations: {row.organizations}",
                    source_record_id=person.source_record_id,
                )
            )


def person_for_name(
    session: Session,
    index: EntityIndex,
    name: object,
    org: object = "",
    title: object = "",
    is_internal: bool = False,
    source_record_id: int | None = None,
    subject_context: str = "",
) -> Person | None:
    """Find or create the person a *named individual* mention refers to.

    Used only where the source names an actual person (a requester, a connector,
    a Slack author). Target personas never reach this function.
    """
    assert index.person_resolver is not None
    raw = norm_ws(name)
    if not raw:
        return None
    normalized = norm_person(raw)
    existing = index.persons_by_norm_name.get(normalized, [])
    if len(existing) == 1:
        return existing[0]

    match = index.person_resolver.resolve(raw, org, title)
    session.add(
        EntityMatch(
            subject_type="person",
            subject_value=raw,
            subject_context=subject_context,
            tier=match.tier,
            method=match.method,
            evidence=match.evidence,
            verdict="resolved" if match.tier in RESOLVED_PERSON_TIERS else (
                "ambiguous" if match.tier.startswith("T2") or match.tier.startswith("T5") else "unmatched"
            ),
            competing_candidates="; ".join(match.candidates),
            source_record_id=source_record_id,
        )
    )
    if match.tier in RESOLVED_PERSON_TIERS and match.person_key in index.persons_by_key:
        return index.persons_by_key[match.person_key]

    return _add_person(
        session,
        index,
        person_key=f"internal:{normalized}" if is_internal else f"name:{normalized}",
        display_name=raw,
        normalized_name=normalized,
        identity_basis="internal_directory" if is_internal else "name_only_export",
        profile_url="",
        is_internal=is_internal,
        source_type="historical_corpus",
        match_tier=match.tier,
        match_method=match.method,
        match_evidence=match.evidence,
        confidence="medium" if is_internal else "low",
        competing_candidates="; ".join(match.candidates),
        review_status="resolved" if is_internal else "needs_review",
        raw_value=raw,
        source_record_id=source_record_id,
    )


# -- connectors ---------------------------------------------------------------


def _build_connectors(session: Session, staged: dict[str, list[SourceRecord]], index: EntityIndex) -> None:
    for record in staged["connector_roster.csv"]:
        row = payload(record)
        person = person_for_name(
            session, index, row["name"], is_internal=True, source_record_id=record.id, subject_context="connector_roster"
        )
        assert person is not None
        capacity = row.get("stated_monthly_capacity", "")
        connector = Connector(
            person_id=person.id,
            name=norm_ws(row["name"]),
            on_roster=True,
            connector_type=row.get("type", ""),
            role=row.get("role", ""),
            focus_areas=row.get("focus_areas", ""),
            stated_monthly_capacity=int(capacity) if str(capacity).isdigit() else None,
            notes=row.get("notes", ""),
            observed_in="connector_roster.csv",
            source_record_id=record.id,
        )
        session.add(connector)
        session.flush()
        index.connectors_by_norm_name[norm_person(row["name"])] = connector


def observed_connector(
    session: Session,
    index: EntityIndex,
    name: object,
    source_record_id: int | None,
    observed_in: str,
) -> Connector | None:
    """Connector seen in the data. Absence from the roster is a coverage gap.

    Off-roster connectors are real people doing real routing work; the roster
    simply does not manage them, so they carry no stated capacity and are
    reported as a gap in the operating model rather than as a bad record.
    """
    raw = norm_ws(name)
    if not raw:
        return None
    key = norm_person(raw)
    if key in index.connectors_by_norm_name:
        return index.connectors_by_norm_name[key]

    person = person_for_name(
        session, index, raw, is_internal=True, source_record_id=source_record_id, subject_context=observed_in
    )
    assert person is not None
    connector = Connector(
        person_id=person.id,
        name=raw,
        on_roster=False,
        stated_monthly_capacity=None,
        observed_in=observed_in,
        notes="Observed connector not present in the managed connector roster.",
        source_record_id=source_record_id,
    )
    session.add(connector)
    session.flush()
    index.connectors_by_norm_name[key] = connector
    session.add(
        CoverageGap(
            gap_type="connector_not_on_roster",
            subject=raw,
            detail=(
                f"acted as a connector in {observed_in} but is not in connector_roster.csv; no stated capacity is "
                "known, so their load cannot be managed"
            ),
            source_record_id=source_record_id,
        )
    )
    return connector


# -- relationship edges -------------------------------------------------------


def _build_connection_edges(session: Session, connections: pd.DataFrame, index: EntityIndex) -> None:
    for row in connections.itertuples():
        connector = index.connectors_by_norm_name.get(norm_person(row.connector))
        if connector is None:  # pragma: no cover - roster covers all six exports
            continue
        person = index.persons_by_norm_name.get(norm_person(row.name), [None])[0]
        if person is None:
            continue
        org, _ = resolve_account(
            session,
            index,
            row.company,
            domain_hints=None,
            source_record_id=row.record_id,
            subject_context=f"connection_export:{row.source_file_name}",
            record_match=False,
        )
        connected_on = parse_date(row.connected_on)
        edge = RelationshipEdge(
            connector_id=connector.id,
            person_id=person.id,
            organization_id=org.id if org else None,
            edge_type="connection_export",
            relationship_date=connected_on,
            date_precision="day" if connected_on else "unknown",
            raw_value=f"{row.name} | {row.company} | {row.title} | connected_on={row.connected_on}",
            confidence="high" if row.profile_url else "medium",
            source_file=row.source_file_name,
            source_record_id=row.record_id,
        )
        _add_edge(session, index, edge)

        if org is not None:
            _add_affiliation(
                session,
                index,
                Affiliation(
                    person_id=person.id,
                    organization_id=org.id,
                    title=norm_ws(row.title),
                    title_family=title_family(row.title),
                    start_date=None,
                    end_date=None,
                    date_precision="unknown",
                    is_current=True,
                    match_method="connection_export",
                    confidence="medium",
                    raw_value=f"{row.company} | {row.title}",
                    source_record_id=row.record_id,
                ),
            )
        if not norm_url(row.profile_url):
            session.add(
                DataQualityIssue(
                    check="missing_profile_url",
                    severity="low",
                    subject=f"{row.name} ({row.connector} export)",
                    detail="connection row has no profile_url, so the identity rests on the name alone",
                    source_record_id=row.record_id,
                )
            )


def _build_investor_edges(session: Session, staged: dict[str, list[SourceRecord]], index: EntityIndex) -> None:
    for record in staged["investor_network.csv"]:
        row = payload(record)
        connector = observed_connector(session, index, row.get("person"), record.id, "investor_network.csv")
        if connector is None:
            continue
        portfolio = norm_ws(row.get("portfolio_company", ""))
        if portfolio:
            org, _ = resolve_account(
                session,
                index,
                portfolio,
                source_record_id=record.id,
                subject_context="investor_network.portfolio_company",
                record_match=False,
            )
            _add_edge(
                session,
                index,
                RelationshipEdge(
                    connector_id=connector.id,
                    person_id=None,
                    organization_id=org.id if org else None,
                    edge_type="investor_board_seat" if row.get("board_seat") == "True" else "investor_portfolio",
                    relationship_date=None,
                    date_precision="unknown",
                    raw_value=f"{row.get('fund', '')} | {portfolio} | board_seat={row.get('board_seat', '')}",
                    confidence="medium",
                    source_file="investor_network.csv",
                    source_record_id=record.id,
                ),
            )
        prior = norm_ws(row.get("prior_employer", ""))
        if prior:
            org, _ = resolve_account(
                session,
                index,
                prior,
                source_record_id=record.id,
                subject_context="investor_network.prior_employer",
                record_match=False,
            )
            start = parse_partial_date(row.get("prior_employer_start"))
            end = parse_partial_date(row.get("prior_employer_end"))
            _add_edge(
                session,
                index,
                RelationshipEdge(
                    connector_id=connector.id,
                    person_id=None,
                    organization_id=org.id if org else None,
                    edge_type="prior_employer",
                    relationship_date=start,
                    date_precision="year" if start else "unknown",
                    raw_value=f"{prior} | {row.get('prior_employer_start', '')}-{row.get('prior_employer_end', '')}",
                    confidence="medium",
                    source_file="investor_network.csv",
                    source_record_id=record.id,
                ),
            )
            if org is not None:
                _add_affiliation(
                    session,
                    index,
                    Affiliation(
                        person_id=connector.person_id,
                        organization_id=org.id,
                        title="",
                        title_family="",
                        start_date=start,
                        end_date=end,
                        date_precision="year" if start else "unknown",
                        is_current=False,
                        match_method="investor_network_prior_employer",
                        confidence="medium",
                        raw_value=prior,
                        source_record_id=record.id,
                    ),
                )
    session.flush()
    # Edges added after the connection exports need to be visible to path building.
    for connector in index.connectors_by_norm_name.values():
        index.edges_by_connector.setdefault(connector.id, [])


def _add_edge(session: Session, index: EntityIndex, edge: RelationshipEdge) -> RelationshipEdge:
    session.add(edge)
    session.flush()
    index.edges_by_connector.setdefault(edge.connector_id, []).append(edge)
    return edge


def _add_affiliation(session: Session, index: EntityIndex, affiliation: Affiliation) -> None:
    """One affiliation per (person, organization, title); repeats are the same fact."""
    key = (affiliation.person_id, affiliation.organization_id, affiliation.title)
    if key in index.affiliation_keys:
        return
    index.affiliation_keys.add(key)
    session.add(affiliation)


def dump_candidates(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)
