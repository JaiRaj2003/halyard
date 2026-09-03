# Entity resolution

Conservative, provenance-preserving matching. Every mention keeps its tier,
method, evidence string and competing candidates, so a reader can always see
*why* two records were joined — or deliberately not joined.

Implementation: `halyard/matching/` — `accounts.py`, `people.py`, `slack.py`
and `normalize.py`. This is a single shared package: the forensic audit
(`analysis/audit/`) and the application's ingestion both import it, so the
product cannot drift away from the analysis that justified it.

## Accounts

Normalisation strips accents and transliterates (`ø→o`, `ß→ss`, …), lowercases,
removes punctuation and drops legal suffixes (`inc`, `ltd`, `gmbh`, `holdings`
is **not** treated as a suffix). Domains are lowercased with `www.` and the
scheme removed.

| Tier | Meaning |
| --- | --- |
| `A_exact_crm_id` | the mention *is* a CRM `account_id` — definitive |
| `A_exact_unique_domain` | domain matches exactly one CRM record — strong mapping evidence |
| `B_probable_name_exact` | canonical name matches exactly one CRM record |
| `B_probable_shared_domain_group` | name/domain matches a group of CRM records sharing a domain; resolved to the **group**, never to one id |
| `C_similar_but_distinct` | high string similarity but disqualifying evidence (different domain, different country, different industry) — kept apart |
| `D_ambiguous` | conflicting name/domain/id evidence — left unresolved |
| `E_unmatched` | no CRM candidate |

Rules the resolver enforces:

- A shared normalised domain never collapses two CRM `account_id`s. The six
  shared-domain CRM pairs in this corpus stay separate and are exported as
  groups in `analysis/output/account_crm_groups.csv`.
- Subsidiaries and look-alikes are protected by the `C_similar_but_distinct`
  tier: "Apex Holdings" and "Apex Logistics" score highly on string similarity
  and are explicitly held apart (regression test in
  `analysis/tests/test_matching.py`).
- Fuzzy name similarity alone never produces a match; it produces a candidate
  pair in `analysis/output/account_similar_pairs.csv` for human review.

Result on the request spine: 92 `B_probable_name_exact`, 71 `E_unmatched`,
21 `C_similar_but_distinct`, 14 `B_probable_shared_domain_group`,
2 `D_ambiguous`.

## People

Person identity is built from the six connection exports plus the roster,
investor network, outcomes and Slack participants.

| Tier | Meaning |
| --- | --- |
| `T1_unique_identifier` | profile URL match — the strongest identifier available |
| `T2_ambiguous_name_collision` | the name maps to several distinct identities — unresolved |
| `T3_name_plus_org` | exact name corroborated by organisation (or a name with exactly one identity in the universe) |
| `T4_composite_name_title` | exact name corroborated by title family only |
| `T5_fuzzy_candidate_review` | near-identical name — **review only, never treated as a match** |
| `T6_unmatched` | no candidate identity |

Notes:

- Several export rows can describe one identity (two connectors knowing the same
  person). Rows are collapsed on identity before ambiguity is judged.
- Title families (`executive`, `revenue`, `engineering`, …) are corroborating
  evidence only; they never resolve an identity on their own.
- Requested buyers are essentially unresolvable in this corpus: 199/200 target
  people are `T6_unmatched`, 1 is `T5` review-only. This is a finding, not a
  matcher defect — the requested people simply do not appear in the network
  exports.

## Outputs

| File | Contents |
| --- | --- |
| `account_resolution.csv` | every account mention with tier, method, evidence, competing candidates |
| `account_crm_groups.csv` | CRM records grouped by shared domain, kept distinct |
| `account_similar_pairs.csv` | high-similarity pairs flagged for review, with the disqualifying evidence |
| `account_canonical.csv` | canonical account list with mention counts by source |
| `person_resolution.csv` | every person mention with tier, method, evidence |
| `person_identities.csv` | identity universe, with conflicting-affiliation and missing-URL flags |

## In the application

The same tiers drive canonical rows, and ambiguity survives ingestion instead of
being resolved away:

- Every decision — resolved, ambiguous or unmatched — is written to
  `entity_matches` with its tier, method, evidence and competing candidates.
  The current build records 92 resolved, 17 ambiguous and 126 unmatched.
- An ambiguous account or target sends the request to `NEEDS_ENTITY_REVIEW`
  with the candidates attached. It is never silently assigned to the best guess.
- Shared-domain CRM accounts stay separate rows in a common `domain_group`;
  `GET /api/accounts/{id}` shows the siblings explicitly. Twelve
  `crm_shared_domain` data-quality rows record the overlap.
- **Unresolved target intent never becomes a person.** "VP of Security at Acme"
  is a `RequestTarget` with a title family and an account; 199 of the 200
  historical targets are unresolved this way, and no `Person` is fabricated for
  any of them.
- Live input may create a `Person`, but only for a named individual supplied and
  confirmed at intake, recorded with `source_type='live_input'`,
  `identity_basis='live_input'` and medium confidence. A name that collides with
  existing identities is written as `needs_review` with its competitors listed,
  not merged.
- 278 export rows have no profile URL. They resolve on name plus company at
  `name_only_export` and carry a low-severity `missing_profile_url` issue, so
  the weaker basis is visible wherever they are used.
