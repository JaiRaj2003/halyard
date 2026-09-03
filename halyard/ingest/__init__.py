"""Rebuild the canonical database from ``data/raw/`` without touching it."""

from .pipeline import IngestReport, ingest

__all__ = ["IngestReport", "ingest"]
