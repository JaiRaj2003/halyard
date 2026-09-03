"""Explainable account canonicalization.

Evidence hierarchy (per the approved methodology):

* an exact CRM ``account_id`` is definitive;
* a *unique* normalized domain is strong mapping evidence for external records;
* when several CRM account records share a domain they stay separate entities
  unless another identifier proves they are the same - the shared domain only
  buys them a ``domain_group`` label for review;
* conflicting domain / name / account-id evidence stays ambiguous.

Name similarity alone never collapses two accounts: subsidiaries, business
units and deliberately similar entities must survive the audit intact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from rapidfuzz import fuzz

from .normalize import company_core, norm_company, norm_domain, norm_ws


def canonical_key(value: object) -> str:
    """Whitespace/punctuation-insensitive identity key for a company string.

    Two strings share a key only when their normalized names are identical once
    legal suffixes and spacing are removed (``THORNBURYFINANCIAL`` ==
    ``Thornbury Financial``). Differing names - ``Blackwood Industrial`` vs
    ``Blackwood Holdings`` - always get different keys and stay separate
    entities.
    """
    return norm_company(value).replace(" ", "")


FUZZY_CANDIDATE_THRESHOLD = 88

TIER_EXACT_ID = "A_exact_crm_id"
TIER_EXACT_DOMAIN = "A_exact_unique_domain"
TIER_PROBABLE_NAME = "B_probable_name_exact"
TIER_PROBABLE_DOMAIN_GROUP = "B_probable_shared_domain_group"
TIER_SIMILAR_DISTINCT = "C_similar_but_distinct"
TIER_AMBIGUOUS = "D_ambiguous"
TIER_UNMATCHED = "E_unmatched"


@dataclass
class AccountMatch:
    tier: str
    account_id: str = ""
    account_name: str = ""
    domain_group: str = ""
    method: str = ""
    evidence: str = ""
    competing_candidates: list[str] = field(default_factory=list)

    def as_row(self) -> dict:
        return {
            "match_tier": self.tier,
            "canonical_account_id": self.account_id,
            "canonical_account_name": self.account_name,
            "domain_group": self.domain_group,
            "match_method": self.method,
            "match_evidence": self.evidence,
            "competing_candidates": "; ".join(self.competing_candidates),
        }


class AccountResolver:
    """Resolves free-text company strings against the CRM account universe."""

    def __init__(self, crm: pd.DataFrame):
        self.crm = crm.copy()
        self.crm["norm_name"] = self.crm["account_name"].map(norm_company)
        self.crm["norm_domain"] = self.crm["domain"].map(norm_domain)
        self.crm["core"] = self.crm["account_name"].map(company_core)

        self.crm["canonical_key"] = self.crm["account_name"].map(canonical_key)

        self._by_id = {norm_ws(r.account_id).casefold(): r for r in self.crm.itertuples()}
        self._by_domain: dict[str, list] = {}
        self._by_name: dict[str, list] = {}
        for row in self.crm.itertuples():
            self._by_domain.setdefault(row.norm_domain, []).append(row)
            self._by_name.setdefault(row.canonical_key, []).append(row)

    # -- CRM-internal structure -------------------------------------------------
    def domain_groups(self) -> pd.DataFrame:
        """CRM accounts grouped by shared normalized domain.

        Rows in a group of size > 1 are *probable* duplicates only. They are
        reported, never merged: the audit has no identifier proving they are the
        same legal entity, and collapsing them could hide a real subsidiary.
        """
        records = []
        for domain, rows in sorted(self._by_domain.items()):
            group_id = f"DG_{domain}" if len(rows) > 1 else ""
            for row in rows:
                same_name = len({r.norm_name for r in rows}) == 1
                records.append(
                    {
                        "account_id": row.account_id,
                        "account_name": row.account_name,
                        "domain": row.domain,
                        "normalized_domain": domain,
                        "normalized_name": row.norm_name,
                        "industry": row.industry,
                        "hq": row.hq,
                        "employee_count": row.employee_count,
                        "owner": row.owner,
                        "stage": row.stage,
                        "domain_group": group_id,
                        "domain_group_size": len(rows),
                        "duplicate_class": (
                            "unique_domain"
                            if len(rows) == 1
                            else ("probable_duplicate_same_normalized_name" if same_name else "shared_domain_distinct_names")
                        ),
                        "resolution": (
                            "canonical"
                            if len(rows) == 1
                            else "kept_separate_pending_identifier_evidence"
                        ),
                    }
                )
        return pd.DataFrame(records)

    def similar_but_distinct_pairs(self) -> pd.DataFrame:
        """CRM pairs that look alike but have conflicting discriminators."""
        rows = list(self.crm.itertuples())
        records = []
        for i, left in enumerate(rows):
            for right in rows[i + 1 :]:
                if left.norm_domain == right.norm_domain:
                    continue
                score = round(fuzz.token_sort_ratio(left.norm_name, right.norm_name), 1)
                shares_core = bool(left.core) and left.core == right.core
                if score < FUZZY_CANDIDATE_THRESHOLD and not shares_core:
                    continue
                discriminators = []
                if left.norm_domain != right.norm_domain:
                    discriminators.append(f"domain {left.domain} != {right.domain}")
                if left.industry != right.industry:
                    discriminators.append(f"industry {left.industry} != {right.industry}")
                if left.hq != right.hq:
                    discriminators.append(f"hq {left.hq} != {right.hq}")
                if left.employee_count != right.employee_count:
                    discriminators.append(f"employees {left.employee_count} != {right.employee_count}")
                records.append(
                    {
                        "account_id_a": left.account_id,
                        "account_name_a": left.account_name,
                        "account_id_b": right.account_id,
                        "account_name_b": right.account_name,
                        "name_similarity": score,
                        "shared_name_core": shares_core,
                        "discriminators": "; ".join(discriminators),
                        "verdict": TIER_SIMILAR_DISTINCT if discriminators else TIER_AMBIGUOUS,
                    }
                )
        return pd.DataFrame(records)

    # -- external record resolution ---------------------------------------------
    def resolve(self, raw_value: object, domain_hints: list[str] | None = None) -> AccountMatch:
        raw = norm_ws(raw_value)
        if not raw:
            return AccountMatch(TIER_UNMATCHED, method="empty_value", evidence="no company string supplied")

        key = raw.casefold()
        if key in self._by_id:
            row = self._by_id[key]
            return AccountMatch(
                TIER_EXACT_ID,
                row.account_id,
                row.account_name,
                method="crm_account_id",
                evidence=f"exact CRM account_id {row.account_id}",
            )

        for hint in domain_hints or []:
            rows = self._by_domain.get(norm_domain(hint), [])
            if len(rows) == 1:
                row = rows[0]
                return AccountMatch(
                    TIER_EXACT_DOMAIN,
                    row.account_id,
                    row.account_name,
                    method="unique_domain",
                    evidence=f"domain {hint} maps to exactly one CRM account",
                )
            if len(rows) > 1:
                return AccountMatch(
                    TIER_PROBABLE_DOMAIN_GROUP,
                    domain_group=f"DG_{norm_domain(hint)}",
                    method="shared_domain",
                    evidence=f"domain {hint} is shared by {len(rows)} CRM accounts; entity not determined",
                    competing_candidates=[f"{r.account_id}:{r.account_name}" for r in rows],
                )

        normalized = norm_company(raw)
        exact = self._by_name.get(canonical_key(raw), [])
        if len(exact) == 1:
            row = exact[0]
            return AccountMatch(
                TIER_PROBABLE_NAME,
                row.account_id,
                row.account_name,
                domain_group=f"DG_{row.norm_domain}" if len(self._by_domain[row.norm_domain]) > 1 else "",
                method="normalized_name_exact",
                evidence=f"normalized name '{normalized}' matches one CRM account",
            )
        if len(exact) > 1:
            domains = {r.norm_domain for r in exact}
            if len(domains) == 1:
                return AccountMatch(
                    TIER_PROBABLE_DOMAIN_GROUP,
                    domain_group=f"DG_{domains.pop()}",
                    method="normalized_name_exact_shared_domain",
                    evidence=f"name '{normalized}' matches {len(exact)} CRM records sharing one domain",
                    competing_candidates=[f"{r.account_id}:{r.account_name}" for r in exact],
                )
            return AccountMatch(
                TIER_AMBIGUOUS,
                method="normalized_name_exact_conflicting_domains",
                evidence=f"name '{normalized}' matches {len(exact)} CRM records with different domains",
                competing_candidates=[f"{r.account_id}:{r.account_name}" for r in exact],
            )

        core = company_core(raw)
        scored = []
        for row in self.crm.itertuples():
            score = round(fuzz.token_sort_ratio(normalized, row.norm_name), 1)
            if score >= FUZZY_CANDIDATE_THRESHOLD or (core and core == row.core):
                scored.append((score, row))
        if not scored:
            return AccountMatch(
                TIER_UNMATCHED,
                method="no_candidate",
                evidence=f"'{raw}' has no CRM account within similarity threshold",
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        candidates = [f"{row.account_id}:{row.account_name}({score})" for score, row in scored]
        best_score, best = scored[0]
        if best_score >= 97 and len({row.norm_name for _, row in scored}) == 1:
            return AccountMatch(
                TIER_PROBABLE_NAME,
                best.account_id,
                best.account_name,
                method="near_exact_name",
                evidence=f"similarity {best_score} to '{best.account_name}', no competing candidate",
                competing_candidates=candidates[1:],
            )
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return AccountMatch(
                TIER_AMBIGUOUS,
                method="tied_fuzzy_candidates",
                evidence=f"'{raw}' ties between multiple CRM accounts at similarity {best_score}",
                competing_candidates=candidates,
            )
        return AccountMatch(
            TIER_SIMILAR_DISTINCT,
            method="similar_name_conflicting_evidence",
            evidence=(
                f"'{raw}' resembles CRM account '{best.account_name}' but no domain or id evidence supports "
                "the same entity; treated as a distinct entity with no CRM record"
            ),
            competing_candidates=candidates,
        )
