"""Step 02 - canonicalize accounts and record every mapping decision.

Outputs:
  analysis/output/account_resolution.csv      one row per distinct company string per source
  analysis/output/account_crm_groups.csv      CRM-internal duplicate / domain-group structure
  analysis/output/account_similar_pairs.csv   look-alike CRM entities deliberately held apart
  analysis/output/account_canonical.csv       canonical entity per distinct company identity
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import io
from common.accounts import AccountResolver, canonical_key
from common.normalize import extract_domains, norm_ws


def collect_company_mentions() -> pd.DataFrame:
    """Every free-text company string in the corpus, with a domain hint when the
    surrounding text supplies one."""
    mentions: dict[tuple[str, str], dict] = {}
    hints: dict[str, set[str]] = defaultdict(set)

    requests = io.load_requests()
    slack = io.slack_messages()
    slack_text_by_request = slack.groupby("request_id")["text"].apply(" \n".join).to_dict()

    for row in requests.itertuples():
        company = norm_ws(row.target_company_raw)
        text = f"{norm_ws(row.raw_ask)} {slack_text_by_request.get(row.request_id, '')}"
        for domain in extract_domains(text):
            if company:
                hints[company.casefold()].add(domain)
        if not company:
            continue
        key = ("intro_requests.target_company_raw", company.casefold())
        entry = mentions.setdefault(key, {"source": key[0], "raw_value": company, "occurrences": 0})
        entry["occurrences"] += 1

    for row in io.load_connections().itertuples():
        company = norm_ws(row.company)
        if not company:
            continue
        key = ("connections.company", company.casefold())
        entry = mentions.setdefault(key, {"source": key[0], "raw_value": company, "occurrences": 0})
        entry["occurrences"] += 1

    investors = io.load_investors()
    for column, label in (("portfolio_company", "investor_network.portfolio_company"), ("prior_employer", "investor_network.prior_employer")):
        for value in investors[column].dropna():
            company = norm_ws(value)
            if not company:
                continue
            key = (label, company.casefold())
            entry = mentions.setdefault(key, {"source": label, "raw_value": company, "occurrences": 0})
            entry["occurrences"] += 1

    frame = pd.DataFrame(mentions.values())
    frame["domain_hints"] = frame["raw_value"].map(lambda v: sorted(hints.get(v.casefold(), set())))
    return frame.sort_values(["source", "raw_value"], ignore_index=True)


def build_canonical_entities(resolution: pd.DataFrame) -> pd.DataFrame:
    """One row per distinct company identity across the whole corpus.

    Identity is the whitespace-insensitive normalized name. Distinct names stay
    distinct entities; CRM linkage is an attribute of an entity, not its
    identity, so an entity may map to zero, one, or an unresolved group of CRM
    account records.
    """
    records = []
    for key, group in resolution.groupby("canonical_key", sort=True):
        tiers = set(group["match_tier"])
        crm_ids = sorted({v for v in group["canonical_account_id"].dropna() if v})
        competing = sorted({c for row in group["competing_candidates"].dropna() for c in row.split("; ") if c})
        if crm_ids:
            crm_link = "linked_single_crm_account" if len(crm_ids) == 1 else "conflicting_crm_links"
        elif "B_probable_shared_domain_group" in tiers:
            crm_link = "linked_to_shared_domain_group_account_id_unresolved"
        elif "D_ambiguous" in tiers:
            crm_link = "ambiguous_crm_candidates"
        elif "C_similar_but_distinct" in tiers:
            crm_link = "distinct_from_lookalike_crm_account"
        else:
            crm_link = "no_crm_record"
        records.append(
            {
                "canonical_key": key,
                "display_name": group.sort_values("occurrences", ascending=False)["raw_value"].iloc[0],
                "name_variants": "; ".join(sorted(set(group["raw_value"]))),
                "sources": "; ".join(sorted(set(group["source"]))),
                "mentions": int(group["occurrences"].sum()),
                "crm_link": crm_link,
                "crm_account_ids": "; ".join(crm_ids),
                "crm_candidate_ids": "; ".join(competing),
                "domain_group": "; ".join(sorted({d for d in group["domain_group"].dropna() if d})),
                "match_tiers": "; ".join(sorted(tiers)),
            }
        )
    return pd.DataFrame(records)


def main() -> None:
    crm = io.load_crm()
    resolver = AccountResolver(crm)

    groups = resolver.domain_groups()
    similar = resolver.similar_but_distinct_pairs()

    mentions = collect_company_mentions()
    rows = []
    for row in mentions.itertuples():
        match = resolver.resolve(row.raw_value, list(row.domain_hints))
        record = {
            "source": row.source,
            "raw_value": row.raw_value,
            "occurrences": row.occurrences,
            "domain_hints": "; ".join(row.domain_hints),
        }
        record.update(match.as_row())
        rows.append(record)
    resolution = pd.DataFrame(rows)
    resolution.insert(2, "canonical_key", resolution["raw_value"].map(canonical_key))
    canonical = build_canonical_entities(resolution)

    io.write_csv(resolution, "account_resolution.csv")
    io.write_csv(groups, "account_crm_groups.csv")
    io.write_csv(similar, "account_similar_pairs.csv")
    io.write_csv(canonical, "account_canonical.csv")

    print("canonical entities across corpus:", len(canonical))
    print(canonical["crm_link"].value_counts().to_string())
    print("\ncanonical CRM account records:", len(groups))
    print("distinct normalized domains:", groups["normalized_domain"].nunique())
    print(groups["duplicate_class"].value_counts().to_string())
    print("\nresolution tiers by source:")
    print(resolution.groupby(["source", "match_tier"]).size().to_string())
    if len(similar):
        print("\nlook-alike CRM pairs held apart:", len(similar))
        print(similar[["account_name_a", "account_name_b", "name_similarity", "verdict"]].to_string(index=False))


if __name__ == "__main__":
    main()
