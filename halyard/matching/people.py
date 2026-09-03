"""Tiered person resolution.

Tiers, strongest first:

* ``T1_unique_identifier``  - exact normalized ``profile_url``
* ``T3_name_plus_org``      - exact normalized name corroborated by organization
* ``T4_composite``          - exact normalized name corroborated by title family
* ``T5_fuzzy_candidate``    - near-identical name only; surfaced for review, never applied
* ``T2_ambiguous_name``     - exact name matching several distinct identities
* ``T6_unmatched``          - no candidate

The corpus carries no email addresses, so the T2 email tier of the plan is not
exercised; profile URLs are the only unique identifier available.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from rapidfuzz import fuzz, process

from .accounts import canonical_key
from .normalize import norm_person, norm_url, norm_ws, title_family

FUZZY_NAME_THRESHOLD = 92

T1 = "T1_unique_identifier"
T3 = "T3_name_plus_org"
T4 = "T4_composite_name_title"
T5 = "T5_fuzzy_candidate_review"
T_AMBIGUOUS = "T2_ambiguous_name_collision"
T6 = "T6_unmatched"


@dataclass
class PersonMatch:
    tier: str
    person_key: str = ""
    display_name: str = ""
    method: str = ""
    evidence: str = ""
    candidates: list[str] = field(default_factory=list)

    def as_row(self) -> dict:
        return {
            "match_tier": self.tier,
            "resolved_person_key": self.person_key,
            "resolved_display_name": self.display_name,
            "match_method": self.method,
            "match_evidence": self.evidence,
            "competing_candidates": "; ".join(self.candidates),
        }


class PersonResolver:
    """Resolves person mentions against the connection-export identity universe."""

    def __init__(self, connections: pd.DataFrame):
        frame = connections.copy()
        frame["norm_name"] = frame["name"].map(norm_person)
        frame["norm_url"] = frame["profile_url"].map(norm_url)
        frame["org_key"] = frame["company"].map(canonical_key)
        frame["title_family"] = frame["title"].map(title_family)
        self.connections = frame

        self.by_url: dict[str, list] = {}
        self.by_name: dict[str, list] = {}
        for row in frame.itertuples():
            if row.norm_url:
                self.by_url.setdefault(row.norm_url, []).append(row)
            self.by_name.setdefault(row.norm_name, []).append(row)
        self._name_choices = list(self.by_name)

    def identities(self) -> pd.DataFrame:
        """One row per distinct identity key, with the evidence behind the key.

        An identity key is the profile URL when present, otherwise the
        normalized name; name-only identities are explicitly weaker and are
        flagged as such.
        """
        records = []
        for name, rows in sorted(self.by_name.items()):
            urls = sorted({r.norm_url for r in rows if r.norm_url})
            orgs = sorted({r.company for r in rows})
            titles = sorted({r.title for r in rows})
            connectors = sorted({r.connector for r in rows})
            records.append(
                {
                    "person_key": urls[0] if len(urls) == 1 else f"name:{name}",
                    "identity_basis": "profile_url" if len(urls) == 1 else ("name_only" if not urls else "multiple_urls"),
                    "normalized_name": name,
                    "display_name": rows[0].name,
                    "profile_urls": "; ".join(urls),
                    "organizations": "; ".join(orgs),
                    "titles": "; ".join(titles),
                    "appears_in_exports": "; ".join(connectors),
                    "export_rows": len(rows),
                    "distinct_orgs": len(orgs),
                    "conflicting_affiliation": len(orgs) > 1,
                    "missing_profile_url": sum(1 for r in rows if not r.norm_url),
                }
            )
        return pd.DataFrame(records)

    def resolve(self, name: object, org: object = "", title: object = "", url: object = "") -> PersonMatch:
        normalized_url = norm_url(url)
        if normalized_url and normalized_url in self.by_url:
            rows = self.by_url[normalized_url]
            return PersonMatch(T1, normalized_url, rows[0].name, "profile_url", f"exact profile_url {normalized_url}")

        normalized = norm_person(name)
        if not normalized:
            return PersonMatch(T6, method="empty_value", evidence="no person name supplied")

        rows = self.by_name.get(normalized, [])
        if rows:
            org_key = canonical_key(org)
            org_matches = [r for r in rows if org_key and r.org_key == org_key]
            # Several export rows can describe one identity (two connectors who
            # both know the same person); collapse on identity before judging
            # ambiguity.
            if len({r.norm_url or f"{r.org_key}|{r.title_family}" for r in org_matches}) == 1:
                org_matches = org_matches[:1]
            if len(org_matches) == 1:
                row = org_matches[0]
                return PersonMatch(
                    T3,
                    row.norm_url or f"name:{normalized}",
                    row.name,
                    "name_plus_org",
                    f"name '{norm_ws(name)}' corroborated by organization '{norm_ws(org)}'",
                )
            if len(org_matches) > 1:
                return PersonMatch(
                    T_AMBIGUOUS,
                    method="name_org_multiple_rows",
                    evidence=f"name + organization matches {len(org_matches)} export rows",
                    candidates=sorted({f"{r.connector}:{r.profile_url}" for r in org_matches}),
                )
            family = title_family(title)
            title_matches = [r for r in rows if family and r.title_family == family]
            if len(title_matches) == 1:
                row = title_matches[0]
                return PersonMatch(
                    T4,
                    row.norm_url or f"name:{normalized}",
                    row.name,
                    "name_plus_title_family",
                    f"name matches and title family '{family}' corroborates; organization differs or is unknown",
                )
            distinct = {r.norm_url or r.company for r in rows}
            if len(distinct) == 1:
                row = rows[0]
                return PersonMatch(
                    T3,
                    row.norm_url or f"name:{normalized}",
                    row.name,
                    "name_exact_single_identity",
                    "name matches exactly one identity in the export universe; organization not corroborated",
                )
            return PersonMatch(
                T_AMBIGUOUS,
                method="name_collision",
                evidence=f"name '{norm_ws(name)}' matches {len(distinct)} distinct identities; not resolved",
                candidates=sorted({f"{r.company}|{r.title}|{r.profile_url}" for r in rows})[:6],
            )

        best = process.extractOne(normalized, self._name_choices, scorer=fuzz.token_sort_ratio)
        if best and best[1] >= FUZZY_NAME_THRESHOLD:
            rows = self.by_name[best[0]]
            return PersonMatch(
                T5,
                method="fuzzy_name_only",
                evidence=f"near-identical name '{rows[0].name}' (similarity {round(best[1], 1)}); requires human review",
                candidates=[f"{r.name}|{r.company}|{r.profile_url}" for r in rows][:6],
            )
        return PersonMatch(T6, method="no_candidate", evidence=f"'{norm_ws(name)}' has no identity in the export universe")
