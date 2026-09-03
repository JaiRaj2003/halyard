"""Step 06 (H2) - connector concentration, capacity and throughput.

Asks are counted from ``intro_outcomes.asked_date`` (the only evidence that a
connector was actually asked). Capacity is the connector's own stated monthly
number from the roster. Because 115/200 requests have no outcome row, this is a
*lower bound* on real load: unrouted asks are excluded, never imputed.

Outputs:
  analysis/output/connector_load.csv
  analysis/output/connector_month_load.csv
  analysis/output/connector_path_supply.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import io
from common.normalize import norm_person, norm_ws, parse_date


def main() -> None:
    outcomes = io.load_outcomes()
    roster = io.load_roster()
    requests = io.read_output("request_reconstruction.csv")
    paths = io.read_output("candidate_paths.csv")

    roster_by_key = {norm_person(r.name): r for r in roster.itertuples()}

    outcomes = outcomes.assign(
        connector_key=outcomes["connector_asked"].map(norm_person),
        asked=outcomes["asked_date"].map(parse_date),
    )
    outcomes["month"] = outcomes["asked"].map(lambda d: d.strftime("%Y-%m") if d else "unknown")

    deal_values = {r.request_id: int(r.deal_value_usd) for r in requests.itertuples()}

    rows = []
    for key, group in outcomes.groupby("connector_key"):
        roster_row = roster_by_key.get(key)
        capacity = int(roster_row.stated_monthly_capacity) if roster_row is not None else None
        months = group[group["month"] != "unknown"].groupby("month").size()
        responded = int((group["responded"] == "Y").sum())
        intros = int((group["intro_sent"] == "Y").sum())
        meetings = int((group["meeting_booked"] == "Y").sum())
        turnaround = [
            (parse_date(r.response_date) - parse_date(r.asked_date)).days
            for r in group.itertuples()
            if parse_date(r.response_date) and parse_date(r.asked_date)
        ]
        rows.append(
            {
                "connector": norm_ws(group["connector_asked"].iloc[0]),
                "on_roster": roster_row is not None,
                "connector_type": norm_ws(roster_row.type) if roster_row is not None else "not_on_roster",
                "stated_monthly_capacity": capacity,
                "asks_recorded": len(group),
                "share_of_recorded_asks_pct": round(100 * len(group) / len(outcomes), 1),
                "active_months": int(len(months)),
                "peak_month": months.idxmax() if len(months) else "",
                "peak_month_asks": int(months.max()) if len(months) else 0,
                "months_over_capacity": int((months > capacity).sum()) if capacity else None,
                "peak_month_over_capacity_by": int(months.max() - capacity) if capacity and len(months) else None,
                "responded": responded,
                "response_rate_pct": round(100 * responded / len(group), 1),
                "intros_sent": intros,
                "intro_rate_pct": round(100 * intros / len(group), 1),
                "meetings_booked": meetings,
                "median_response_days": float(pd.Series(turnaround).median()) if turnaround else None,
                "response_days_coverage": f"{len(turnaround)}/{len(group)}",
                "deal_value_asked_usd": sum(deal_values.get(r, 0) for r in group["request_id"]),
            }
        )

    load = pd.DataFrame(rows).sort_values("asks_recorded", ascending=False)

    month_rows = []
    for (key, month), group in outcomes[outcomes["month"] != "unknown"].groupby(["connector_key", "month"]):
        roster_row = roster_by_key.get(key)
        capacity = int(roster_row.stated_monthly_capacity) if roster_row is not None else None
        month_rows.append(
            {
                "connector": norm_ws(group["connector_asked"].iloc[0]),
                "month": month,
                "asks": len(group),
                "stated_monthly_capacity": capacity,
                "over_capacity": bool(capacity and len(group) > capacity),
                "responded": int((group["responded"] == "Y").sum()),
                "intros_sent": int((group["intro_sent"] == "Y").sum()),
            }
        )
    month_load = pd.DataFrame(month_rows).sort_values(["connector", "month"])

    time_aware = paths[paths["availability"] == "time_aware_available"]
    supply_rows = []
    for key, group in time_aware.assign(k=time_aware["connector"].map(norm_person)).groupby("k"):
        roster_row = roster_by_key.get(key)
        reachable_requests = set(group["request_id"])
        asked_requests = set(outcomes[outcomes["connector_key"] == key]["request_id"])
        supply_rows.append(
            {
                "connector": norm_ws(group["connector"].iloc[0]),
                "on_roster": roster_row is not None,
                "stated_monthly_capacity": int(roster_row.stated_monthly_capacity) if roster_row is not None else None,
                "requests_with_time_aware_path": len(reachable_requests),
                "requests_actually_asked": len(asked_requests),
                "asked_where_path_observable": len(asked_requests & reachable_requests),
                "path_observable_never_asked": len(reachable_requests - asked_requests),
            }
        )
    supply = pd.DataFrame(supply_rows).sort_values("requests_with_time_aware_path", ascending=False)

    io.write_csv(load, "connector_load.csv")
    io.write_csv(month_load, "connector_month_load.csv")
    io.write_csv(supply, "connector_path_supply.csv")

    print("recorded asks (outcome rows):", len(outcomes), "of", len(requests), "requests")
    print(load.to_string(index=False))
    print()
    top2 = load.head(2)["asks_recorded"].sum()
    print(f"top-2 connectors hold {top2}/{len(outcomes)} recorded asks ({round(100*top2/len(outcomes),1)}%)")
    print("connector-months over stated capacity:", int(month_load["over_capacity"].sum()), "/", len(month_load))
    print()
    print(supply.to_string(index=False))


if __name__ == "__main__":
    main()
