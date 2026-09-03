"""Every ranking factor, one at a time, plus the ordering they produce.

The unit tests build unsaved ``IntroCandidatePath`` rows so a factor can be
isolated from the corpus; the ordering tests run against the real ingested data.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from halyard.config import Settings
from halyard.db.models import Connector, IntroCandidatePath, IntroRequest
from halyard.ingest.paths import (
    HISTORICALLY_OBSERVABLE,
    HOP_COLLEAGUE,
    HOP_DIRECT,
    HOP_INVESTOR,
    POST_DATES_REQUEST,
    SNAPSHOT_ONLY,
)
from halyard.services.ranking import ConnectorContext, connector_contexts, path_factors, rank_paths
from halyard.services.requests import candidate_path_payload


def make_path(**kwargs) -> IntroCandidatePath:
    defaults = dict(
        hop_type=HOP_COLLEAGUE,
        observability=SNAPSHOT_ONLY,
        connector_reachable=True,
        same_title_family=False,
        limitations="test",
    )
    defaults.update(kwargs)
    return IntroCandidatePath(**defaults)


def keys(path, context=None, settings=None, sources=1) -> list[str]:
    factors = path_factors(path, context, settings or Settings(), corroborating_sources=sources)
    return [factor.key for factor in factors]


def weight_of(path, key, context=None, settings=None, sources=1) -> int:
    factors = path_factors(path, context, settings or Settings(), corroborating_sources=sources)
    return next(factor.weight for factor in factors if factor.key == key)


def test_historically_observable_beats_snapshot_only_beats_post_dating():
    settings = Settings()
    before = weight_of(make_path(observability=HISTORICALLY_OBSERVABLE), "historically_observable")
    unknown = weight_of(make_path(observability=SNAPSHOT_ONLY), "snapshot_only")
    after = weight_of(make_path(observability=POST_DATES_REQUEST), "post_dates_request")
    assert before > unknown > after
    assert settings.path_factor_weights["post_dates_request"] < 0


def test_direct_hop_outranks_same_function_colleague_outranks_colleague_outranks_investor():
    direct = weight_of(make_path(hop_type=HOP_DIRECT), "direct_target_person")
    aligned = weight_of(make_path(same_title_family=True), "same_title_family")
    colleague = weight_of(make_path(), "colleague_at_account")
    investor = weight_of(make_path(hop_type=HOP_INVESTOR), "investor_relationship")
    assert direct > aligned > colleague > investor


def test_indirect_paths_state_that_no_buyer_relationship_is_verified():
    assert "no_direct_buyer_relationship" in keys(make_path())
    assert "no_direct_buyer_relationship" in keys(make_path(hop_type=HOP_INVESTOR))
    assert "no_direct_buyer_relationship" not in keys(make_path(hop_type=HOP_DIRECT))


def test_no_direct_buyer_relationship_is_a_statement_not_a_penalty():
    assert weight_of(make_path(), "no_direct_buyer_relationship") == 0


def test_off_roster_connector_is_penalised_but_not_excluded():
    on = weight_of(make_path(connector_reachable=True), "connector_on_roster")
    off = weight_of(make_path(connector_reachable=False), "connector_off_roster")
    assert on > 0 > off
    assert "connector_off_roster" in keys(make_path(connector_reachable=False))


def test_second_source_corroboration_only_fires_when_a_second_source_exists():
    assert "corroborated_by_second_source" not in keys(make_path(), sources=1)
    factors = path_factors(make_path(), None, Settings(), corroborating_sources=2)
    statement = next(f.statement for f in factors if f.key == "corroborated_by_second_source")
    assert "2 independent sources" in statement


def test_prior_successful_intro_is_credited_to_the_connector():
    context = ConnectorContext(
        recent_asks=0, stated_monthly_capacity=4, prior_successful_intros=3, engaged_on_account=False
    )
    assert weight_of(make_path(), "connector_prior_successful_intro", context=context) > 0
    quiet = ConnectorContext(
        recent_asks=0, stated_monthly_capacity=4, prior_successful_intros=0, engaged_on_account=False
    )
    assert "connector_prior_successful_intro" not in keys(make_path(), context=quiet)


def test_recent_asks_penalise_proportionally_and_are_capped():
    settings = Settings()
    light = ConnectorContext(
        recent_asks=1, stated_monthly_capacity=None, prior_successful_intros=0, engaged_on_account=False
    )
    heavy = ConnectorContext(
        recent_asks=20, stated_monthly_capacity=None, prior_successful_intros=0, engaged_on_account=False
    )
    one = weight_of(make_path(), "connector_recent_ask", context=light, settings=settings)
    many = weight_of(make_path(), "connector_recent_ask", context=heavy, settings=settings)
    assert one == settings.path_factor_weights["connector_recent_ask"]
    assert many == settings.max_recent_ask_penalty < one


def test_over_capacity_fires_only_when_a_stated_capacity_is_exceeded():
    over = ConnectorContext(
        recent_asks=5, stated_monthly_capacity=4, prior_successful_intros=0, engaged_on_account=False
    )
    at = ConnectorContext(
        recent_asks=4, stated_monthly_capacity=4, prior_successful_intros=0, engaged_on_account=False
    )
    unknown = ConnectorContext(
        recent_asks=99, stated_monthly_capacity=None, prior_successful_intros=0, engaged_on_account=False
    )
    assert "connector_over_stated_capacity" in keys(make_path(), context=over)
    assert "connector_over_stated_capacity" not in keys(make_path(), context=at)
    assert "connector_over_stated_capacity" not in keys(make_path(), context=unknown)


def test_connector_already_engaged_on_the_account_is_penalised():
    engaged = ConnectorContext(
        recent_asks=0, stated_monthly_capacity=4, prior_successful_intros=0, engaged_on_account=True
    )
    assert weight_of(make_path(), "connector_already_engaged_on_account", context=engaged) < 0


def test_missing_connector_context_does_not_break_ranking():
    factors = path_factors(make_path(), None, Settings())
    assert factors
    assert all(factor.statement for factor in factors)


def test_weights_are_configurable_without_touching_code():
    louder = Settings(path_factor_weights={**Settings().path_factor_weights, "direct_target_person": 999})
    assert weight_of(make_path(hop_type=HOP_DIRECT), "direct_target_person", settings=louder) == 999


def _request_with_paths(session) -> IntroRequest:
    row = session.execute(
        select(IntroCandidatePath.request_id)
        .group_by(IntroCandidatePath.request_id)
        .having(func.count() > 2)
        .limit(1)
    ).first()
    if row is None:  # pragma: no cover - the corpus has such requests
        pytest.skip("no multi-path request in the corpus")
    return session.get(IntroRequest, row[0])


def test_ordering_is_deterministic_across_runs(session, settings, clock):
    request = _request_with_paths(session)
    first = [entry.path.id for entry in rank_paths(session, request, settings, clock.now())]
    second = [entry.path.id for entry in rank_paths(session, request, settings, clock.now())]
    assert first == second
    assert len(first) > 1


def test_ranking_is_monotonic_and_ranks_are_dense(session, settings, clock):
    request = _request_with_paths(session)
    ranked = rank_paths(session, request, settings, clock.now())
    assert [entry.rank for entry in ranked] == list(range(1, len(ranked) + 1))
    priorities = [entry.priority for entry in ranked]
    assert priorities == sorted(priorities, reverse=True)
    assert sum(1 for entry in ranked if entry.recommended) == 1


def test_payload_explains_the_order_without_exposing_a_number(session, settings, clock):
    request = _request_with_paths(session)
    payload = candidate_path_payload(session, request, settings, clock.now())
    top = payload["paths"][0]
    assert top["recommendation_label"] == "Recommended to investigate first"
    assert top["factors"]
    assert not payload["paths"][1]["recommendation_label"]

    def leaves(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield from leaves(item) if isinstance(item, (dict, list)) else [(key, item)]
        elif isinstance(value, list):
            for item in value:
                yield from leaves(item)

    forbidden = {"priority", "score", "weight", "points", "total_score"}
    assert not [key for key, _ in leaves(payload["paths"]) if key in forbidden]


def test_no_path_request_ranks_to_an_empty_list(session, settings, clock):
    empty = session.scalars(
        select(IntroRequest).where(
            ~IntroRequest.id.in_(select(IntroCandidatePath.request_id)),
        )
    ).first()
    if empty is None:  # pragma: no cover - the corpus has no-path requests
        pytest.skip("no path-less request in the corpus")
    assert rank_paths(session, empty, settings, clock.now()) == []
    payload = candidate_path_payload(session, empty, settings, clock.now())
    assert payload["counts"]["total"] == 0
    assert payload["disclaimer"]


def test_over_capacity_connector_can_be_outranked_by_a_quieter_one(session, settings, clock):
    """A viable alternative must be able to overtake an overloaded connector."""
    loaded = ConnectorContext(
        recent_asks=8, stated_monthly_capacity=3, prior_successful_intros=0, engaged_on_account=False
    )
    quiet = ConnectorContext(
        recent_asks=0, stated_monthly_capacity=3, prior_successful_intros=0, engaged_on_account=False
    )
    strong_but_busy = sum(
        f.weight for f in path_factors(make_path(observability=HISTORICALLY_OBSERVABLE), loaded, settings)
    )
    same_but_quiet = sum(
        f.weight for f in path_factors(make_path(observability=HISTORICALLY_OBSERVABLE), quiet, settings)
    )
    assert same_but_quiet > strong_but_busy


def test_connector_contexts_cover_every_connector(session, settings, clock):
    contexts = connector_contexts(session, settings, clock.now(), account_id=None)
    assert len(contexts) == len(session.scalars(select(Connector)).all())
