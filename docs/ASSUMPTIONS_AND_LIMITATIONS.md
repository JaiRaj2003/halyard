# Assumptions and limitations

Assumptions that could bias the findings, and what would change if they are wrong.

## Assumptions

1. **"Today" is 2026-08-10**, the latest activity observed anywhere in the
   corpus. If the real current date is later, every staleness figure understates
   the problem.
2. **`intro_requests.csv` (200 rows) is the authoritative request universe.**
   Slack was reconciled against it independently and maps 1:1 (0 orphan threads,
   0 unmapped outcome rows), so no out-of-spine bucket was required.
3. **A missing `intro_outcomes` row means "no connector of record", not
   "failed".** 115 requests are treated as *unknown owner*. If routing happens
   off-system, the ownership gap is smaller than reported — but the visibility
   gap is identical, because nothing in the supplied data records it.
4. **A self-declared `status` is the weakest form of evidence.** State is taken
   from an outcome event first, an explicit Slack statement second, and the
   declared status only when nothing stronger exists (marked `declared_only:`,
   confidence `low`).
5. **Slack recency is activity, never state.** A silent request is stale, not
   closed; a request can be `unknown` and `potentially_stale` at once.
6. **Historical path availability requires a date.** Export edges count only when
   `connected_on <= request_date`; investor/advisor edges have no dates and are
   reported as snapshot-only.
7. **Year-only employment dates are coarsened to 1 January** of that year, used
   solely to test whether a relationship pre-dates a request. This is generous
   by up to 11 months at the boundary.
8. **A shared domain never merges two CRM accounts.** Subsidiaries and business
   units are held apart at the cost of some genuine duplicates being missed.
9. **A "path" is at account granularity.** Nobody in the corpus knows the
   requested buyer, so every path is a colleague at the target account —
   a lead, not a guaranteed introduction.
10. **Title families** (executive / revenue / engineering / …) are corroborating
    evidence only and never resolve an identity on their own.

## Limitations of the supplied data

- **No meeting dates.** `intro→meeting` latency is not computable; reported as
  such rather than omitted.
- **No connector availability, seniority of relationship, or relationship
  strength.** Capacity is a stated monthly number only; there is no signal for
  how willing a connector is to make a given intro.
- **No decline reasons and no closure events.** Terminal state exists only when
  an outcome column happens to record it.
- **Investor/advisor network has no temporal information at all** for portfolio
  and board edges (73 records, 154 snapshot-only path edges).
- **36.6% of candidate path edges depend on people Halyard has no proven route
  to** — investor-network people who are neither on the roster nor in any export.
- **11 connectors appear in outcomes but only 6 are on the roster.** Capacity
  analysis covers the 6 roster connectors; the other 5 have 1 ask each and no
  stated capacity.
- **Single-year, single-company corpus.** Rates observed here may not generalise
  to other teams or periods.
- **The `raw_ask` free text is the only signal for re-asks.** A repeat ask that
  does not say so is invisible; 21% is a floor, not a ceiling.
- **No cost data**, so "impact" is expressed as requested `deal_value_usd`, which
  is an ask-time estimate, not booked revenue.

## Things deliberately not done

- No imputation of missing outcomes; unknown stays unknown.
- No collapsing of similar account names without a disqualifying-evidence check.
- No fuzzy person match promoted to a resolved identity.
- No claim that an undated relationship existed at a historical request date.
- No product built. This phase is evidence only.
