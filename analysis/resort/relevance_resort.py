"""Re-sort every historical request with and without the relevance factor.

Answers two questions that a flip count alone cannot:

1. **Does the factor disturb the historical ordering, and where it does, is the
   new first choice defensible?** Every changed first choice is printed with
   both paths and the titles behind them, so a human judges each one.
2. **Does it do the thing it was built for on requests the corpus never
   contained?** The synthetic block ranks hand-built colleague paths for a CEO,
   a CISO and a CFO ask — the out-of-sample case the product actually has to
   handle. The corpus holds only a handful of distinct contact titles, so zero
   historical flips would say nothing about live behaviour either way.

Run: ``python -m analysis.resort.relevance_resort``. It builds its own database
from ``data/raw/`` with the fixed operationalization instant, so the output is
deterministic and independent of any local ``make ingest`` state.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from halyard.config import RAW_DIR, Settings
from halyard.db.models import IntroCandidatePath, IntroRequest, Person
from halyard.db.session import build_engine, sessionmaker_for
from halyard.ingest import ingest
from halyard.ingest.paths import HISTORICALLY_OBSERVABLE, HOP_COLLEAGUE
from halyard.services.ranking import ConnectorContext, contact_title, path_factors, rank_paths
from halyard.services.relevance import relevance_tier

OPERATIONALIZED_AT = datetime(2026, 8, 10, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
RELEVANCE_KEYS = ("relevance_same_function", "relevance_adjacent_function", "relevance_senior_peer")


def without_relevance(settings: Settings) -> Settings:
    weights = dict(settings.path_factor_weights)
    for key in RELEVANCE_KEYS:
        weights[key] = 0
    return replace(settings, path_factor_weights=weights)


def _describe(session, path: IntroCandidatePath, target_title: str) -> str:
    title = contact_title(session, path)
    tier = relevance_tier(target_title, title) or "none"
    return f"{path.connector.name} -> {title or 'title unrecorded'} [{path.hop_type}, relevance={tier}]"


def historical_resort(session, settings: Settings) -> None:
    baseline = without_relevance(settings)
    flips: list[str] = []
    reordered: list[str] = []
    tier_counts: dict[str, int] = {}
    margins: list[int] = []
    considered = 0

    requests = session.scalars(select(IntroRequest).order_by(IntroRequest.request_id)).all()
    for request in requests:
        target_title = request.target.raw_target_title if request.target is not None else ""
        new = rank_paths(session, request, settings, NOW)
        old = rank_paths(session, request, baseline, NOW)
        if not new:
            continue
        considered += 1
        for entry in new:
            for factor in entry.factors:
                if factor.key in RELEVANCE_KEYS:
                    tier_counts[factor.key] = tier_counts.get(factor.key, 0) + 1
        new_order = [entry.path.id for entry in new]
        old_order = [entry.path.id for entry in old]
        if new_order == old_order:
            continue
        reordered.append(request.request_id)
        if new_order[0] != old_order[0]:
            baseline_scores = {entry.path.id: entry.priority for entry in old}
            margin = baseline_scores[old_order[0]] - baseline_scores[new_order[0]]
            margins.append(margin)
            flips.append(
                f"{request.request_id}  target={target_title or 'persona unrecorded'}\n"
                f"    was: {_describe(session, old[0].path, target_title)}\n"
                f"    now: {_describe(session, new[0].path, target_title)}\n"
                f"    the two were {margin} point(s) apart before the factor was added"
            )

    print("HISTORICAL CORPUS RESORT")
    print(f"  requests with candidate paths ........ {considered}")
    for key in RELEVANCE_KEYS:
        print(f"  paths firing {key:32} {tier_counts.get(key, 0)}")
    print(f"  requests with any order change ....... {len(reordered)}")
    print(f"  requests whose first choice changed .. {len(flips)}")
    if margins:
        print(f"  largest pre-existing gap overturned .. {max(margins)} point(s)")
    for flip in flips:
        print(f"\n  {flip}")

    titles: dict[str, int] = {}
    for path in session.scalars(select(IntroCandidatePath)).all():
        person = session.get(Person, path.edge.person_id) if path.edge.person_id else None
        title = next((a.title for a in person.affiliations if a.title), "") if person else ""
        titles[title or "(no named contact)"] = titles.get(title or "(no named contact)", 0) + 1
    print("\n  known-contact titles behind every candidate path in the corpus:")
    for title, count in sorted(titles.items(), key=lambda item: (-item[1], item[0])):
        print(f"    {count:5}  {title}")


# --- Out-of-sample cases -------------------------------------------------
#
# Built in memory, not persisted: these are the shapes a live request takes that
# the corpus never contains. Each case ranks colleague paths that are identical
# in every respect the ranker already sees — same observability, same roster
# status, same load — so any ordering difference is the relevance factor alone.

SYNTHETIC_CASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("CEO ask", "Chief Executive Officer", ("Chief Financial Officer", "Engineering Manager", "Staff Engineer")),
    ("CISO ask", "Chief Information Security Officer", ("Chief Technology Officer", "Chief Information Officer",
                                                        "VP of Marketing", "Software Engineer")),
    ("CFO ask", "Chief Financial Officer", ("Controller", "Engineering Manager", "Principal Engineer")),
)

NEUTRAL_CONTEXT = ConnectorContext(
    recent_asks=0,
    stated_monthly_capacity=4,
    prior_successful_intros=0,
    engaged_on_account=False,
)


def synthetic_cases(settings: Settings) -> None:
    baseline = without_relevance(settings)
    print("\nOUT-OF-SAMPLE SYNTHETIC CASES (identical paths but for the contact's title)")
    for name, target_title, contacts in SYNTHETIC_CASES:
        path = IntroCandidatePath(
            hop_type=HOP_COLLEAGUE,
            observability=HISTORICALLY_OBSERVABLE,
            connector_reachable=True,
            same_title_family=False,
            relationship_date=date(2025, 1, 1),
            limitations="synthetic",
        )
        rows = []
        for contact in contacts:
            with_factor = sum(
                factor.weight
                for factor in path_factors(
                    path, NEUTRAL_CONTEXT, settings, target_title=target_title, known_contact_title=contact
                )
            )
            without = sum(
                factor.weight
                for factor in path_factors(
                    path, NEUTRAL_CONTEXT, baseline, target_title=target_title, known_contact_title=contact
                )
            )
            rows.append((with_factor, contact, relevance_tier(target_title, contact) or "none", without))
        print(f"\n  {name} — target: {target_title}")
        print("    before (no factor):  " + ", ".join(f"{c}" for _, c, _, _ in rows) + "  [tied — arbitrary order]")
        ordered = sorted(rows, key=lambda row: (-row[0], row[1]))
        print("    after  (with factor):")
        for position, (_score, contact, tier, _without) in enumerate(ordered, start=1):
            print(f"      {position}. {contact:36} relevance={tier}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            db_path=Path(tmp) / "resort.sqlite3",
            operationalization_at=OPERATIONALIZED_AT,
        )
        engine = build_engine(settings.db_path)
        ingest(engine, RAW_DIR, settings=settings)
        session = sessionmaker_for(engine)()
        try:
            historical_resort(session, settings)
        finally:
            session.close()
        synthetic_cases(settings)


if __name__ == "__main__":
    main()
