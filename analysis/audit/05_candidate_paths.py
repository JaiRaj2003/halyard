"""Step 05 (H1) - candidate warm-introduction paths, time-aware.

Two distinct measures are produced and never conflated:

* ``snapshot`` - the path is visible in the supplied network snapshot today;
* ``time_aware`` - the path is defensibly available at the historical request
  date, which requires a date proving the relationship pre-dated the request
  (``connected_on <= request_date``, or ``prior_employer_start <= request_date``).

Sources without temporal information (investor / advisor portfolio edges) can
never reach ``time_aware``; they are labelled "visible in supplied current
snapshot; historical availability unknown". The headline missed-path metric uses
only time-aware paths.

A candidate path is a *lead worth checking*, not a strong relationship: the data
carries no relationship-strength signal, only connection recency and job title.

Outputs:
  analysis/output/candidate_paths.csv
  analysis/output/path_coverage.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import io
from common.accounts import canonical_key
from common.normalize import norm_person, norm_ws, parse_date, parse_partial_date, title_family

SNAPSHOT_ONLY_NOTE = "Candidate path visible in supplied current snapshot; historical availability unknown."


def build_paths() -> pd.DataFrame:
    requests = io.read_output("request_reconstruction.csv")
    connections = io.load_connections()
    investors = io.load_investors()
    roster = io.load_roster()

    roster_types = {norm_person(r.name): norm_ws(r.type) for r in roster.itertuples()}
    export_owners = {norm_person(name) for name in connections["connector"].unique()}

    connections = connections.rename(columns={"_source_file": "export_file"}).assign(
        company_key=connections["company"].map(canonical_key),
        person_key=connections["name"].map(norm_person),
        connected_on_date=connections["connected_on"].map(parse_date),
        contact_title_family=connections["title"].map(title_family),
    )
    connections_by_company = {key: group for key, group in connections.groupby("company_key")}
    connections_by_person = {key: group for key, group in connections.groupby("person_key")}

    investors = investors.assign(
        portfolio_key=investors["portfolio_company"].map(canonical_key),
        prior_key=investors["prior_employer"].map(canonical_key),
        person_key=investors["person"].map(norm_person),
    )

    rows: list[dict] = []
    for request in requests.itertuples():
        request_date = parse_date(request.request_date)
        target_company_key = norm_ws(request.target_company_canonical_key)
        target_person_key = norm_person(request.target_person_raw)
        target_family = norm_ws(request.target_title_family)

        def add(**kwargs) -> None:
            rows.append({"request_id": request.request_id, "request_date": request_date, **kwargs})

        def availability_label(relationship_date, request_date) -> str:
            if relationship_date is None or request_date is None:
                return "unknown"
            return "time_aware_available" if relationship_date <= request_date else "post_dates_request"

        if target_person_key and target_person_key in connections_by_person:
            for edge in connections_by_person[target_person_key].itertuples():
                add(
                    connector=edge.connector,
                    connector_type=roster_types.get(norm_person(edge.connector), "unknown"),
                    connector_reachable=True,
                    edge_type="export_direct_target_person",
                    target_entity=norm_ws(edge.name),
                    target_entity_title=norm_ws(edge.title),
                    target_entity_company=norm_ws(edge.company),
                    same_title_family=bool(target_family and edge.contact_title_family == target_family),
                    source_file=edge.export_file,
                    relationship_date=edge.connected_on_date,
                    recency_days_at_request=(
                        (request_date - edge.connected_on_date).days
                        if edge.connected_on_date and request_date
                        else None
                    ),
                    availability=availability_label(edge.connected_on_date, request_date),
                    confidence="medium",
                    limitations="Name match to the requested target person; no relationship-strength signal available.",
                )

        if target_company_key and target_company_key in connections_by_company:
            for edge in connections_by_company[target_company_key].itertuples():
                if edge.person_key == target_person_key:
                    continue
                add(
                    connector=edge.connector,
                    connector_type=roster_types.get(norm_person(edge.connector), "unknown"),
                    connector_reachable=True,
                    edge_type="export_colleague_at_target_account",
                    target_entity=norm_ws(edge.name),
                    target_entity_title=norm_ws(edge.title),
                    target_entity_company=norm_ws(edge.company),
                    same_title_family=bool(target_family and edge.contact_title_family == target_family),
                    source_file=edge.export_file,
                    relationship_date=edge.connected_on_date,
                    recency_days_at_request=(
                        (request_date - edge.connected_on_date).days
                        if edge.connected_on_date and request_date
                        else None
                    ),
                    availability=availability_label(edge.connected_on_date, request_date),
                    confidence="medium" if target_family and edge.contact_title_family == target_family else "low",
                    limitations=(
                        "Connection is to a colleague at the target account, not the requested person; "
                        "onward reachability inside the account is unknown."
                    ),
                )

        if not target_company_key:
            continue

        for edge in investors[investors["portfolio_key"] == target_company_key].itertuples():
            reachable = edge.person_key in roster_types or edge.person_key in export_owners
            add(
                connector=norm_ws(edge.person),
                connector_type="Investor/Advisor" + ("" if reachable else " (not on roster or in exports)"),
                connector_reachable=reachable,
                edge_type="investor_portfolio_board_seat" if edge.board_seat == "True" else "investor_portfolio",
                target_entity=norm_ws(edge.portfolio_company),
                target_entity_title="",
                target_entity_company=norm_ws(edge.portfolio_company),
                same_title_family=False,
                source_file="investor_network.csv",
                relationship_date=None,
                recency_days_at_request=None,
                availability="snapshot_only_historical_unknown",
                confidence="medium" if edge.board_seat == "True" else "low",
                limitations=SNAPSHOT_ONLY_NOTE
                + (" Board seat implies direct access to leadership." if edge.board_seat == "True" else "")
                + ("" if reachable else " Connector is not on the roster and appears in no export: reachability unproven."),
            )

        for edge in investors[investors["prior_key"] == target_company_key].itertuples():
            start = parse_partial_date(edge.prior_employer_start)
            reachable = edge.person_key in roster_types or edge.person_key in export_owners
            add(
                connector=norm_ws(edge.person),
                connector_type="Investor/Advisor" + ("" if reachable else " (not on roster or in exports)"),
                connector_reachable=reachable,
                edge_type="investor_alumni_prior_employer",
                target_entity=norm_ws(edge.prior_employer),
                target_entity_title="",
                target_entity_company=norm_ws(edge.prior_employer),
                same_title_family=False,
                source_file="investor_network.csv",
                relationship_date=start,
                recency_days_at_request=None,
                availability=availability_label(start, request_date),
                confidence="low",
                limitations=(
                    "Alumni relationship inferred from prior employment (year-only dates); whether live "
                    "contacts remain inside the account is unknown."
                ),
            )

    return pd.DataFrame(rows)


def build_coverage(paths: pd.DataFrame) -> pd.DataFrame:
    requests = io.read_output("request_reconstruction.csv")
    grouped = {key: group for key, group in paths.groupby("request_id")} if len(paths) else {}
    empty = paths.iloc[0:0]

    records = []
    for request in requests.itertuples():
        group = grouped.get(request.request_id, empty)
        time_aware = group[group["availability"] == "time_aware_available"]
        connector_used = norm_person(request.connector_asked)
        observable_connectors = {norm_person(c) for c in time_aware["connector"]}
        snapshot_connectors = {norm_person(c) for c in group["connector"]}
        records.append(
            {
                "request_id": request.request_id,
                "target_company_raw": request.target_company_raw,
                "target_company_canonical_key": request.target_company_canonical_key,
                "declared_path_found_flag": request.declared_path_found_flag,
                "declared_status": request.declared_status,
                "derived_state": request.derived_state,
                "routed": request.routed,
                "connector_asked": request.connector_asked,
                "deal_value_usd": int(request.deal_value_usd),
                "urgency": request.urgency,
                "n_paths_time_aware": int(len(time_aware)),
                "n_paths_snapshot": int(len(group)),
                "n_connectors_time_aware": len(observable_connectors),
                "n_connectors_snapshot": len(snapshot_connectors),
                "time_aware_via_export": int(time_aware["edge_type"].str.startswith("export_").sum()),
                "time_aware_via_investor": int(time_aware["edge_type"].str.startswith("investor_").sum()),
                "snapshot_only_investor_paths": int((group["availability"] == "snapshot_only_historical_unknown").sum()),
                "time_aware_same_title_family": int(time_aware["same_title_family"].sum()),
                "connectors_time_aware": "; ".join(sorted({norm_ws(c) for c in time_aware["connector"]})),
                "used_connector_was_observable": bool(connector_used and connector_used in observable_connectors),
                "used_connector_was_only_observable_path": bool(
                    connector_used and observable_connectors == {connector_used}
                ),
                "alternatives_to_used_connector": (
                    len(observable_connectors - {connector_used}) if connector_used else len(observable_connectors)
                ),
            }
        )
    return pd.DataFrame(records)


def main() -> None:
    paths = build_paths()
    coverage = build_coverage(paths)
    io.write_csv(paths, "candidate_paths.csv")
    io.write_csv(coverage, "path_coverage.csv")

    total = len(coverage)
    print("candidate path edges:", len(paths))
    print(paths.groupby(["edge_type", "availability"]).size().to_string())
    print()
    print("requests with >=1 time-aware path:", int((coverage["n_paths_time_aware"] > 0).sum()), "/", total)
    print("requests with >=2 time-aware connectors:", int((coverage["n_connectors_time_aware"] >= 2).sum()), "/", total)
    print(
        "requests with only snapshot (undated) paths:",
        int(((coverage["n_paths_time_aware"] == 0) & (coverage["n_paths_snapshot"] > 0)).sum()),
        "/",
        total,
    )
    print()
    negative = coverage[
        coverage["declared_path_found_flag"].isin(["No path found", "Unknown", ""])
        | coverage["declared_status"].eq("Closed - no path")
    ]
    print("requests declared no-path / unknown:", len(negative))
    print("  with >=1 time-aware path:", int((negative["n_paths_time_aware"] > 0).sum()))
    print("  with >=2 time-aware paths:", int((negative["n_paths_time_aware"] >= 2).sum()))
    print("  with time-aware path via export:", int((negative["time_aware_via_export"] > 0).sum()))
    print("  with investor/advisor path (snapshot only):", int((negative["snapshot_only_investor_paths"] > 0).sum()))
    print()
    routed = coverage[coverage["routed"] == "True"]
    print("routed requests:", len(routed))
    print("  used connector observable by this logic:", int(routed["used_connector_was_observable"].sum()))
    print("  used connector was the only observable path:", int(routed["used_connector_was_only_observable_path"].sum()))


if __name__ == "__main__":
    main()
