"""Ingestion: every source parsed, nothing dropped, reruns idempotent."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import func, select

from halyard.db.models import (
    Affiliation,
    Connector,
    CoverageGap,
    IntroOutcome,
    IntroRequest,
    Organization,
    Person,
    RelationshipEdge,
    RequestTarget,
    SourceFile,
    SourceRecord,
)
from halyard.ingest import ingest
from halyard.ingest.raw import CSV_SOURCES, SLACK_FILE

EXPECTED_ROWS = {
    "intro_requests.csv": 200,
    "intro_outcomes.csv": 85,
    "crm_accounts.csv": 50,
    "connector_roster.csv": 6,
    "investor_network.csv": 73,
    SLACK_FILE: 200,
}


def test_every_supplied_file_is_accounted_for(session, raw_dir, report):
    on_disk = {path.name for path in raw_dir.iterdir() if path.is_file()}
    parsed = {row.filename for row in session.scalars(select(SourceFile)).all()}
    assert on_disk == parsed | set(report.unparsed_files)
    assert report.unparsed_files == [".gitkeep", "BD Ops Takehome Assignment.docx"]


def test_per_source_parsers_produce_the_expected_row_counts(session):
    for filename, expected in EXPECTED_ROWS.items():
        count = session.scalar(
            select(func.count()).select_from(SourceRecord).where(SourceRecord.filename == filename)
        )
        assert count == expected, filename


def test_connection_exports_parse_all_rows(session):
    count = session.scalar(
        select(func.count()).select_from(SourceRecord).where(SourceRecord.filename.like("connections_%"))
    )
    assert count == 5075


def test_raw_files_are_hashed_and_unmodified(session, raw_dir):
    for source_file in session.scalars(select(SourceFile)).all():
        digest = hashlib.sha256((raw_dir / source_file.filename).read_bytes()).hexdigest()
        assert digest == source_file.sha256


def test_raw_payloads_are_preserved_verbatim(session):
    record = session.scalar(
        select(SourceRecord)
        .where(SourceRecord.filename == "intro_requests.csv")
        .order_by(SourceRecord.row_index)
    )
    assert record.row_index == 2, "row indices are file line numbers, so a record traces back to a line"
    payload = json.loads(record.raw_json)
    assert payload["request_id"]
    assert record.parse_status == "ok"


def test_source_counts_reconcile_to_canonical_records(report):
    checks = {row["check"]: row for row in report.reconciliation}
    for name in ("requests_in_spine", "outcome_rows", "crm_accounts", "roster_connectors",
                 "connection_export_rows", "slack_threads", "slack_messages_classified"):
        assert checks[name]["supplied"] == checks[name]["canonical"], name


def test_spine_is_the_denominator(session):
    assert session.scalar(select(func.count()).select_from(IntroRequest)) == 200
    assert session.scalar(select(func.count()).select_from(RequestTarget)) == 200
    assert session.scalar(select(func.count()).select_from(IntroOutcome)) == 85


def test_crm_accounts_are_never_collapsed_by_shared_domain(session):
    crm = session.scalars(select(Organization).where(Organization.is_crm_account.is_(True))).all()
    assert len(crm) == 50
    assert len({org.crm_account_id for org in crm}) == 50
    grouped = [org for org in crm if org.domain_group]
    assert grouped, "the corpus contains shared-domain accounts"
    for org in grouped:
        siblings = [other for other in crm if other.domain_group == org.domain_group]
        assert len(siblings) > 1
        assert len({sibling.id for sibling in siblings}) == len(siblings)


def test_off_roster_connectors_are_a_coverage_gap_not_a_defect(session):
    off_roster = session.scalars(select(Connector).where(Connector.on_roster.is_(False))).all()
    assert off_roster
    for connector in off_roster:
        assert connector.stated_monthly_capacity is None
        assert connector.observed_in
    gaps = session.scalars(select(CoverageGap).where(CoverageGap.gap_type == "connector_not_on_roster")).all()
    assert len(gaps) == len(off_roster)


def test_rerunning_ingestion_does_not_duplicate_anything(engine, raw_dir, settings, report):
    second = ingest(engine, raw_dir, settings=settings)
    assert second.canonical_counts == report.canonical_counts
    assert second.reconciliation == report.reconciliation
    with engine.connect() as connection:
        duplicates = connection.execute(
            select(SourceRecord.filename, SourceRecord.row_index, func.count())
            .group_by(SourceRecord.filename, SourceRecord.row_index)
            .having(func.count() > 1)
        ).all()
    assert duplicates == []


def test_ingestion_is_deterministic_across_rebuilds(report):
    """Operational facts created at ingest are stamped with a fixed instant."""
    assert report.operationalization_at.isoformat() == "2026-08-10T00:00:00+00:00"


def test_entities_carry_provenance(session):
    for model in (Organization, Person, Affiliation, RelationshipEdge):
        row = session.scalars(select(model).limit(1)).one()
        assert row.source_record_id is not None
    person = session.scalars(select(Person).where(Person.profile_url != "").limit(1)).one()
    assert person.identity_basis == "profile_url"
    assert person.match_evidence


def test_csv_specs_cover_every_tabular_source(raw_dir):
    specs = {spec.filename for spec in CSV_SOURCES}
    on_disk = {path.name for path in raw_dir.glob("*.csv")}
    assert specs == on_disk
