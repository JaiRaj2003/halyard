"""The account view: everything Halyard observes about one target account.

CRM facts, who we appear to know there, what has already been asked, and what
the network actually covers. Coverage is stated as observed edges — never as a
claim that an introduction is available.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock
from ..config import Settings
from ..db.models import (
    Connector,
    CoverageGap,
    DataQualityIssue,
    IntroCandidatePath,
    IntroOutcome,
    IntroRequest,
    Person,
    RelationshipEdge,
)
from ..domain.states import SETTLED_STATES
from .requests import request_summary
from .search import account_detail

_POSITIVE = {"y", "yes", "true", "1"}


def _yes(value: str) -> bool:
    return value.strip().casefold() in _POSITIVE


def account_view(session: Session, settings: Settings, clock: Clock, account_id: int) -> dict | None:
    """Account detail plus its request activity, coverage and open questions."""
    detail = account_detail(session, account_id)
    if detail is None:
        return None
    now = clock.now()

    requests = session.scalars(
        select(IntroRequest).where(IntroRequest.organization_id == account_id).order_by(IntroRequest.request_id)
    ).all()
    settled = {state.value for state in SETTLED_STATES}
    summaries = [request_summary(request, now, settings) for request in requests]
    request_ids = [request.id for request in requests]

    edges = session.scalars(
        select(RelationshipEdge).where(RelationshipEdge.organization_id == account_id)
    ).all()
    connectors = {connector.id: connector for connector in session.scalars(select(Connector)).all()}
    people = {person.id: person for person in session.scalars(select(Person)).all()}

    coverage: dict[int, dict] = {}
    for edge in edges:
        connector = connectors.get(edge.connector_id)
        if connector is None:
            continue
        row = coverage.setdefault(
            connector.id,
            {
                "connector_id": connector.id,
                "connector": connector.name,
                "on_roster": connector.on_roster,
                "edge_count": 0,
                "named_contacts": [],
                "sources": [],
            },
        )
        row["edge_count"] += 1
        person = people.get(edge.person_id) if edge.person_id else None
        if person is not None and person.display_name not in row["named_contacts"]:
            row["named_contacts"].append(person.display_name)
        if edge.source_file and edge.source_file not in row["sources"]:
            row["sources"].append(edge.source_file)
    coverage_rows = sorted(coverage.values(), key=lambda row: (-row["edge_count"], row["connector"]))

    outcomes = (
        session.scalars(select(IntroOutcome).where(IntroOutcome.request_id.in_(request_ids))).all()
        if request_ids
        else []
    )
    by_request = {request.id: request for request in requests}
    prior_intros = [
        {
            "request_id": by_request[outcome.request_id].request_id,
            "connector": outcome.connector_name,
            "asked_date": outcome.asked_date,
            "intro_date": outcome.intro_date,
            "meeting_booked": _yes(outcome.meeting_booked),
            "opportunity_created": _yes(outcome.opportunity_created),
        }
        for outcome in outcomes
        if _yes(outcome.intro_sent) and outcome.request_id in by_request
    ]
    prior_intros.sort(key=lambda row: (row["intro_date"] is None, row["intro_date"], row["request_id"]))

    issues = (
        session.scalars(select(DataQualityIssue).where(DataQualityIssue.request_id.in_(request_ids))).all()
        if request_ids
        else []
    )
    gaps = session.scalars(select(CoverageGap).where(CoverageGap.subject.contains(detail["name"]))).all()

    observable_paths = (
        session.scalar(
            select(IntroCandidatePath)
            .where(
                IntroCandidatePath.request_id.in_(request_ids),
                IntroCandidatePath.observability == "historically_observable",
            )
            .limit(1)
        )
        if request_ids
        else None
    )

    return {
        **detail,
        "as_of": now,
        "active_requests": [row for row in summaries if row["workflow_state"] not in settled],
        "settled_requests": [row for row in summaries if row["workflow_state"] in settled],
        "request_count": len(summaries),
        "coverage": {
            "note": (
                "Observed relationship edges into this account. An edge is evidence about where to investigate, "
                "not an available introduction."
            ),
            "connector_count": len(coverage_rows),
            "edge_count": len(edges),
            "has_historically_observable_path": observable_paths is not None,
            "connectors": coverage_rows,
        },
        "prior_observed_introductions": prior_intros,
        "data_quality_issues": [
            {"check": issue.check, "severity": issue.severity, "subject": issue.subject, "detail": issue.detail}
            for issue in issues
        ],
        "coverage_gaps": [{"gap_type": gap.gap_type, "subject": gap.subject, "detail": gap.detail} for gap in gaps],
    }
