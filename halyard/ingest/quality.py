"""Contradictions between sources, recorded rather than resolved.

Where two sources disagree the disagreement itself is the finding: the record
keeps both readings and says which fields conflict. Nothing here silently picks
a winner.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import DataQualityIssue, IntroCandidatePath, IntroOutcome, IntroRequest, SourceRecord
from .paths import HISTORICALLY_OBSERVABLE
from .raw import payload

NO_PATH_STATUSES = {"closed - no path", "no path found", "closed no path"}


def check_contradictions(session: Session, requests: dict[str, IntroRequest]) -> int:
    issues = 0
    observable = {
        request_id
        for (request_id,) in session.execute(
            select(IntroCandidatePath.request_id).where(IntroCandidatePath.observability == HISTORICALLY_OBSERVABLE)
        ).all()
    }
    outcomes = {outcome.request_id: outcome for outcome in session.scalars(select(IntroOutcome)).all()}

    for request in requests.values():
        declared = (request.declared_status or "").casefold()
        flag = (request.declared_path_found_flag or "").casefold()
        outcome = outcomes.get(request.id)

        if declared in NO_PATH_STATUSES and request.id in observable:
            issues += _add(
                session,
                request,
                "declared_no_path_contradicted_by_observable_path",
                f"status is '{request.declared_status}' but at least one relationship pre-dating the request exists",
            )
        if flag in {"n", "no", "unknown"} and request.id in observable:
            issues += _add(
                session,
                request,
                "path_found_flag_contradicted_by_observable_path",
                f"path_found_flag='{request.declared_path_found_flag}' but a pre-dating relationship exists",
            )
        if "intro sent" in declared and not (outcome and outcome.intro_sent == "Y"):
            issues += _add(
                session,
                request,
                "declared_intro_sent_without_outcome_evidence",
                f"status is '{request.declared_status}' but no outcome row records intro_sent=Y",
            )
        if outcome and outcome.intro_sent == "Y" and declared in {"open", "new"}:
            issues += _add(
                session,
                request,
                "outcome_ahead_of_declared_status",
                f"outcome records intro_sent=Y while the request status is still '{request.declared_status}'",
            )
        if outcome and outcome.meeting_booked == "Y" and outcome.intro_sent != "Y":
            issues += _add(
                session,
                request,
                "meeting_without_intro",
                "outcome records a meeting but no introduction",
            )

    spine = set(requests)
    for record in session.scalars(
        select(SourceRecord).where(SourceRecord.record_type == "intro_outcome")
    ).all():
        request_id = payload(record).get("request_id", "")
        if request_id and request_id not in spine:
            session.add(
                DataQualityIssue(
                    check="outcome_row_outside_request_spine",
                    severity="high",
                    subject=request_id,
                    detail="intro_outcomes references a request_id that is not in intro_requests.csv",
                    source_record_id=record.id,
                )
            )
            issues += 1

    duplicates = session.execute(
        select(SourceRecord.natural_key, func.count())
        .where(SourceRecord.record_type == "intro_outcome")
        .group_by(SourceRecord.natural_key)
        .having(func.count() > 1)
    ).all()
    for natural_key, count in duplicates:
        session.add(
            DataQualityIssue(
                check="duplicate_outcome_rows",
                severity="high",
                subject=natural_key,
                detail=f"{count} outcome rows exist for one request",
            )
        )
        issues += 1

    session.flush()
    return issues


def _add(session: Session, request: IntroRequest, check: str, detail: str) -> int:
    session.add(
        DataQualityIssue(
            check=check,
            severity="medium",
            subject=request.request_id,
            detail=detail,
            request_id=request.id,
            source_record_id=request.source_record_id,
        )
    )
    return 1
