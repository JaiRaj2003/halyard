"""Clean, deterministic rebuild of the database from ``data/raw/``.

Determinism matters more than it looks: ingesting history *creates* operational
facts that the corpus never had (a fallback owner, a triage action, a due date).
Those are stamped with ``settings.operationalization_at``, not with ``now()``, so
two rebuilds a week apart produce identical content. Only live requests use the
application clock.

Re-running is safe: the corpus-derived schema is rebuilt wholesale, so nothing
accumulates. Rebuilding a database that already contains live requests would
throw them away, so it refuses unless explicitly forced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ..clock import Clock, SystemClock
from ..config import Settings, load_settings
from ..db.models import (
    AccountCoordination,
    Affiliation,
    Base,
    BuildMetadata,
    Connector,
    CoverageGap,
    DataQualityIssue,
    EntityMatch,
    IntroCandidatePath,
    IntroEvent,
    IntroOutcome,
    IntroRequest,
    Organization,
    Person,
    RelationshipEdge,
    RequestTarget,
    SourceFile,
    SourceRecord,
)
from ..db.session import sessionmaker_for
from .coordination import build_coordination
from .entities import build_entities
from .paths import build_candidate_paths
from .quality import check_contradictions
from .raw import NON_DATA_FILES, SLACK_FILE, raw_file_inventory, stage_raw
from .requests import build_requests, finalize_route_signals, finalize_unevidenced_states


class LiveDataPresent(RuntimeError):
    """Raised rather than destroy operational data during a rebuild."""


@dataclass
class IngestReport:
    operationalization_at: datetime
    files: list[dict] = field(default_factory=list)
    canonical_counts: dict[str, int] = field(default_factory=dict)
    reconciliation: list[dict] = field(default_factory=list)
    unparsed_files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "operationalization_at": self.operationalization_at.isoformat(),
            "files": self.files,
            "canonical_counts": self.canonical_counts,
            "reconciliation": self.reconciliation,
            "unparsed_files": self.unparsed_files,
        }


COUNTED_TABLES = {
    "source_files": SourceFile,
    "source_records": SourceRecord,
    "organizations": Organization,
    "persons": Person,
    "affiliations": Affiliation,
    "connectors": Connector,
    "relationship_edges": RelationshipEdge,
    "intro_requests": IntroRequest,
    "request_targets": RequestTarget,
    "intro_candidate_paths": IntroCandidatePath,
    "intro_events": IntroEvent,
    "intro_outcomes": IntroOutcome,
    "entity_matches": EntityMatch,
    "data_quality_issues": DataQualityIssue,
    "coverage_gaps": CoverageGap,
    "account_coordination": AccountCoordination,
}


def ingest(
    engine: Engine,
    raw_dir: Path,
    settings: Settings | None = None,
    clock: Clock | None = None,
    force: bool = False,
) -> IngestReport:
    settings = settings or load_settings()
    clock = clock or SystemClock()
    _guard_live_data(engine, force)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    session = sessionmaker_for(engine)()
    try:
        staged = stage_raw(session, raw_dir, ingested_at=settings.operationalization_at)
        index = build_entities(session, staged)
        requests = build_requests(session, staged, index, settings)
        path_counts = build_candidate_paths(session, requests)
        finalize_unevidenced_states(session, requests, path_counts, settings)
        finalize_route_signals(session, requests, path_counts)
        build_coordination(session, requests, settings)
        check_contradictions(session, requests)

        report = _report(session, staged, raw_dir, settings)
        session.add_all(
            [
                BuildMetadata(key="operationalization_at", value=settings.operationalization_at.isoformat()),
                BuildMetadata(key="ingested_at", value=clock.now().isoformat()),
                BuildMetadata(key="raw_dir", value=str(raw_dir)),
                BuildMetadata(key="staleness_days", value=str(settings.staleness_days)),
            ]
        )
        session.commit()
        return report
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _guard_live_data(engine: Engine, force: bool) -> None:
    inspector_tables = Base.metadata.tables
    if "intro_requests" not in inspector_tables:  # pragma: no cover - schema is static
        return
    try:
        with sessionmaker_for(engine)() as session:
            live = session.scalar(
                select(func.count()).select_from(IntroRequest).where(IntroRequest.origin == "live_intake")
            )
    except Exception:
        return
    if live and not force:
        raise LiveDataPresent(
            f"{live} live request(s) exist in this database; a rebuild would discard them. "
            "Point HALYARD_DB at a fresh file, or pass force=True if that is what you want."
        )


def _report(session: Session, staged: dict, raw_dir: Path, settings: Settings) -> IngestReport:
    report = IngestReport(operationalization_at=settings.operationalization_at)
    for source_file in session.scalars(select(SourceFile).order_by(SourceFile.filename)).all():
        report.files.append(
            {
                "filename": source_file.filename,
                "sha256": source_file.sha256,
                "records_supplied": source_file.record_count,
                "records_parsed": source_file.parsed_count,
                "records_with_errors": source_file.error_count,
            }
        )
    supplied = set(raw_file_inventory(raw_dir))
    parsed = {source_file.filename for source_file in session.scalars(select(SourceFile)).all()}
    report.unparsed_files = sorted(supplied - parsed)

    for name, model in COUNTED_TABLES.items():
        report.canonical_counts[name] = int(session.scalar(select(func.count()).select_from(model)) or 0)

    slack_messages = int(
        session.scalar(
            select(func.count()).select_from(IntroEvent).where(IntroEvent.event_type.like("slack:%"))
        )
        or 0
    )
    report.reconciliation = [
        {
            "check": "requests_in_spine",
            "supplied": len(staged["intro_requests.csv"]),
            "canonical": report.canonical_counts["intro_requests"],
        },
        {
            "check": "outcome_rows",
            "supplied": len(staged["intro_outcomes.csv"]),
            "canonical": report.canonical_counts["intro_outcomes"],
        },
        {
            "check": "crm_accounts",
            "supplied": len(staged["crm_accounts.csv"]),
            "canonical": int(
                session.scalar(
                    select(func.count()).select_from(Organization).where(Organization.is_crm_account.is_(True))
                )
                or 0
            ),
        },
        {
            "check": "roster_connectors",
            "supplied": len(staged["connector_roster.csv"]),
            "canonical": int(
                session.scalar(select(func.count()).select_from(Connector).where(Connector.on_roster.is_(True))) or 0
            ),
        },
        {
            "check": "connection_export_rows",
            "supplied": sum(len(rows) for name, rows in staged.items() if name.startswith("connections_")),
            "canonical": int(
                session.scalar(
                    select(func.count())
                    .select_from(RelationshipEdge)
                    .where(RelationshipEdge.edge_type == "connection_export")
                )
                or 0
            ),
        },
        {
            "check": "slack_threads",
            "supplied": len(staged[SLACK_FILE]),
            "canonical": int(
                session.scalar(
                    select(func.count(func.distinct(IntroEvent.request_id))).where(
                        IntroEvent.asserted_by == SLACK_FILE
                    )
                )
                or 0
            ),
        },
        {
            "check": "slack_messages_classified",
            "supplied": sum(len(_messages(record)) for record in staged[SLACK_FILE]),
            "canonical": slack_messages,
        },
        {
            "check": "non_data_files_not_parsed",
            "supplied": len(NON_DATA_FILES & supplied),
            "canonical": len(NON_DATA_FILES & set(report.unparsed_files)),
        },
    ]
    return report


def _messages(record: SourceRecord) -> list:
    import json

    if record.parse_status != "ok":
        return []
    return json.loads(record.raw_json).get("messages", [])
