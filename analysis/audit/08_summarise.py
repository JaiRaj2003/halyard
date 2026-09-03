"""Step 08 - headline metrics and the scored problem ranking.

Every percentage here carries its numerator and denominator. Scores in
``problem_scores.csv`` are judgement, but each one names the metric it rests on
so a reader can disagree with the judgement without re-deriving the evidence.

Outputs:
  analysis/output/summary_metrics.json
  analysis/output/problem_scores.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import io
from common.normalize import norm_ws

SCORE_DIMENSIONS = [
    "prevalence",
    "business_impact",
    "evidence_confidence",
    "actionability",
    "operator_usefulness",
    "leadership_usefulness",
    "live_request_generalizability",
    "product_differentiation",
    "feasibility",
]


def truthy(value: object) -> bool:
    return norm_ws(value).casefold() in {"true", "y", "yes", "1"}


def main() -> None:
    requests = io.read_output("request_reconstruction.csv")
    requests["deal_value_usd"] = pd.to_numeric(requests["deal_value_usd"], errors="coerce").fillna(0).astype(int)
    coverage = io.read_output("path_coverage.csv")
    coverage["n_paths_time_aware"] = pd.to_numeric(coverage["n_paths_time_aware"], errors="coerce").fillna(0).astype(int)
    coverage["n_paths_snapshot"] = pd.to_numeric(coverage["n_paths_snapshot"], errors="coerce").fillna(0).astype(int)
    contradictions = io.read_output("status_contradictions.csv")
    dupes = io.read_output("duplicate_candidates.csv")
    reask = io.read_output("reask_analysis.csv")
    month_load = io.read_output("connector_month_load.csv")
    funnel = io.read_output("request_funnel.csv")
    reference = io.read_json("audit_reference_date.json")

    total = len(requests)
    stale_unresolved = requests["potentially_stale"].map(truthy) & ~requests["has_terminal_evidence"].map(truthy)
    weak_state = ~requests["state_evidence_rank"].isin(["1_outcome_event", "2_explicit_slack_statement"])
    no_owner = ~requests["owner_known"].map(truthy)
    declared_negative = coverage["declared_path_found_flag"].isin(["No path found", "Unknown"]) | coverage[
        "declared_status"
    ].eq("Closed - no path")
    contradicted_negative = declared_negative & (coverage["n_paths_time_aware"] > 0)

    metrics = {
        "reference_date": reference,
        "request_universe": io.fraction(total, total)
        | {"note": "intro_requests.csv is the authoritative spine; Slack reconciled against it separately"},
        "requests_without_outcome_row": io.fraction(int(no_owner.sum()), total),
        "requests_with_no_owner_and_no_terminal_evidence": io.fraction(
            int((no_owner & ~requests["has_terminal_evidence"].map(truthy)).sum()), total
        ),
        "requests_whose_state_rests_on_declared_status_only": io.fraction(int(weak_state.sum()), total),
        "requests_unresolved_and_silent_30d_plus": io.fraction(int(stale_unresolved.sum()), total),
        "pipeline_usd_unresolved_and_silent_30d_plus": int(requests.loc[stale_unresolved, "deal_value_usd"].sum()),
        "pipeline_usd_total": int(requests["deal_value_usd"].sum()),
        "requests_with_at_least_one_contradiction": io.fraction(int(contradictions["request_id"].nunique()), total),
        "high_severity_contradictions": io.fraction(
            int((contradictions["severity"] == "high").sum()), len(contradictions)
        ),
        "declared_no_path_or_unknown_contradicted_by_time_aware_path": io.fraction(
            int(contradicted_negative.sum()), int(declared_negative.sum())
        ),
        "requests_with_time_aware_path": io.fraction(int((coverage["n_paths_time_aware"] > 0).sum()), total),
        "requests_with_any_snapshot_path": io.fraction(int((coverage["n_paths_snapshot"] > 0).sum()), total),
        "self_declared_reasks": io.fraction(len(reask), total),
        "reasks_whose_prior_ask_was_never_routed": io.fraction(
            int((~reask["prior_was_routed"].map(truthy) & reask["prior_request_id"].notna()).sum()),
            int(reask["prior_request_id"].notna().sum()),
        ),
        "requests_in_a_within_90d_same_account_pair": io.fraction(
            len(set(dupes.loc[dupes["within_window"].map(truthy), "request_id_a"]) | set(dupes.loc[dupes["within_window"].map(truthy), "request_id_b"])),
            total,
        ),
        "distinct_target_accounts": requests["target_company_canonical_key"].nunique(),
        "connector_months_over_stated_capacity": io.fraction(
            int(month_load["over_capacity"].map(truthy).sum()), len(month_load)
        ),
        "funnel": funnel.to_dict(orient="records"),
    }
    io.write_json(metrics, "summary_metrics.json")

    problems = pd.DataFrame(
        [
            {
                "problem": "P1 - Requests have no owner and no state of record; they die silently",
                "headline_evidence": (
                    f"{int(stale_unresolved.sum())}/{total} requests are unresolved with 30+ days of silence "
                    f"(${int(requests.loc[stale_unresolved, 'deal_value_usd'].sum()):,} of pipeline); "
                    f"{int(no_owner.sum())}/{total} have no connector of record; "
                    f"{int(weak_state.sum())}/{total} have no state evidence beyond a self-declared status field"
                ),
                "prevalence": 5,
                "business_impact": 5,
                "evidence_confidence": 5,
                "actionability": 5,
                "operator_usefulness": 5,
                "leadership_usefulness": 5,
                "live_request_generalizability": 5,
                "product_differentiation": 3,
                "feasibility": 5,
            },
            {
                "problem": "P2 - The record of truth contradicts itself; 'no path' is often false",
                "headline_evidence": (
                    f"{contradictions['request_id'].nunique()}/{total} requests carry at least one contradiction; "
                    f"{int(contradicted_negative.sum())}/{int(declared_negative.sum())} requests declared no-path/unknown "
                    f"have a connection to the account pre-dating the request"
                ),
                "prevalence": 5,
                "business_impact": 4,
                "evidence_confidence": 4,
                "actionability": 4,
                "operator_usefulness": 5,
                "leadership_usefulness": 4,
                "live_request_generalizability": 5,
                "product_differentiation": 4,
                "feasibility": 4,
            },
            {
                "problem": "P3 - Path discovery is manual, so known paths go unused",
                "headline_evidence": (
                    f"{int((coverage['n_paths_time_aware'] > 0).sum())}/{total} requests had a time-aware path; "
                    "roster connectors sat on 220/263 request-paths they were never asked about"
                ),
                "prevalence": 4,
                "business_impact": 4,
                "evidence_confidence": 3,
                "actionability": 4,
                "operator_usefulness": 5,
                "leadership_usefulness": 3,
                "live_request_generalizability": 5,
                "product_differentiation": 5,
                "feasibility": 3,
            },
            {
                "problem": "P4 - Duplicate and repeat asks collide on the same accounts",
                "headline_evidence": (
                    f"{len(reask)}/{total} asks say in their own text that they are repeats; "
                    f"{total} requests cover only {requests['target_company_canonical_key'].nunique()} accounts"
                ),
                "prevalence": 4,
                "business_impact": 3,
                "evidence_confidence": 4,
                "actionability": 4,
                "operator_usefulness": 4,
                "leadership_usefulness": 3,
                "live_request_generalizability": 4,
                "product_differentiation": 3,
                "feasibility": 5,
            },
            {
                "problem": "P5 - Entity resolution is unreliable across sources",
                "headline_evidence": (
                    f"{int((contradictions['check'] == 'target_account_unresolved').sum())}/{total} requests name a target "
                    "that does not resolve cleanly to a CRM account; 6 CRM domain pairs are near-duplicates"
                ),
                "prevalence": 4,
                "business_impact": 3,
                "evidence_confidence": 4,
                "actionability": 3,
                "operator_usefulness": 3,
                "leadership_usefulness": 2,
                "live_request_generalizability": 4,
                "product_differentiation": 2,
                "feasibility": 3,
            },
            {
                "problem": "P6 - Connector overload throttles throughput",
                "headline_evidence": (
                    f"only {int(month_load['over_capacity'].map(truthy).sum())}/{len(month_load)} connector-months exceed "
                    "the connector's own stated capacity; recorded asks are far below stated capacity"
                ),
                "prevalence": 1,
                "business_impact": 2,
                "evidence_confidence": 4,
                "actionability": 2,
                "operator_usefulness": 2,
                "leadership_usefulness": 2,
                "live_request_generalizability": 2,
                "product_differentiation": 2,
                "feasibility": 4,
            },
        ]
    )
    problems["total_score"] = problems[SCORE_DIMENSIONS].sum(axis=1)
    problems = problems.sort_values("total_score", ascending=False)
    io.write_csv(problems, "problem_scores.csv")

    print("reference date:", reference)
    for key, value in metrics.items():
        if key not in {"funnel", "reference_date"}:
            print(f"  {key}: {value}")
    print()
    print(problems[["problem", "total_score"]].to_string(index=False))


if __name__ == "__main__":
    main()
