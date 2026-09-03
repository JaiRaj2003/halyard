"""Canonical schema.

Two rules run through every table here.

**Provenance.** Anything derived from the supplied data points back at the
``source_records`` row it came from, and carries the match method, the
confidence and the raw value it was derived from. Nothing is a bare assertion.

**Ambiguity survives.** Where the evidence is thin or conflicting the row says
so (``review_status``, ``competing_candidates``, ``resolution_status``) instead
of picking a winner. Conflicting sources are not flattened into one apparently
clean truth.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """Timestamps that come back from SQLite as UTC-aware as they went in.

    SQLite has no timezone type, so a naive value read back would silently mix
    with the aware values the clock produces and blow up the first time anything
    subtracts two dates. Everything in this system is UTC; this makes that true
    on the way out as well as on the way in.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class SourceFile(Base):
    """One supplied raw file, with the hash proving it was not modified."""

    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String, unique=True)
    file_format: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    byte_size: Mapped[int] = mapped_column(Integer)
    record_count: Mapped[int] = mapped_column(Integer)
    parsed_count: Mapped[int] = mapped_column(Integer)
    error_count: Mapped[int] = mapped_column(Integer)
    ingested_at: Mapped[datetime] = mapped_column(UtcDateTime)


class SourceRecord(Base):
    """One raw record, kept verbatim. Malformed records are stored, never dropped."""

    __tablename__ = "source_records"
    __table_args__ = (UniqueConstraint("filename", "row_index", name="uq_source_record"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"))
    filename: Mapped[str] = mapped_column(String, index=True)
    row_index: Mapped[int] = mapped_column(Integer)
    record_type: Mapped[str] = mapped_column(String, index=True)
    natural_key: Mapped[str] = mapped_column(String, default="")
    raw_json: Mapped[str] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String, default="ok")  # ok | error
    parse_error: Mapped[str] = mapped_column(Text, default="")


class Organization(Base):
    """A canonical account.

    Separate CRM account ids stay separate rows even when they share a domain:
    a shared domain buys them a ``domain_group`` for coordination and matching
    context, never a merge.
    """

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String, index=True)
    crm_account_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String)
    raw_name: Mapped[str] = mapped_column(String)
    normalized_name: Mapped[str] = mapped_column(String, index=True)
    domain: Mapped[str] = mapped_column(String, default="")
    domain_group: Mapped[str] = mapped_column(String, default="", index=True)
    is_crm_account: Mapped[bool] = mapped_column(Boolean, default=False)
    industry: Mapped[str] = mapped_column(String, default="")
    hq: Mapped[str] = mapped_column(String, default="")
    employee_count: Mapped[str] = mapped_column(String, default="")
    stage: Mapped[str] = mapped_column(String, default="")
    arr_potential_usd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crm_owner: Mapped[str] = mapped_column(String, default="")
    match_tier: Mapped[str] = mapped_column(String, default="")
    match_method: Mapped[str] = mapped_column(String, default="")
    match_evidence: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String, default="")
    competing_candidates: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String, default="resolved")  # resolved | needs_review
    source_type: Mapped[str] = mapped_column(String, default="historical_corpus")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)


class Person(Base):
    """A real individual supported by source evidence.

    Unresolved wording from a request ("VP of Security at Acme") never lands
    here — that is intent, and lives on :class:`RequestTarget`. Live operational
    input *can* create a person, with ``source_type='live_input'`` and the event
    that asserted them, but it goes through the same provenance requirements.
    """

    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_key: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)
    normalized_name: Mapped[str] = mapped_column(String, index=True)
    identity_basis: Mapped[str] = mapped_column(String)  # profile_url | name_only_export | internal_directory | live_input
    profile_url: Mapped[str] = mapped_column(String, default="")
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)
    source_type: Mapped[str] = mapped_column(String, default="historical_corpus")  # historical_corpus | live_input
    match_tier: Mapped[str] = mapped_column(String, default="")
    match_method: Mapped[str] = mapped_column(String, default="")
    match_evidence: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String, default="")
    competing_candidates: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String, default="resolved")
    raw_value: Mapped[str] = mapped_column(String, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)
    asserted_by_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("intro_events.id", use_alter=True, name="fk_persons_asserted_by_event"),
        nullable=True,
    )

    affiliations: Mapped[list["Affiliation"]] = relationship(back_populates="person")


class Affiliation(Base):
    """Person ↔ organization employment, with the precision of the date we have."""

    __tablename__ = "affiliations"
    __table_args__ = (UniqueConstraint("person_id", "organization_id", "title", name="uq_affiliation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    title: Mapped[str] = mapped_column(String, default="")
    title_family: Mapped[str] = mapped_column(String, default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_precision: Mapped[str] = mapped_column(String, default="unknown")  # day | year | unknown
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    match_method: Mapped[str] = mapped_column(String, default="")
    confidence: Mapped[str] = mapped_column(String, default="")
    raw_value: Mapped[str] = mapped_column(String, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)

    person: Mapped[Person] = relationship(back_populates="affiliations")


class Connector(Base):
    """Someone who may be able to help establish a route.

    A connector is never, by that fact alone, the owner of any request.
    Connectors observed in the data but absent from the managed roster are kept
    with ``on_roster=False`` and no stated capacity; that is a coverage gap in
    the operating model, not a defect in the person or the record.
    """

    __tablename__ = "connectors"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), unique=True)
    name: Mapped[str] = mapped_column(String)
    on_roster: Mapped[bool] = mapped_column(Boolean, default=False)
    connector_type: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="")
    focus_areas: Mapped[str] = mapped_column(String, default="")
    stated_monthly_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    observed_in: Mapped[str] = mapped_column(String, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)

    person: Mapped[Person] = relationship()


class RelationshipEdge(Base):
    """An observed relationship between a connector and a person or account.

    An edge is evidence that somebody may know somebody. It says nothing about
    whether an introduction can actually be made.
    """

    __tablename__ = "relationship_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    connector_id: Mapped[int] = mapped_column(ForeignKey("connectors.id"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"), nullable=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    edge_type: Mapped[str] = mapped_column(String)
    relationship_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_precision: Mapped[str] = mapped_column(String, default="unknown")  # day | year | unknown
    raw_value: Mapped[str] = mapped_column(String, default="")
    confidence: Mapped[str] = mapped_column(String, default="")
    source_file: Mapped[str] = mapped_column(String, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)


class IntroRequest(Base):
    """The spine: one ask for a warm introduction.

    Four roles are kept apart on purpose. ``requester_id`` is who asked.
    ``observed_owner_id`` is ownership actually evidenced in the historical
    record and is nullable — most of the corpus has none, and hiding that would
    make the old process look healthier than it was.
    ``operational_owner_id`` is who is accountable now and can never be null.
    ``selected_connector_id`` is a route, not an owner.
    """

    __tablename__ = "intro_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    origin: Mapped[str] = mapped_column(String, default="historical_corpus")  # historical_corpus | live_intake

    requester_id: Mapped[int] = mapped_column(ForeignKey("persons.id"))
    requester_role: Mapped[str] = mapped_column(String, default="")

    observed_owner_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"), nullable=True)
    observed_owner_evidence: Mapped[str] = mapped_column(Text, default="")
    operational_owner_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), nullable=False)
    operational_owner_source: Mapped[str] = mapped_column(String)  # observed_owner | fallback_requester |
    # configured_triage_owner | explicit_intake | manual_assignment
    was_ownerless_at_ingest: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Whether the corpus recorded *any* handling of this ask (an outcome row
    #: naming a connector who was asked). Distinct from ownership.
    had_recorded_handling: Mapped[bool] = mapped_column(Boolean, default=False)

    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    raw_ask: Mapped[str] = mapped_column(Text, default="")
    deal_value_usd: Mapped[int] = mapped_column(Integer, default=0)
    urgency: Mapped[str] = mapped_column(String, default="")

    declared_status: Mapped[str] = mapped_column(String, default="")
    declared_path_found_flag: Mapped[str] = mapped_column(String, default="")

    workflow_state: Mapped[str] = mapped_column(String, index=True)
    route_status: Mapped[str] = mapped_column(String, default="NONE")
    outcome: Mapped[str] = mapped_column(String, default="UNKNOWN")
    state_source: Mapped[str] = mapped_column(String, default="no_evidence")
    state_confidence: Mapped[str] = mapped_column(String, default="none")
    state_evidence: Mapped[str] = mapped_column(Text, default="")

    selected_connector_id: Mapped[int | None] = mapped_column(ForeignKey("connectors.id"), nullable=True)
    #: When a human confirmed that route. A confirmed route is an ask on that
    #: connector, so it counts towards their load exactly like a historical one.
    route_confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    next_action: Mapped[str] = mapped_column(String, default="")
    next_action_assigned_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    next_action_due_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    requested_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: When this request came under management by this system. For the legacy
    #: backlog this is the deterministic operationalization instant, not "now".
    operationalized_at: Mapped[datetime] = mapped_column(UtcDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    closure_reason: Mapped[str] = mapped_column(String, default="")

    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)

    target: Mapped["RequestTarget"] = relationship(back_populates="request", uselist=False)
    organization: Mapped[Organization | None] = relationship()
    requester: Mapped[Person] = relationship(foreign_keys=[requester_id])
    operational_owner: Mapped[Person] = relationship(foreign_keys=[operational_owner_id])
    observed_owner: Mapped[Person | None] = relationship(foreign_keys=[observed_owner_id])
    selected_connector: Mapped[Connector | None] = relationship()


class RequestTarget(Base):
    """Who the request is *trying* to reach — intent, not identity.

    ``resolved_person_id`` stays null until real evidence identifies an actual
    individual. "VP of Security at Acme" is a persona attached to Acme and
    resolves to nobody; that is a normal, actionable state, not an error.
    """

    __tablename__ = "request_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("intro_requests.id"), unique=True)
    raw_target_text: Mapped[str] = mapped_column(Text, default="")
    raw_target_name: Mapped[str] = mapped_column(String, default="")
    raw_target_title: Mapped[str] = mapped_column(String, default="")
    normalized_title_family: Mapped[str] = mapped_column(String, default="")
    raw_account_text: Mapped[str] = mapped_column(String, default="")
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    account_match_tier: Mapped[str] = mapped_column(String, default="")
    account_match_method: Mapped[str] = mapped_column(String, default="")
    account_match_evidence: Mapped[str] = mapped_column(Text, default="")
    account_candidate_matches: Mapped[str] = mapped_column(Text, default="")
    resolved_person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String, default="unresolved")  # unresolved | ambiguous | resolved
    resolution_method: Mapped[str] = mapped_column(String, default="")
    resolution_confidence: Mapped[str] = mapped_column(String, default="none")
    resolution_evidence: Mapped[str] = mapped_column(Text, default="")
    candidate_matches: Mapped[str] = mapped_column(Text, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)

    request: Mapped[IntroRequest] = relationship(back_populates="target")
    organization: Mapped[Organization | None] = relationship()
    resolved_person: Mapped[Person | None] = relationship()


class IntroCandidatePath(Base):
    """A lead worth investigating — never a claim that an intro is available.

    ``observability`` records what we can honestly say about *when* the
    relationship is known to have existed:

    * ``historically_observable`` — dated, and the date pre-dates the request;
    * ``snapshot_only`` — visible in the supplied snapshot, historical
      availability unknown;
    * ``post_dates_request`` — the relationship began after the ask.

    ``limitations`` is mandatory and non-empty: every path states what it does
    not prove.
    """

    __tablename__ = "intro_candidate_paths"
    __table_args__ = (
        UniqueConstraint("request_id", "connector_id", "relationship_edge_id", name="uq_candidate_path"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("intro_requests.id"), index=True)
    connector_id: Mapped[int] = mapped_column(ForeignKey("connectors.id"), index=True)
    relationship_edge_id: Mapped[int] = mapped_column(ForeignKey("relationship_edges.id"))
    hop_type: Mapped[str] = mapped_column(String)
    observability: Mapped[str] = mapped_column(String, index=True)
    connector_reachable: Mapped[bool] = mapped_column(Boolean, default=True)
    same_title_family: Mapped[bool] = mapped_column(Boolean, default=False)
    relationship_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[str] = mapped_column(String, default="low")
    #: unreviewed | selected | rejected — the record of a human route review.
    review_status: Mapped[str] = mapped_column(String, default="unreviewed", index=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String, default="")
    limitations: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text, default="")
    source_file: Mapped[str] = mapped_column(String, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)

    connector: Mapped[Connector] = relationship()
    edge: Mapped[RelationshipEdge] = relationship()


class IntroEvent(Base):
    """Append-only log of things that happened to a request."""

    __tablename__ = "intro_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("intro_requests.id"), index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime)
    actor: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    asserted_by: Mapped[str] = mapped_column(String, default="")  # source file, or "operator"
    confidence: Mapped[str] = mapped_column(String, default="")
    is_state_evidence: Mapped[bool] = mapped_column(Boolean, default=False)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)


class IntroOutcome(Base):
    """The recorded outcome facts for a request, exactly as the corpus states them."""

    __tablename__ = "intro_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("intro_requests.id"), unique=True)
    connector_id: Mapped[int | None] = mapped_column(ForeignKey("connectors.id"), nullable=True)
    connector_name: Mapped[str] = mapped_column(String, default="")
    asked_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    responded: Mapped[str] = mapped_column(String, default="")
    response_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    intro_sent: Mapped[str] = mapped_column(String, default="")
    intro_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    meeting_booked: Mapped[str] = mapped_column(String, default="")
    opportunity_created: Mapped[str] = mapped_column(String, default="")
    opportunity_value_usd: Mapped[str] = mapped_column(String, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)


class EntityMatch(Base):
    """Every match decision, including the ones that were rejected or left open."""

    __tablename__ = "entity_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[str] = mapped_column(String, index=True)  # account | person
    subject_value: Mapped[str] = mapped_column(String)
    subject_context: Mapped[str] = mapped_column(String, default="")
    tier: Mapped[str] = mapped_column(String, index=True)
    method: Mapped[str] = mapped_column(String, default="")
    evidence: Mapped[Text] = mapped_column(Text, default="")
    verdict: Mapped[str] = mapped_column(String)  # resolved | ambiguous | unmatched
    resolved_organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    resolved_person_id: Mapped[int | None] = mapped_column(ForeignKey("persons.id"), nullable=True)
    competing_candidates: Mapped[str] = mapped_column(Text, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)


class DataQualityIssue(Base):
    """A record that contradicts itself or another record."""

    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    check: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String, default="medium")
    subject: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[int | None] = mapped_column(ForeignKey("intro_requests.id"), nullable=True)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)


class CoverageGap(Base):
    """Something the operating model does not cover yet.

    Deliberately not a :class:`DataQualityIssue`: an observed connector who is
    missing from the managed roster is a gap in coverage, not a bad record and
    not an invalid person.
    """

    __tablename__ = "coverage_gaps"

    id: Mapped[int] = mapped_column(primary_key=True)
    gap_type: Mapped[str] = mapped_column(String, index=True)
    subject: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[Text] = mapped_column(Text, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)


class AccountCoordination(Base):
    """Related activity on the same account, typed by how related it actually is.

    ``same_canonical_account`` < ``same_title_family`` < ``same_target_person``
    < ``explicit_reask``. Only the strongest kinds mean "probably the same ask";
    two different targets at one account are parallel work to coordinate, not
    duplicates.
    """

    __tablename__ = "account_coordination"
    __table_args__ = (UniqueConstraint("request_id_a", "request_id_b", name="uq_account_coordination"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id_a: Mapped[int] = mapped_column(ForeignKey("intro_requests.id"), index=True)
    request_id_b: Mapped[int] = mapped_column(ForeignKey("intro_requests.id"), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    canonical_key: Mapped[str] = mapped_column(String, default="")
    relation_type: Mapped[str] = mapped_column(String, index=True)
    days_apart: Mapped[int | None] = mapped_column(Integer, nullable=True)
    within_window: Mapped[bool] = mapped_column(Boolean, default=False)
    same_requester: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str] = mapped_column(Text, default="")


class BuildMetadata(Base):
    """How this database was built, so any number can be traced to a run."""

    __tablename__ = "build_metadata"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
