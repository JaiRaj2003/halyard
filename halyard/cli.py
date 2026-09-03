"""Command line entry points: ``ingest``, ``reset``, ``report``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .clock import get_clock
from .config import RAW_DIR, load_settings
from .db.session import build_engine
from .ingest import ingest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="halyard")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_parser = sub.add_parser("ingest", help="rebuild the database from data/raw/")
    ingest_parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ingest_parser.add_argument("--force", action="store_true", help="rebuild even if live requests exist")

    sub.add_parser("reset", help="delete the database file")
    sub.add_parser("report", help="print the ingestion reconciliation for the current database")

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "reset":
        if settings.db_path.exists():
            settings.db_path.unlink()
            print(f"removed {settings.db_path}")
        else:
            print(f"nothing to remove at {settings.db_path}")
        return 0

    if args.command == "ingest":
        engine = build_engine(settings.db_path)
        report = ingest(engine, args.raw_dir, settings=settings, clock=get_clock(), force=args.force)
        print(json.dumps(report.as_dict(), indent=2))
        return 0

    from .services.metrics import ingestion_snapshot

    engine = build_engine(settings.db_path)
    print(json.dumps(ingestion_snapshot(engine), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
