"""Staging: every supplied record lands in the database verbatim, first.

Nothing is filtered out here. A row that cannot be parsed is stored with
``parse_status='error'`` and its error message, so the count of what was
supplied always reconciles with the count of what was loaded — the difference is
visible rather than silently discarded.

Raw files are opened read-only and hashed, so a rebuild can prove they were not
modified.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import SourceFile, SourceRecord

CONNECTION_FILES: dict[str, str] = {
    "Marcus Aldridge": "connections_aldridge.csv",
    "Tomás Beckett": "connections_beckett.csv",
    "Elena Duvall": "connections_duvall.csv",
    "Priya Raghunathan": "connections_raghunathan.csv",
    "Owen Trask": "connections_trask.csv",
    "Dana Whitfield": "connections_whitfield.csv",
}


@dataclass(frozen=True)
class SourceSpec:
    filename: str
    record_type: str
    key_fields: tuple[str, ...]
    required_fields: tuple[str, ...]


CSV_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec("intro_requests.csv", "intro_request", ("request_id",), ("request_id",)),
    SourceSpec("intro_outcomes.csv", "intro_outcome", ("request_id",), ("request_id",)),
    SourceSpec("crm_accounts.csv", "crm_account", ("account_id",), ("account_id", "account_name")),
    SourceSpec("connector_roster.csv", "connector_roster", ("name",), ("name",)),
    SourceSpec("investor_network.csv", "investor_network", ("person", "fund", "portfolio_company"), ("person",)),
) + tuple(
    SourceSpec(filename, "connection", ("name", "company", "profile_url"), ("name",))
    for filename in CONNECTION_FILES.values()
)

SLACK_FILE = "slack_threads.jsonl"

#: Files that are documentation rather than data, and are deliberately not parsed.
NON_DATA_FILES = {"BD Ops Takehome Assignment.docx"}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upsert_file(session: Session, **kwargs) -> SourceFile:
    existing = session.scalar(select(SourceFile).where(SourceFile.filename == kwargs["filename"]))
    if existing is None:
        existing = SourceFile(**kwargs)
        session.add(existing)
    else:
        for key, value in kwargs.items():
            setattr(existing, key, value)
    session.flush()
    return existing


def _upsert_record(session: Session, cache: dict[tuple[str, int], SourceRecord], **kwargs) -> SourceRecord:
    key = (kwargs["filename"], kwargs["row_index"])
    existing = cache.get(key)
    if existing is None:
        existing = session.scalar(
            select(SourceRecord).where(
                SourceRecord.filename == kwargs["filename"], SourceRecord.row_index == kwargs["row_index"]
            )
        )
    if existing is None:
        existing = SourceRecord(**kwargs)
        session.add(existing)
    else:
        for key_name, value in kwargs.items():
            setattr(existing, key_name, value)
    cache[key] = existing
    return existing


def stage_raw(session: Session, raw_dir: Path, ingested_at: datetime) -> dict[str, list[SourceRecord]]:
    """Load every raw file into ``source_files`` / ``source_records``.

    Returns the staged records grouped by filename, in file order.
    """
    cache: dict[tuple[str, int], SourceRecord] = {}
    staged: dict[str, list[SourceRecord]] = {}

    for spec in CSV_SOURCES:
        path = raw_dir / spec.filename
        rows: list[SourceRecord] = []
        errors = 0
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            source_file = _upsert_file(
                session,
                filename=spec.filename,
                file_format="csv",
                sha256=sha256_of(path),
                byte_size=path.stat().st_size,
                record_count=0,
                parsed_count=0,
                error_count=0,
                ingested_at=ingested_at,
            )
            for offset, row in enumerate(reader):
                row_index = offset + 2  # 1-based, header is line 1
                clean = {k: ("" if v is None else v.strip()) for k, v in row.items() if k is not None}
                missing = [field for field in spec.required_fields if not clean.get(field)]
                status = "ok" if not missing else "error"
                if missing:
                    errors += 1
                rows.append(
                    _upsert_record(
                        session,
                        cache,
                        source_file_id=source_file.id,
                        filename=spec.filename,
                        row_index=row_index,
                        record_type=spec.record_type,
                        natural_key="|".join(clean.get(field, "") for field in spec.key_fields),
                        raw_json=json.dumps(clean, ensure_ascii=False, sort_keys=True),
                        parse_status=status,
                        parse_error="" if not missing else f"missing required field(s): {', '.join(missing)}",
                    )
                )
        source_file.record_count = len(rows)
        source_file.parsed_count = len(rows) - errors
        source_file.error_count = errors
        staged[spec.filename] = rows

    staged[SLACK_FILE] = _stage_slack(session, raw_dir / SLACK_FILE, cache, ingested_at)
    session.flush()
    return staged


def _stage_slack(
    session: Session, path: Path, cache: dict[tuple[str, int], SourceRecord], ingested_at: datetime
) -> list[SourceRecord]:
    source_file = _upsert_file(
        session,
        filename=SLACK_FILE,
        file_format="jsonl",
        sha256=sha256_of(path),
        byte_size=path.stat().st_size,
        record_count=0,
        parsed_count=0,
        error_count=0,
        ingested_at=ingested_at,
    )
    rows: list[SourceRecord] = []
    errors = 0
    with path.open(encoding="utf-8") as handle:
        for offset, line in enumerate(handle):
            if not line.strip():
                continue
            row_index = offset + 1
            try:
                thread = json.loads(line)
                status, error, payload = "ok", "", line.strip()
                if not thread.get("request_id"):
                    status, error = "error", "thread has no request_id"
                    errors += 1
            except json.JSONDecodeError as exc:  # pragma: no cover - corpus parses cleanly
                status, error, payload = "error", f"invalid json: {exc}", line.strip()
                errors += 1
            rows.append(
                _upsert_record(
                    session,
                    cache,
                    source_file_id=source_file.id,
                    filename=SLACK_FILE,
                    row_index=row_index,
                    record_type="slack_thread",
                    natural_key=(thread.get("request_id", "") if status == "ok" else ""),
                    raw_json=payload,
                    parse_status=status,
                    parse_error=error,
                )
            )
    source_file.record_count = len(rows)
    source_file.parsed_count = len(rows) - errors
    source_file.error_count = errors
    return rows


def payload(record: SourceRecord) -> dict:
    return json.loads(record.raw_json)


def raw_file_inventory(raw_dir: Path) -> list[str]:
    return sorted(p.name for p in raw_dir.iterdir() if p.is_file())
