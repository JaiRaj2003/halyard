"""The organizational-relevance tie-breaker: vocabulary, tiers and blast radius.

The corpus cannot validate this factor — 96 requests carry candidate paths and
the whole corpus holds 17 distinct contact titles, none of them a CFO or a
Controller. So the tests here do two things: pin the tier vocabulary on the
out-of-sample shapes the product must handle live, and prove the factor cannot
overturn evidence, only ties.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from halyard.config import Settings
from halyard.db.models import IntroCandidatePath, IntroRequest
from halyard.ingest.paths import HISTORICALLY_OBSERVABLE, HOP_COLLEAGUE, HOP_DIRECT, SNAPSHOT_ONLY
from halyard.services.ranking import ConnectorContext, path_factors, rank_paths
from halyard.services.relevance import (
    ADJACENT_FUNCTION,
    SAME_FUNCTION,
    SENIOR_PEER,
    function_group,
    is_senior,
    relevance_tier,
)
from halyard.services.requests import candidate_path_payload

RELEVANCE_KEYS = ("relevance_same_function", "relevance_adjacent_function", "relevance_senior_peer")

NEUTRAL_CONTEXT = ConnectorContext(
    recent_asks=0,
    stated_monthly_capacity=4,
    prior_successful_intros=0,
    engaged_on_account=False,
)


def colleague_path(**kwargs) -> IntroCandidatePath:
    defaults = dict(
        hop_type=HOP_COLLEAGUE,
        observability=HISTORICALLY_OBSERVABLE,
        connector_reachable=True,
        same_title_family=False,
        relationship_date=date(2025, 1, 1),
        limitations="test",
    )
    defaults.update(kwargs)
    return IntroCandidatePath(**defaults)


def priority(target_title: str, contact_title: str, settings: Settings, **kwargs) -> int:
    factors = path_factors(
        colleague_path(**kwargs),
        NEUTRAL_CONTEXT,
        settings,
        target_title=target_title,
        known_contact_title=contact_title,
    )
    return sum(factor.weight for factor in factors)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Chief Financial Officer", "finance"),
        ("Controller", "finance"),
        ("Chief Information Security Officer", "security"),
        ("Chief Technology Officer", "technology"),
        ("Staff Engineer", "technology"),
        ("Chief Executive Officer", "executive"),
        ("", ""),
        ("Head of Innovation", ""),
    ],
)
def test_function_group(title, expected):
    assert function_group(title) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Chief Financial Officer", True),
        ("Controller", True),
        ("VP of Security", True),
        ("Director of Software Engineering", True),
        ("Engineering Manager", False),
        ("Staff Engineer", False),
        ("", False),
    ],
)
def test_is_senior(title, expected):
    assert is_senior(title) == expected


@pytest.mark.parametrize(
    "target,contact,expected",
    [
        # The three out-of-sample cases the corpus never contains.
        ("Chief Executive Officer", "Chief Financial Officer", ADJACENT_FUNCTION),
        ("Chief Executive Officer", "Engineering Manager", ""),
        ("Chief Information Security Officer", "Chief Technology Officer", ADJACENT_FUNCTION),
        ("Chief Information Security Officer", "Chief Information Officer", ADJACENT_FUNCTION),
        ("Chief Information Security Officer", "VP of Marketing", SENIOR_PEER),
        ("Chief Information Security Officer", "Software Engineer", ""),
        ("Chief Financial Officer", "Controller", SAME_FUNCTION),
        ("Chief Financial Officer", "Principal Engineer", ""),
        # Unknown or missing titles never produce a tier, in either position.
        ("", "Chief Financial Officer", ""),
        ("Chief Financial Officer", "", ""),
        ("Head of Innovation", "Chief Financial Officer", ""),
    ],
)
def test_relevance_tier(target, contact, expected):
    assert relevance_tier(target, contact) == expected


def test_tier_is_symmetric_in_adjacency():
    assert relevance_tier("Chief Technology Officer", "Chief Information Security Officer") == ADJACENT_FUNCTION
    assert relevance_tier("Chief Information Security Officer", "Chief Technology Officer") == ADJACENT_FUNCTION


def test_factor_fires_only_on_colleague_paths(settings):
    direct = path_factors(
        colleague_path(hop_type=HOP_DIRECT),
        NEUTRAL_CONTEXT,
        settings,
        target_title="Chief Financial Officer",
        known_contact_title="Controller",
    )
    assert not [factor for factor in direct if factor.key in RELEVANCE_KEYS]


def test_unrecognised_title_never_penalises(settings):
    """A title we cannot read costs nothing; it simply produces no factor."""
    unknown = priority("Chief Financial Officer", "Chief Wrangler of Widgets", settings)
    none_at_all = priority("Chief Financial Officer", "", settings)
    assert unknown == none_at_all


def test_relevance_orders_the_synthetic_cases(settings):
    """CFO over middle managers, CTO/CIO over unrelated, CFO over an IC for a CEO ask."""
    assert priority("Chief Financial Officer", "Controller", settings) > priority(
        "Chief Financial Officer", "Engineering Manager", settings
    )
    assert priority("Chief Information Security Officer", "Chief Technology Officer", settings) > priority(
        "Chief Information Security Officer", "Software Engineer", settings
    )
    assert priority("Chief Executive Officer", "Chief Financial Officer", settings) > priority(
        "Chief Executive Officer", "Staff Engineer", settings
    )


def test_relevance_never_outweighs_real_evidence(settings):
    """The most relevant contact still loses to dated, on-roster evidence."""
    relevant_but_undated = priority(
        "Chief Financial Officer", "Controller", settings, observability=SNAPSHOT_ONLY, relationship_date=None
    )
    irrelevant_but_dated = priority("Chief Financial Officer", "Staff Engineer", settings)
    assert irrelevant_but_dated > relevant_but_undated

    relevant_off_roster = priority("Chief Financial Officer", "Controller", settings, connector_reachable=False)
    assert irrelevant_but_dated > relevant_off_roster


def test_weights_stay_below_every_other_supporting_factor(settings):
    weights = settings.path_factor_weights
    ceiling = min(
        weights["colleague_at_account"],
        weights["same_title_family"],
        weights["corroborated_by_second_source"],
        weights["connector_on_roster"],
    )
    assert max(weights[key] for key in RELEVANCE_KEYS) < ceiling


def test_historical_resort_only_breaks_exact_ties(session, settings):
    """Across the corpus, no flip overturns a path that was ahead on evidence.

    This is the ship criterion the flip count cannot give: whatever the factor
    reorders, it reorders inside groups the ranker had already declared equal.
    """
    weights = dict(settings.path_factor_weights)
    for key in RELEVANCE_KEYS:
        weights[key] = 0
    baseline = replace(settings, path_factor_weights=weights)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    flips = 0
    for request in session.scalars(select(IntroRequest)).all():
        new = rank_paths(session, request, settings, now)
        old = rank_paths(session, request, baseline, now)
        if not new or new[0].path.id == old[0].path.id:
            continue
        flips += 1
        scores = {entry.path.id: entry.priority for entry in old}
        assert scores[new[0].path.id] == scores[old[0].path.id]
    assert flips, "the corpus should exercise the tie-break at least once"


def test_no_composite_score_reaches_the_payload(session, settings, clock):
    """The new factor is a sentence like every other one; the total stays internal."""
    request = session.scalars(select(IntroRequest)).first()
    ranked = rank_paths(session, request, settings, clock.now())
    for entry in ranked:
        for factor in entry.factors:
            assert factor.statement
            assert str(factor.weight) not in factor.statement


def test_candidate_path_payload_exposes_relevance_as_a_sentence(session, settings, clock):
    for request in session.scalars(select(IntroRequest)).all():
        payload = candidate_path_payload(session, request, settings, clock.now())
        for path in payload["paths"]:
            for factor in path["factors"]:
                assert set(factor) == {"key", "statement", "direction"}
                if factor["key"] in RELEVANCE_KEYS:
                    assert "Known contact" in factor["statement"]
