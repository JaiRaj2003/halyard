"""Three clocks, deliberately kept apart.

* **Application clock** — real wall time. Everything the running product
  computes (request age, overdue status, staleness, rolling connector load,
  30/60/90-day windows) reads this, so a request entered today is age ~0.
* **Test / demo clock** — a fixed instant, used *only* when ``HALYARD_AS_OF`` is
  explicitly set, so tests can assert on deterministic timestamps.
* **Audit clock** — the corpus as-of date (2026-08-10). It belongs to the
  forensic audit and to historical reproduction only; no application code path
  may default to it.

The application clock is always injected, never read from a global, so no module
can quietly reach for "now".
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Protocol

AUDIT_AS_OF = datetime(2026, 8, 10, tzinfo=timezone.utc)
"""Documented as-of date of the supplied corpus. Audit-only."""

AS_OF_ENV_VAR = "HALYARD_AS_OF"


class Clock(Protocol):
    def now(self) -> datetime:  # pragma: no cover - protocol
        ...


class SystemClock:
    """Real current time. The application default."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """A deterministic instant, for tests, demos and historical reproduction."""

    def __init__(self, instant: datetime):
        self._instant = instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._instant


def parse_as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def get_clock(env: dict[str, str] | None = None) -> Clock:
    """The application clock: real time unless ``HALYARD_AS_OF`` is explicitly set."""
    environ = os.environ if env is None else env
    override = environ.get(AS_OF_ENV_VAR, "").strip()
    if override:
        return FixedClock(parse_as_of(override))
    return SystemClock()


def audit_clock() -> Clock:
    """The historical audit clock. Never used to answer a live product question."""
    return FixedClock(AUDIT_AS_OF)
