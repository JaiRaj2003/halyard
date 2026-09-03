"""Step 01 - profile every supplied source, column by column.

Output: analysis/output/source_profile.csv, analysis/output/source_record_counts.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import io
from common.normalize import (
    has_casing_defect,
    has_whitespace_defect,
    is_malformed_name,
    norm_ws,
    parse_date,
    parse_timestamp,
)

DATE_COLUMNS = {"connected_on", "request_date", "asked_date", "response_date", "intro_date", "last_touch_date"}
NAME_COLUMNS = {
    "name",
    "person",
    "requested_by",
    "connector_asked",
    "target_person_raw",
    "owner",
    "user",
    "account_name",
}
KEY_COLUMNS = {
    "request_id",
    "account_id",
    "domain",
    "profile_url",
    "connector_asked",
    "person",
    "name",
}


def profile_frame(frame: pd.DataFrame, source: str, id_column: str | None) -> list[dict]:
    rows = []
    data_columns = [c for c in frame.columns if not c.startswith("_")]
    duplicate_rows = int(frame.duplicated(subset=data_columns).sum())
    for column in data_columns:
        series = frame[column]
        values = series.map(norm_ws)
        non_empty = values[values != ""]
        record: dict[str, object] = {
            "source": source,
            "column": column,
            "rows": len(frame),
            "duplicate_full_rows": duplicate_rows,
            "null_count": int(len(frame) - len(non_empty)),
            "null_rate_pct": round(100.0 * (len(frame) - len(non_empty)) / len(frame), 1) if len(frame) else None,
            "unique_non_null": int(non_empty.nunique()),
            "is_candidate_join_key": column in KEY_COLUMNS,
            "unique_ratio_pct": round(100.0 * non_empty.nunique() / len(non_empty), 1) if len(non_empty) else None,
            "whitespace_defects": int(series.map(has_whitespace_defect).sum()),
            "casing_defects": int(non_empty.map(has_casing_defect).sum()),
        }
        if column in DATE_COLUMNS:
            parsed = non_empty.map(parse_date)
            valid = parsed.dropna()
            record["malformed_values"] = int(parsed.isna().sum())
            record["min_date"] = str(valid.min()) if len(valid) else ""
            record["max_date"] = str(valid.max()) if len(valid) else ""
        elif column == "ts":
            parsed = non_empty.map(parse_timestamp)
            valid = parsed.dropna()
            record["malformed_values"] = int(parsed.isna().sum())
            record["min_date"] = str(valid.min().date()) if len(valid) else ""
            record["max_date"] = str(valid.max().date()) if len(valid) else ""
        else:
            record["malformed_values"] = ""
            record["min_date"] = ""
            record["max_date"] = ""
        record["malformed_names"] = int(non_empty.map(is_malformed_name).sum()) if column in NAME_COLUMNS else ""
        if column == "profile_url" or column == "domain":
            record["missing_identifier_count"] = int(len(frame) - len(non_empty))
        else:
            record["missing_identifier_count"] = ""
        if id_column and column == id_column:
            record["duplicate_ids"] = int(non_empty.duplicated().sum())
        else:
            record["duplicate_ids"] = ""
        rows.append(record)
    return rows


def main() -> None:
    sources: list[tuple[str, pd.DataFrame, str | None]] = [
        ("intro_requests.csv", io.load_requests(), "request_id"),
        ("intro_outcomes.csv", io.load_outcomes(), "request_id"),
        ("crm_accounts.csv", io.load_crm(), "account_id"),
        ("connector_roster.csv", io.load_roster(), "name"),
        ("investor_network.csv", io.load_investors(), None),
        ("slack_threads.jsonl (messages)", io.slack_messages(), None),
    ]
    connections = io.load_connections()
    for filename, group in connections.groupby("_source_file", sort=True):
        sources.append((str(filename), group.drop(columns=["connector"]), "profile_url"))

    profile_rows: list[dict] = []
    counts: list[dict] = []
    for source, frame, id_column in sources:
        profile_rows.extend(profile_frame(frame, source, id_column))
        counts.append({"source": source, "records": len(frame)})

    threads = io.load_slack()
    counts.append({"source": "slack_threads.jsonl (threads)", "records": len(threads)})

    io.write_csv(pd.DataFrame(profile_rows), "source_profile.csv")
    io.write_csv(pd.DataFrame(counts), "source_record_counts.csv")
    print(pd.DataFrame(counts).to_string(index=False))


if __name__ == "__main__":
    main()
