"""Shared fixtures.

The database is built once per test session from ``data/raw/`` with a fixed
operationalization instant and a fixed application clock, so every assertion in
the suite is about deterministic content rather than about the day it ran.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from halyard.api.app import create_app
from halyard.clock import FixedClock
from halyard.config import RAW_DIR, Settings
from halyard.db.session import build_engine, sessionmaker_for
from halyard.ingest import ingest

OPERATIONALIZED_AT = datetime(2026, 8, 10, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def raw_dir() -> Path:
    return RAW_DIR


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> Settings:
    return Settings(
        db_path=tmp_path_factory.mktemp("halyard") / "test.sqlite3",
        operationalization_at=OPERATIONALIZED_AT,
    )


@pytest.fixture(scope="session")
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture(scope="session")
def built(settings, raw_dir):
    engine = build_engine(settings.db_path)
    report = ingest(engine, raw_dir, settings=settings)
    return engine, report


@pytest.fixture(scope="session")
def engine(built):
    return built[0]


@pytest.fixture(scope="session")
def report(built):
    return built[1]


@pytest.fixture()
def session(engine):
    factory = sessionmaker_for(engine)
    db = factory()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture()
def api(tmp_path, settings, built, clock):
    """A throwaway copy of the built database per test, so writes never leak."""
    db_path = tmp_path / "api.sqlite3"
    shutil.copyfile(settings.db_path, db_path)

    def make(triage_owner_name: str | None = None) -> TestClient:
        test_settings = Settings(
            db_path=db_path,
            operationalization_at=OPERATIONALIZED_AT,
            triage_owner_name=triage_owner_name,
        )
        app = create_app(engine=build_engine(db_path), settings=test_settings, clock=clock)
        return TestClient(app)

    return make


@pytest.fixture()
def client(api):
    with api() as test_client:
        yield test_client
