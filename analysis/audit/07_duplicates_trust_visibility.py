"""Step 07 - H4 duplicates, H5 data trust, H6 leadership visibility, H7 cross-source.

Outputs:
  analysis/output/duplicate_candidates.csv
  analysis/output/status_contradictions.csv
  analysis/output/leadership_observability.csv
  analysis/output/cross_source_findings.csv
"""

from __future__ import annotations

import sys
import re
from itertools import combinations
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import io
from common.normalize import norm_person, norm_ws, parse_date

DUPLICATE_WINDOW_DAYS = 90
REASK_PATTERN = re.compile(r"asking again|again|already|follow(?:ing)? up|still waiting|any update", re.IGNORECASE)

# analysis/output is written as text so provenance strings survive round-tripping;
# the numeric columns this step reasons over are coerced back explicitly.
COVERAGE_NUMERIC = [
    "n_paths_time_aware",
    "n_paths_snapshot",
    "n_connectors_time_aware",
    "n_connectors_snapshot",
    "time_aware_via_export",
    "time_aware_via_investor",
    "snapshot_only_investor_paths",
    "time_aware_same_title_family",
    "alternatives_to_used_connector",
]


def truthy(value: object) -> bool:
    return norm_ws(value).casefold() in {"true", "y", "yes", "1"}


def duplicates(requests: pd.DataFrame) -> pd.DataFrame:
    rows = []
    requests = requests.assign(
        person_key=requests["target_person_raw"].map(norm_person),
        date=requests["request_date"].map(parse_date),
    )
    for key, group in requests.groupby("target_company_canonical_key"):
        if not norm_ws(key) or len(group) < 2:
            continue
        for left, right in combinations(group.itertuples(), 2):
            gap = abs((left.date - right.date).days) if left.date and right.date else None
            same_person = bool(left.person_key) and left.person_key == right.person_key
            same_requester = norm_person(left.requested_by) == norm_person(right.requested_by)
            if same_person:
                kind = "same_target_person"
            elif left.target_title_family and left.target_title_family == right.target_title_family:
                kind = "same_account_same_title_family"
            else:
                kind = "same_account_different_person"
            within = gap is not None and gap <= DUPLICATE_WINDOW_DAYS
            rows.append(
                {
                    "request_id_a": left.request_id,
                    "request_id_b": right.request_id,
                    "target_company_canonical_key": key,
                    "target_company_a": left.target_company_raw,
                    "target_company_b": right.target_company_raw,
                    "overlap_type": kind,
                    "days_apart": gap,
                    "within_window": within,
                    "same_requester": same_requester,
                    "requester_a": left.requested_by,
                    "requester_b": right.requested_by,
                    "target_person_a": left.target_person_raw,
                    "target_person_b": right.target_person_raw,
                    "state_a": left.derived_state,
                    "state_b": right.derived_state,
                    "connector_a": left.connector_asked,
                    "connector_b": right.connector_asked,
                    "deal_value_a": int(left.deal_value_usd),
                    "deal_value_b": int(right.deal_value_usd),
                    "different_connectors_used": bool(
                        norm_ws(left.connector_asked)
                        and norm_ws(right.connector_asked)
                        and norm_person(left.connector_asked) != norm_person(right.connector_asked)
                    ),
                    "conflicting_deal_value": int(left.deal_value_usd) != int(right.deal_value_usd),
                    "severity": (
                        "high"
                        if same_person and within
                        else "medium"
                        if kind == "same_account_same_title_family" and within
                        else "low"
                    ),
                }
            )
    frame = pd.DataFrame(rows)
    return frame.sort_values(["severity", "days_apart"]) if len(frame) else frame


def reasks(requests: pd.DataFrame) -> pd.DataFrame:
    """Requests whose own text says they are a repeat, matched to the prior ask."""
    raw = io.load_requests().set_index("request_id")
    dated = requests.assign(date=requests["request_date"].map(parse_date))
    rows = []
    for request in dated.itertuples():
        text = norm_ws(raw.loc[request.request_id, "raw_ask"])
        if not REASK_PATTERN.search(text):
            continue
        earlier = dated[
            (dated["target_company_canonical_key"] == request.target_company_canonical_key)
            & (dated["date"] < request.date)
        ].sort_values("date")
        prior = earlier.iloc[-1] if len(earlier) else None
        rows.append(
            {
                "request_id": request.request_id,
                "request_date": request.request_date,
                "requested_by": request.requested_by,
                "target_company_raw": request.target_company_raw,
                "raw_ask": text,
                "prior_request_id": prior["request_id"] if prior is not None else "",
                "prior_request_date": prior["request_date"] if prior is not None else "",
                "prior_same_requester": bool(
                    prior is not None and norm_person(prior["requested_by"]) == norm_person(request.requested_by)
                ),
                "prior_derived_state": prior["derived_state"] if prior is not None else "",
                "prior_was_routed": bool(prior is not None and truthy(prior["routed"])),
                "prior_had_terminal_evidence": bool(prior is not None and truthy(prior["has_terminal_evidence"])),
                "days_since_prior": (request.date - parse_date(prior["request_date"])).days if prior is not None else None,
            }
        )
    return pd.DataFrame(rows)


def contradictions(requests: pd.DataFrame, coverage: pd.DataFrame, roster: pd.DataFrame) -> pd.DataFrame:
    roster_keys = {norm_person(n) for n in roster["name"]}
    cov = coverage.set_index("request_id")
    rows = []

    def add(request, check: str, detail: str, severity: str) -> None:
        rows.append(
            {
                "request_id": request.request_id,
                "check": check,
                "detail": detail,
                "severity": severity,
                "declared_status": request.declared_status,
                "declared_path_found_flag": request.declared_path_found_flag,
                "derived_state": request.derived_state,
                "deal_value_usd": int(request.deal_value_usd),
            }
        )

    for request in requests.itertuples():
        paths = cov.loc[request.request_id]
        declared = norm_ws(request.declared_status)
        flag = norm_ws(request.declared_path_found_flag)

        if declared == "Closed - no path" and paths["n_paths_time_aware"] > 0:
            add(
                request,
                "closed_no_path_but_path_observable",
                f"closed as 'no path' yet {int(paths['n_paths_time_aware'])} connection(s) to the account "
                f"pre-dating the request exist via {paths['connectors_time_aware']}",
                "high",
            )
        if flag == "No path found" and paths["n_paths_time_aware"] > 0:
            add(
                request,
                "path_flag_no_path_but_path_observable",
                f"path_found_flag='No path found' yet {int(paths['n_paths_time_aware'])} time-aware path(s) exist",
                "high",
            )
        if declared == "Intro sent" and not truthy(request.routed):
            add(request, "declared_intro_sent_without_outcome_row", "status claims an intro with no outcome record at all", "high")
        if declared == "Intro sent" and truthy(request.routed) and norm_ws(request.intro_sent) != "Y":
            add(request, "declared_intro_sent_contradicted_by_outcome", f"outcome row records intro_sent={norm_ws(request.intro_sent) or 'blank'}", "high")
        if declared == "Routed" and not truthy(request.routed):
            add(request, "declared_routed_without_connector", "status claims routing but no connector or asked_date is recorded anywhere", "high")
        if declared in {"Open", "Stalled"} and norm_ws(request.intro_sent) == "Y":
            add(request, "open_status_but_intro_recorded", "outcome row records an intro that the status never reflected", "medium")
        if flag == "Unknown" and truthy(request.routed):
            add(request, "path_flag_unknown_after_routing", "a connector was asked, yet the path flag was never updated from 'Unknown'", "medium")
        if norm_ws(request.connector_asked) and norm_person(request.connector_asked) not in roster_keys:
            add(request, "connector_not_on_roster", f"'{norm_ws(request.connector_asked)}' is recorded as connector but is absent from connector_roster.csv", "medium")
        if norm_ws(request.target_account_match_tier) in {"D_ambiguous", "E_unmatched", "C_similar_but_distinct"}:
            add(request, "target_account_unresolved", f"target '{request.target_company_raw}' resolves to tier {request.target_account_match_tier}", "medium")
        if truthy(request.routed) and norm_ws(request.connector_responded) == "Y" and norm_ws(request.intro_sent) == "N" and not truthy(request.has_terminal_evidence):
            add(request, "connector_responded_no_recorded_next_step", "connector responded, no intro and no closure recorded", "medium")

    return pd.DataFrame(rows)


def visibility(requests: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    total = len(requests)
    value = requests["deal_value_usd"].sum()
    cov = coverage.set_index("request_id")

    def block(question: str, mask: pd.Series, answerable_note: str) -> dict:
        answerable = int(mask.sum())
        at_risk = int(requests.loc[~mask, "deal_value_usd"].sum())
        return {
            "leadership_question": question,
            "answerable_from_data": answerable,
            "denominator": total,
            "answerable_pct": round(100 * answerable / total, 1),
            "unanswerable": total - answerable,
            "pipeline_usd_unanswerable": at_risk,
            "pipeline_usd_total": int(value),
            "evidence_rule": answerable_note,
        }

    strong_state = requests["state_evidence_rank"].isin(["1_outcome_event", "2_explicit_slack_statement"])
    owner = requests["owner_known"].map(truthy)
    next_action = requests["next_action_known"].map(truthy)
    stale = requests["potentially_stale"].map(truthy)
    resolved = requests["has_terminal_evidence"].map(truthy)
    path_known = requests["request_id"].map(lambda r: cov.loc[r, "n_paths_snapshot"] > 0)
    flag_agrees = requests["declared_path_found_flag"].map(norm_ws) != "Unknown"

    rows = [
        block("What is the real state of this request?", strong_state, "state derived from an outcome event or an explicit Slack statement; declared status alone does not count"),
        block("Who owns the next action right now?", owner, "a connector is recorded on the outcome row"),
        block("What is the next action?", next_action, "an unambiguous next step follows from the derived state"),
        block("Is this request still alive or quietly dead?", resolved | ~stale, "terminal evidence exists, or the request has shown activity within 30 days"),
        block("Do we even have a warm path into this account?", path_known, "at least one candidate path is observable in the supplied network snapshot"),
        block("Does the request record itself say whether a path exists?", flag_agrees, "path_found_flag is not 'Unknown'"),
    ]
    return pd.DataFrame(rows)


def cross_source(requests: pd.DataFrame, paths: pd.DataFrame, reask_frame: pd.DataFrame) -> pd.DataFrame:
    total = len(requests)
    rows: list[dict] = []

    def add(finding: str, numerator, denominator, detail: str) -> None:
        rows.append(
            {
                "finding": finding,
                "numerator": numerator,
                "denominator": denominator,
                "pct": round(100 * numerator / denominator, 1) if denominator else None,
                "detail": detail,
            }
        )

    add(
        "Requests where a connector is connected to the requested person themselves",
        int(paths[paths["edge_type"] == "export_direct_target_person"]["request_id"].nunique()),
        total,
        "the requested buyer never appears in any connector's export, so 'do we know them?' is always a second-hop question",
    )
    unreachable = paths[~paths["connector_reachable"].map(truthy)]
    add(
        "Candidate paths that run through people Halyard has no proven route to",
        len(unreachable),
        len(paths),
        "investor/advisor network people who are neither on the connector roster nor present in any connection export",
    )
    supply = io.read_output("connector_path_supply.csv")
    for column in ("requests_with_time_aware_path", "requests_actually_asked", "path_observable_never_asked"):
        supply[column] = pd.to_numeric(supply[column], errors="coerce").fillna(0).astype(int)
    roster_supply = supply[supply["on_roster"].map(truthy)]
    add(
        "Roster connector-request pairs where a time-aware path existed but the connector was never asked",
        int(roster_supply["path_observable_never_asked"].sum()),
        int(roster_supply["requests_with_time_aware_path"].sum()),
        "supply of observable warm paths vastly exceeds the asks actually made of those connectors",
    )
    add(
        "Requests whose target account has more than one request in the corpus",
        int(requests.groupby("target_company_canonical_key")["request_id"].transform("size").gt(1).sum()),
        total,
        f"200 requests cover only {requests['target_company_canonical_key'].nunique()} distinct canonical target accounts",
    )
    add(
        "Requests whose own text says the ask is a repeat",
        len(reask_frame),
        total,
        "requesters re-file asks such as 'asking again: ...' rather than trusting the system to surface the first one",
    )
    add(
        "Requests where someone in Slack asks whether the ask is a duplicate",
        int(requests["slack_duplicate_query"].map(truthy).sum()),
        total,
        "operators visibly cannot tell whether an ask already exists",
    )
    add(
        "Requests where a Slack participant volunteered a path but no outcome row exists",
        int((requests["slack_volunteer_offer"].map(truthy) & ~requests["routed"].map(truthy)).sum()),
        total,
        "offered help evaporates because nothing captures the offer as an assignment",
    )
    add(
        "Requests where Slack suggested a different person to ask and nothing was recorded",
        int((requests["slack_referral_suggestion"].map(truthy) & ~requests["routed"].map(truthy)).sum()),
        total,
        "referral suggestions are made in-thread and then lost",
    )
    add(
        "Recorded connectors who are not on the connector roster",
        int((~io.read_output("connector_load.csv")["on_roster"].map(truthy)).sum()),
        len(io.read_output("connector_load.csv")),
        "outcome rows name connectors the roster does not track, including at least one person who elsewhere files requests",
    )
    add(
        "Connector-months exceeding the connector's own stated monthly capacity",
        int(io.read_output("connector_month_load.csv")["over_capacity"].map(truthy).sum()),
        len(io.read_output("connector_month_load.csv")),
        "recorded load is far below stated capacity: overload is NOT what is throttling throughput",
    )
    add(
        "Requests with no recorded activity for 30+ days and no terminal evidence",
        int((requests["potentially_stale"].map(truthy) & ~requests["has_terminal_evidence"].map(truthy)).sum()),
        total,
        "these are neither alive nor closed; nothing in the system will ever surface them again",
    )
    return pd.DataFrame(rows)


def main() -> None:
    requests = io.read_output("request_reconstruction.csv")
    requests["deal_value_usd"] = pd.to_numeric(requests["deal_value_usd"], errors="coerce").fillna(0).astype(int)
    coverage = io.read_output("path_coverage.csv")
    for column in COVERAGE_NUMERIC:
        coverage[column] = pd.to_numeric(coverage[column], errors="coerce").fillna(0).astype(int)
    paths = io.read_output("candidate_paths.csv")
    roster = io.load_roster()

    dupes = duplicates(requests)
    reask = reasks(requests)
    contras = contradictions(requests, coverage, roster)
    vis = visibility(requests, coverage)
    cross = cross_source(requests, paths, reask)

    io.write_csv(dupes, "duplicate_candidates.csv")
    io.write_csv(reask, "reask_analysis.csv")
    io.write_csv(contras, "status_contradictions.csv")
    io.write_csv(vis, "leadership_observability.csv")
    io.write_csv(cross, "cross_source_findings.csv")

    matched = reask[reask["prior_request_id"].ne("")] if len(reask) else reask
    print("self-declared re-asks:", len(reask), "/", len(requests))
    if len(reask):
        print("  with an identifiable earlier ask for the same account:", len(matched))
        print("  whose earlier ask was never routed to a connector:", int((~matched["prior_was_routed"]).sum()))
        print("  whose earlier ask had no terminal evidence:", int((~matched["prior_had_terminal_evidence"]).sum()))
    print()
    print("duplicate candidate pairs:", len(dupes))
    if len(dupes):
        print(dupes.groupby(["overlap_type", "severity"]).size().to_string())
        print("requests involved in a within-window pair:",
              len(set(dupes[dupes["within_window"]]["request_id_a"]) | set(dupes[dupes["within_window"]]["request_id_b"])), "/", len(requests))
    print()
    print("status contradictions:", len(contras))
    print(contras.groupby(["check", "severity"]).size().sort_values(ascending=False).to_string())
    print("distinct requests with >=1 contradiction:", contras["request_id"].nunique(), "/", len(requests))
    print()
    print(vis.to_string(index=False))
    print()
    print(cross.to_string(index=False))


if __name__ == "__main__":
    main()
