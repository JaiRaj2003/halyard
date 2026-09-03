"""End-to-end checks on the generated audit outputs.

These assert the invariants the audit's conclusions depend on: nothing is
silently dropped, the denominator is the 200-row spine, every rate ships with a
numerator and denominator, and every inferred state keeps its evidence.
"""

import json

import pandas as pd
import pytest
from conftest import load_step

from common import io

pytestmark = pytest.mark.skipif(
    not (io.OUT_DIR / "summary_metrics.json").exists(),
    reason="run `python analysis/audit/run_audit.py` first",
)

duplicates_step = load_step("07_duplicates_trust_visibility.py")


@pytest.fixture(scope="module")
def requests_frame() -> pd.DataFrame:
    return io.read_output("request_reconstruction.csv")


def test_every_raw_record_is_accounted_for():
    counts = io.read_output("source_record_counts.csv").set_index("source")["records"].astype(int)
    assert counts["intro_requests.csv"] == 200
    assert counts["intro_outcomes.csv"] == 85
    for name, expected in [
        ("intro_requests.csv", len(io.load_requests())),
        ("intro_outcomes.csv", len(io.load_outcomes())),
        ("crm_accounts.csv", len(io.load_crm())),
        ("investor_network.csv", len(io.load_investors())),
        ("connector_roster.csv", len(io.load_roster())),
    ]:
        assert counts[name] == expected


def test_request_spine_is_the_denominator(requests_frame):
    assert len(requests_frame) == 200
    assert requests_frame["request_id"].is_unique
    assert set(requests_frame["request_id"]) == set(io.load_requests()["request_id"])


def test_slack_only_activity_is_reported_separately_not_added_to_the_spine():
    reconciliation = io.read_output("slack_reconciliation.csv").set_index("check")["count"].astype(int)
    assert reconciliation["requests_in_spine"] == 200
    assert "slack_threads_without_request_row" in reconciliation.index


def test_outcome_rows_all_map_to_the_spine(requests_frame):
    assert set(io.load_outcomes()["request_id"]) <= set(requests_frame["request_id"])
    assert int(requests_frame["routed"].eq("True").sum()) == len(io.load_outcomes())


def test_every_percentage_carries_numerator_and_denominator():
    metrics = json.loads((io.OUT_DIR / "summary_metrics.json").read_text())
    for key, value in metrics.items():
        if isinstance(value, dict) and "pct" in value:
            assert value["denominator"], f"{key} has a percentage with no denominator"
            assert value["numerator"] <= value["denominator"], key
            assert value["pct"] == pytest.approx(100 * value["numerator"] / value["denominator"], abs=0.05)


def test_every_latency_metric_reports_its_coverage():
    latency = io.read_output("request_latency.csv")
    for row in latency.itertuples():
        assert row.denominator, row.metric
        if int(row.n_observed) == 0:
            assert row.note, f"{row.metric} is empty and must say why"
        assert float(row.coverage_pct) == pytest.approx(100 * int(row.n_observed) / int(row.denominator), abs=0.05)


def test_every_derived_state_keeps_method_and_confidence(requests_frame):
    assert requests_frame["state_evidence"].str.len().gt(0).all()
    assert set(requests_frame["state_confidence"]) <= {"high", "medium", "low", "none"}
    declared_only = requests_frame[requests_frame["state_evidence_rank"] == "3_declared_status_only"]
    assert (declared_only["state_confidence"] == "low").all()
    assert declared_only["derived_state"].str.startswith("declared_only:").all()


def test_candidate_paths_never_claim_undated_sources_are_historically_available():
    paths = io.read_output("candidate_paths.csv")
    undated = paths[paths["relationship_date"].isna()]
    assert (undated["availability"] != "time_aware_available").all()
    investor_snapshot = paths[paths["availability"] == "snapshot_only_historical_unknown"]
    assert investor_snapshot["limitations"].str.contains("historical availability unknown").all()


def test_time_aware_paths_predate_their_request():
    paths = io.read_output("candidate_paths.csv")
    available = paths[paths["availability"] == "time_aware_available"]
    assert (pd.to_datetime(available["relationship_date"]) <= pd.to_datetime(available["request_date"])).all()


def test_duplicate_window_is_applied_consistently():
    dupes = io.read_output("duplicate_candidates.csv")
    within = dupes[dupes["within_window"] == "True"]
    assert within["days_apart"].astype(int).le(duplicates_step.DUPLICATE_WINDOW_DAYS).all()
    outside = dupes[dupes["within_window"] == "False"]
    assert outside["days_apart"].astype(int).gt(duplicates_step.DUPLICATE_WINDOW_DAYS).all()


def test_account_resolution_preserves_ambiguity(requests_frame):
    resolution = io.read_output("account_resolution.csv")
    assert resolution["match_tier"].notna().all()
    # Nothing may be assigned a CRM id while competing candidates remain open.
    conflicted = resolution[resolution["canonical_account_id"].notna() & resolution["competing_candidates"].notna()]
    assert conflicted.empty or (conflicted["match_tier"] == "A_exact_crm_id").all()
    assert resolution["match_evidence"].notna().all()
