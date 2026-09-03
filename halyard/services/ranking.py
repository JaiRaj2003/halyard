"""Evidence-based investigation priority for candidate paths.

This decides **where to look first**. It is not relationship strength, not the
probability that an introduction happens, and not a success likelihood: nothing
in the supplied corpus supports any of those, and 0/200 historical requests have
a connector who knows the requested buyer directly.

The ordering is produced by summing integer weights held in
``Settings.path_factor_weights``, and the sum is deliberately not part of the
API payload. What the operator gets is the order, the sentence for every factor
that fired, and the limitations of each path — a number like "priority 75" would
imply a precision these heuristics do not have. Missing evidence simply means a
factor does not fire; nothing here fails or guesses when a signal is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import Connector, IntroCandidatePath, IntroOutcome, IntroRequest, RelationshipEdge
from ..domain.states import SETTLED_STATES
from ..ingest.paths import HISTORICALLY_OBSERVABLE, HOP_COLLEAGUE, HOP_DIRECT, POST_DATES_REQUEST, SNAPSHOT_ONLY

SUPPORTING = "supporting"
LIMITING = "limiting"
NEUTRAL = "neutral"


@dataclass(frozen=True)
class Factor:
    """One reason this path is more, or less, worth investigating first."""

    key: str
    statement: str
    weight: int
    direction: str


@dataclass(frozen=True)
class RankedPath:
    path: IntroCandidatePath
    rank: int
    factors: tuple[Factor, ...]
    #: Internal only. Never serialised into an API response.
    priority: int

    @property
    def recommended(self) -> bool:
        return self.rank == 1


@dataclass(frozen=True)
class ConnectorContext:
    """Everything about a connector's current situation that affects ordering."""

    recent_asks: int
    stated_monthly_capacity: int | None
    prior_successful_intros: int
    engaged_on_account: bool

    @property
    def over_capacity(self) -> bool:
        return self.stated_monthly_capacity is not None and self.recent_asks > self.stated_monthly_capacity


def _yes(value: str) -> bool:
    return value.strip().casefold() in {"y", "yes", "true", "1"}


def connector_contexts(
    session: Session,
    settings: Settings,
    now: datetime,
    account_id: int | None,
) -> dict[int, ConnectorContext]:
    """Recent load, track record and in-flight engagement, per connector."""
    window_start: date = (now - timedelta(days=settings.connector_load_window_days)).date()
    outcomes = session.scalars(select(IntroOutcome).where(IntroOutcome.connector_id.isnot(None))).all()
    requests = {request.id: request for request in session.scalars(select(IntroRequest)).all()}

    recent: dict[int, int] = {}
    successful: dict[int, int] = {}
    engaged: set[int] = set()
    for outcome in outcomes:
        connector_id = outcome.connector_id
        assert connector_id is not None
        if outcome.asked_date is not None and outcome.asked_date >= window_start:
            recent[connector_id] = recent.get(connector_id, 0) + 1
        if _yes(outcome.intro_sent) or _yes(outcome.meeting_booked):
            successful[connector_id] = successful.get(connector_id, 0) + 1
        request = requests.get(outcome.request_id)
        if (
            account_id is not None
            and request is not None
            and request.organization_id == account_id
            and request.workflow_state not in {state.value for state in SETTLED_STATES}
        ):
            engaged.add(connector_id)

    return {
        connector.id: ConnectorContext(
            recent_asks=recent.get(connector.id, 0),
            stated_monthly_capacity=connector.stated_monthly_capacity,
            prior_successful_intros=successful.get(connector.id, 0),
            engaged_on_account=connector.id in engaged,
        )
        for connector in session.scalars(select(Connector)).all()
    }


def _corroborating_sources(session: Session, path: IntroCandidatePath) -> int:
    """How many distinct source files show this connector knowing this subject."""
    edge = path.edge
    stmt = select(RelationshipEdge).where(RelationshipEdge.connector_id == path.connector_id)
    if edge.person_id is not None:
        stmt = stmt.where(RelationshipEdge.person_id == edge.person_id)
    elif edge.organization_id is not None:
        stmt = stmt.where(
            RelationshipEdge.organization_id == edge.organization_id,
            RelationshipEdge.person_id.is_(None),
        )
    else:  # pragma: no cover - an edge always has one subject
        return 1
    return len({other.source_file for other in session.scalars(stmt).all() if other.source_file})


def path_factors(
    path: IntroCandidatePath,
    context: ConnectorContext | None,
    settings: Settings,
    corroborating_sources: int = 1,
) -> tuple[Factor, ...]:
    """Every factor that fires for one path, in the order an operator reads them."""
    weights = settings.path_factor_weights
    factors: list[Factor] = []

    def add(key: str, statement: str, direction: str, weight: int | None = None) -> None:
        factors.append(
            Factor(
                key=key,
                statement=statement,
                weight=weights.get(key, 0) if weight is None else weight,
                direction=direction,
            )
        )

    if path.observability == HISTORICALLY_OBSERVABLE:
        add("historically_observable", "Relationship was observable before the request was made", SUPPORTING)
    elif path.observability == SNAPSHOT_ONLY:
        add("snapshot_only", "Relationship carries no date, so it has no recency signal", NEUTRAL)
    elif path.observability == POST_DATES_REQUEST:
        add("post_dates_request", "Relationship began after the request was made", LIMITING)

    if path.hop_type == HOP_DIRECT:
        add("direct_target_person", "Direct connection observed to the requested person", SUPPORTING)
    elif path.hop_type == HOP_COLLEAGUE:
        if path.same_title_family:
            add("same_title_family", "Connection is to someone in the requested function at the account", SUPPORTING)
        else:
            add("colleague_at_account", "Connection is to a colleague at the target account", SUPPORTING)
    else:
        add("investor_relationship", "Investor or board relationship to the account", SUPPORTING)

    if path.hop_type != HOP_DIRECT:
        factors.append(
            Factor(
                key="no_direct_buyer_relationship",
                statement="No direct relationship to the requested buyer is verified",
                weight=0,
                direction=LIMITING,
            )
        )

    if path.connector_reachable:
        add("connector_on_roster", "Connector is on the managed roster", SUPPORTING)
    else:
        add("connector_off_roster", "Connector is not on the managed roster, so capacity is unknown", LIMITING)

    if corroborating_sources > 1:
        add(
            "corroborated_by_second_source",
            f"Supported by {corroborating_sources} independent sources",
            SUPPORTING,
        )

    if context is None:
        return tuple(factors)

    if context.prior_successful_intros:
        add(
            "connector_prior_successful_intro",
            f"Connector has {context.prior_successful_intros} observed successful introduction(s)",
            SUPPORTING,
        )
    if context.over_capacity:
        add(
            "connector_over_stated_capacity",
            f"Connector is above stated capacity of {context.stated_monthly_capacity} a month",
            LIMITING,
        )
    if context.recent_asks:
        penalty = max(
            weights.get("connector_recent_ask", 0) * context.recent_asks,
            settings.max_recent_ask_penalty,
        )
        add(
            "connector_recent_ask",
            f"Connector was asked {context.recent_asks} time(s) in the last "
            f"{settings.connector_load_window_days} days",
            LIMITING,
            weight=penalty,
        )
    if context.engaged_on_account:
        add(
            "connector_already_engaged_on_account",
            "Connector is already engaged on another live request at this account",
            LIMITING,
        )
    return tuple(factors)


def rank_paths(
    session: Session,
    request: IntroRequest,
    settings: Settings,
    now: datetime,
) -> list[RankedPath]:
    """Candidate paths in investigation order. Ties break on a stable key."""
    paths = session.scalars(
        select(IntroCandidatePath).where(IntroCandidatePath.request_id == request.id)
    ).all()
    if not paths:
        return []
    contexts = connector_contexts(session, settings, now, request.organization_id)

    scored: list[tuple[int, str, int, IntroCandidatePath, tuple[Factor, ...]]] = []
    for path in paths:
        factors = path_factors(
            path,
            contexts.get(path.connector_id),
            settings,
            corroborating_sources=_corroborating_sources(session, path),
        )
        priority = sum(factor.weight for factor in factors)
        scored.append((priority, path.connector.name, path.id, path, factors))

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [
        RankedPath(path=path, rank=index, factors=factors, priority=priority)
        for index, (priority, _name, _pid, path, factors) in enumerate(scored, start=1)
    ]


def factor_payload(factor: Factor) -> dict:
    """UI shape: the sentence and its direction. The weight stays internal."""
    return {"key": factor.key, "statement": factor.statement, "direction": factor.direction}


__all__ = [
    "ConnectorContext",
    "Factor",
    "RankedPath",
    "connector_contexts",
    "factor_payload",
    "path_factors",
    "rank_paths",
]
