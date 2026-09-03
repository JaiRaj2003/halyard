"""Product configuration.

Everything here is a **product default we chose**, not a finding from the
supplied data. The audit measured what happened historically; none of it
prescribes how quickly a next action ought to be done. Changing a number here
changes product behaviour and nothing else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .domain.states import WorkflowState

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
DERIVED_DIR = REPO_ROOT / "data" / "derived"
DEFAULT_DB_PATH = DERIVED_DIR / "halyard.sqlite3"

#: When the legacy backlog is taken under management by this system.
#:
#: Ingesting history *creates* new operational facts (a fallback owner, a triage
#: action, a due date). Stamping those with ``now()`` would make every rebuild
#: produce different content, so they are stamped with this deterministic,
#: configurable instant instead. Historical timestamps observed in the corpus are
#: never touched. Live requests use the application clock, not this value.
DEFAULT_OPERATIONALIZATION_AT = datetime(2026, 8, 10, tzinfo=timezone.utc)

OPERATIONALIZATION_ENV_VAR = "HALYARD_OPERATIONALIZATION_AT"
DB_PATH_ENV_VAR = "HALYARD_DB"
TRIAGE_OWNER_ENV_VAR = "HALYARD_TRIAGE_OWNER"

#: Next-action SLA, in days, by workflow state. Product configuration.
SLA_DAYS_BY_STATE: dict[WorkflowState, int] = {
    WorkflowState.NEEDS_TRIAGE: 2,
    WorkflowState.NEEDS_ENTITY_REVIEW: 2,
    WorkflowState.PATH_REVIEW: 2,
    WorkflowState.AWAITING_CONNECTOR: 5,
    WorkflowState.INTRO_SENT: 5,
    WorkflowState.NO_OBSERVABLE_PATH: 5,
    WorkflowState.BLOCKED: 5,
}


@dataclass(frozen=True)
class Settings:
    db_path: Path = DEFAULT_DB_PATH
    operationalization_at: datetime = DEFAULT_OPERATIONALIZATION_AT
    #: Person who owns newly intaken requests when no owner is supplied. When
    #: unset, ownership falls back to the requester — never to nobody.
    triage_owner_name: str | None = None
    #: A request with no activity for this long, and no settled state, is
    #: flagged for attention. Flagging never changes state or outcome.
    staleness_days: int = 30
    #: Window used to surface related activity on the same account.
    coordination_window_days: int = 90
    #: Rolling window for connector load.
    connector_load_window_days: int = 30
    sla_days_by_state: dict[WorkflowState, int] = field(default_factory=lambda: dict(SLA_DAYS_BY_STATE))

    def sla_due(self, state: WorkflowState, assigned_at: datetime) -> datetime | None:
        """Due date for a next action, measured from when it was assigned.

        Settled states owe nothing and therefore have no due date.
        """
        days = self.sla_days_by_state.get(state)
        return None if days is None else assigned_at + timedelta(days=days)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    environ = os.environ if env is None else env
    db = environ.get(DB_PATH_ENV_VAR, "").strip()
    operationalized = environ.get(OPERATIONALIZATION_ENV_VAR, "").strip()
    triage_owner = environ.get(TRIAGE_OWNER_ENV_VAR, "").strip()
    return Settings(
        db_path=Path(db) if db else DEFAULT_DB_PATH,
        operationalization_at=(
            datetime.fromisoformat(operationalized.replace("Z", "+00:00"))
            if operationalized
            else DEFAULT_OPERATIONALIZATION_AT
        ),
        triage_owner_name=triage_owner or None,
    )
