"""Step 03 - resolve people across requesters, connectors, targets, investors and exports.

Outputs:
  analysis/output/person_resolution.csv   one row per person mention, with tier and evidence
  analysis/output/person_identities.csv   the export identity universe and its defects
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for halyard.matching

from common import io
from halyard.matching.normalize import norm_person, norm_ws
from halyard.matching.people import PersonResolver


def collect_person_mentions() -> pd.DataFrame:
    records: list[dict] = []

    requests = io.load_requests()
    for row in requests.itertuples():
        records.append(
            {
                "role": "requester",
                "source": "intro_requests.requested_by",
                "raw_name": norm_ws(row.requested_by),
                "org": "Halyard Systems",
                "title": norm_ws(row.requester_role),
                "context": row.request_id,
            }
        )
        if norm_ws(row.target_person_raw):
            records.append(
                {
                    "role": "target",
                    "source": "intro_requests.target_person_raw",
                    "raw_name": norm_ws(row.target_person_raw),
                    "org": norm_ws(row.target_company_raw),
                    "title": norm_ws(row.target_title_raw),
                    "context": row.request_id,
                }
            )

    for row in io.load_outcomes().itertuples():
        records.append(
            {
                "role": "connector_asked",
                "source": "intro_outcomes.connector_asked",
                "raw_name": norm_ws(row.connector_asked),
                "org": "Halyard Systems",
                "title": "",
                "context": row.request_id,
            }
        )

    for row in io.load_roster().itertuples():
        records.append(
            {
                "role": "roster_connector",
                "source": "connector_roster.name",
                "raw_name": norm_ws(row.name),
                "org": "Halyard Systems",
                "title": norm_ws(row.role),
                "context": norm_ws(row.type),
            }
        )

    for row in io.load_investors().itertuples():
        records.append(
            {
                "role": "investor_advisor",
                "source": "investor_network.person",
                "raw_name": norm_ws(row.person),
                "org": norm_ws(row.fund),
                "title": norm_ws(row.role),
                "context": norm_ws(row.portfolio_company),
            }
        )

    slack = io.slack_messages()
    for name in sorted(set(slack["user"].map(norm_ws))):
        records.append(
            {
                "role": "slack_participant",
                "source": "slack_threads.user",
                "raw_name": name,
                "org": "Halyard Systems",
                "title": "",
                "context": "",
            }
        )

    frame = pd.DataFrame(records)
    grouped = (
        frame.groupby(["role", "source", "raw_name", "org", "title"], dropna=False)
        .agg(mentions=("context", "size"), example_context=("context", "first"))
        .reset_index()
    )
    return grouped


def main() -> None:
    connections = io.load_connections()
    resolver = PersonResolver(connections)
    identities = resolver.identities()

    mentions = collect_person_mentions()
    rows = []
    for row in mentions.itertuples():
        match = resolver.resolve(row.raw_name, row.org, row.title)
        record = {
            "role": row.role,
            "source": row.source,
            "raw_name": row.raw_name,
            "normalized_name": norm_person(row.raw_name),
            "stated_org": row.org,
            "stated_title": row.title,
            "mentions": row.mentions,
            "example_context": row.example_context,
        }
        record.update(match.as_row())
        rows.append(record)
    resolution = pd.DataFrame(rows)

    io.write_csv(resolution, "person_resolution.csv")
    io.write_csv(identities, "person_identities.csv")

    print("export identities:", len(identities))
    print(identities["identity_basis"].value_counts().to_string())
    print("identities with conflicting affiliations:", int(identities["conflicting_affiliation"].sum()))
    print("\nmention resolution by role and tier:")
    print(resolution.groupby(["role", "match_tier"])["mentions"].sum().to_string())


if __name__ == "__main__":
    main()
