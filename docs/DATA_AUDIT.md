# Halyard warm-introduction data audit

Programmatic audit of the supplied corpus. Every number below is produced by
`python analysis/audit/run_audit.py` and lands in `analysis/output/`; nothing
here is asserted from intuition. No product has been built.

Reference "today" for all recency maths: **2026-08-10**, the latest activity
observed anywhere in the corpus (`analysis/output/audit_reference_date.json`).

---

## 1. What was parsed

| Source | Records | Role in the audit |
| --- | --- | --- |
| `intro_requests.csv` | 200 | authoritative request spine (denominator for every request-level rate) |
| `intro_outcomes.csv` | 85 | the only evidence that a connector was actually asked |
| `slack_threads.jsonl` | 200 threads / 523 messages | activity and explicit state statements; reconciled against the spine, never added to it |
| `crm_accounts.csv` | 50 | account identity |
| `connector_roster.csv` | 6 | connector identity, type, stated monthly capacity |
| `investor_network.csv` | 73 | investor/advisor edges (no connection dates) |
| `connections_*.csv` (6 files) | 5,075 | connector network exports, each edge dated with `connected_on` |

Per-column profiling (nulls, uniqueness, join-key candidacy, whitespace/casing
defects, malformed names, date ranges, duplicates) is in
`analysis/output/source_profile.csv`.

### Slack reconciliation against the spine

| Check | Count |
| --- | --- |
| requests in spine | 200 |
| requests without a Slack thread | 0 |
| Slack threads without a request row | 0 |
| requests with multiple Slack threads | 0 |
| threads containing an additional ask-like message | 0 |
| outcome rows not mappable to the spine | 0 |
| duplicate outcome rows per request | 0 |

The request table is **not** materially incomplete: Slack maps 1:1 onto it. So
the 200-row denominator stands, and no "out-of-spine" bucket was needed.

---

## 2. The funnel

| Stage | Count | Denominator | % |
| --- | --- | --- | --- |
| requests | 200 | 200 | 100.0 |
| any Slack reply | 157 | 200 | 78.5 |
| substantive Slack reply (not a bump / "no idea") | 44 | 200 | 22.0 |
| routed to a named connector | 85 | 200 | 42.5 |
| connector responded | 55 | 200 | 27.5 |
| intro sent | 32 | 200 | 16.0 |
| meeting booked | 14 | 200 | 7.0 |
| opportunity created | 7 | 200 | 3.5 |

Latency, each with its coverage (`analysis/output/request_latency.csv`):
request→first Slack reply median 1d (157/200); request→connector asked median
3d (85/200); connector asked→response median 6d, p90 11d (55/200);
request→intro median 16d (32/200). `intro→meeting` is **not computable** — no
meeting date is recorded anywhere in the corpus.

The single largest drop is between "someone replied in Slack" (78.5%) and
"a named connector was actually asked" (42.5%). Chatter is plentiful; assignment
is not.

---

## 3. Hypotheses tested

### H1 — Missed warm paths (time-aware)

Two measures, never conflated. A path is **time-aware available** only when a
date proves the relationship pre-dated the request (`connected_on <=
request_date`, or `prior_employer_start <= request_date`). Investor/advisor
portfolio edges carry no dates and can therefore only ever be
"visible in the supplied current snapshot; historical availability unknown".

- 97/200 (48.5%) requests had at least one time-aware candidate path.
- 109/200 (54.5%) have at least one path in the current snapshot.
- 12/200 have snapshot-only paths, i.e. paths that cannot be claimed historically.
- **46/109 (42.2%)** requests declared "No path found" / "Unknown" / "Closed - no
  path" had a time-aware connection into the target account.
- 48 export edges post-date their request and are correctly excluded.

Caveat that materially weakens the pure "missed path" story: **0/200 requests
have a connector connected to the requested person themselves** (199/200 target
people do not appear in any export at all). Every observable path is to a
*colleague* at the account, so "a path existed" means "a lead worth checking",
not "an intro was available". `candidate_paths.csv` carries per-edge
`confidence` and `limitations` for exactly this reason.

### H2 — Connector concentration and overuse — **not supported**

- Only **2/49 connector-months** exceed the connector's own stated monthly
  capacity (both Priya Raghunathan: 4 asks vs capacity 3).
- Recorded asks: Raghunathan 21, Beckett 20, Duvall 17, Aldridge 15, Whitfield 4,
  Trask 3 — spread over ~12 months, i.e. ~1.75/month at the top.
- Top-2 connectors hold 48.2% of recorded asks, so load is *skewed*, but nobody
  is near their stated ceiling. Response rates do not collapse with load
  (Raghunathan 66.7%, Beckett 70.0%, Aldridge 53.3%).

The intuitive "we're burning out our connectors" narrative is the one hypothesis
the data actively contradicts. The bottleneck is upstream of the connectors.

### H3 — Execution and ownership failure — **strongly supported**

- 115/200 (57.5%) requests have **no connector of record at all**.
- 111/200 (55.5%) have no state evidence beyond the self-declared `status` field.
- 159/200 (79.5%) are unresolved *and* silent for 30+ days — **$106.5M of the
  $137.8M** total requested pipeline.
- 23 requests have a connector who responded, no intro, and no recorded closure.
- Critical-urgency requests are barely better off than low-urgency ones:
  71% vs 88% unresolved-and-silent. Urgency does not change what happens.

### H4 — Duplicate / overlapping requests — supported, but as a symptom

- 200 requests cover only **51 canonical target accounts**; 144/200 sit on an
  account with more than one request.
- 114/200 requests belong to a same-account pair filed within 90 days.
- **42/200 (21%) asks say in their own text that they are repeats** ("asking
  again: …"). Of the 31 that have an identifiable earlier ask for the same
  account, 14 had a prior ask that was never routed and 26 had a prior ask with
  no terminal evidence. People re-ask because the first ask disappeared.
- Of 286 same-account pairs, none target the same named person and 26 target the
  same title family. These are not naive duplicates — they are uncoordinated
  parallel attacks on one account.

### H5 — Data trust / entity resolution — supported

- 150/200 (75%) requests carry at least one contradiction
  (`status_contradictions.csv`); 54 of 217 findings are high severity:
  - 14 closed as "no path" while a pre-dating connection exists;
  - 14 declaring "Intro sent" with no outcome row anywhere;
  - 13 declaring "Routed" with no connector or asked date;
  - 9 flagged "No path found" with a time-aware path;
  - 4 declaring "Intro sent" contradicted by their own outcome row.
- 5 of 11 recorded connectors are absent from the roster — including
  Imani Mkhize, who elsewhere in the corpus *files* requests.
- 94/200 requests name a target that does not resolve cleanly to a CRM account;
  6 CRM pairs share a domain and are held apart deliberately.
- 199/200 requested buyers cannot be resolved to any known identity.

### H6 — Leadership visibility — strongly supported

`analysis/output/leadership_observability.csv`, share of the 200 requests a
leader could answer from the data as supplied:

| Question | Answerable | % | Pipeline unanswerable |
| --- | --- | --- | --- |
| What is the real state of this request? | 89 | 44.5% | $75.5M |
| Who owns the next action right now? | 85 | 42.5% | $79.2M |
| What is the next action? | 35 | 17.5% | $112.8M |
| Is this alive or quietly dead? | 41 | 20.5% | $106.5M |
| Do we have a warm path into this account? | 109 | 54.5% | $56.4M |
| Does the record itself say whether a path exists? | 145 | 72.5% | $39.7M |

### H7 — Surprising cross-source patterns

Full list in `analysis/output/cross_source_findings.csv`. The three that changed
the conclusion:

1. **Connector capacity is not the constraint** (2/49 connector-months over
   capacity) while 83.7% of roster connector-request pairs with an observable
   time-aware path were never asked. Supply of paths hugely exceeds demand
   placed on connectors.
2. **No connector knows any requested buyer** (0/200). The network data answers
   "who do we know at the account", never "can you introduce this person" — any
   product that promises the latter is over-claiming.
3. **36.6% of candidate path edges run through investor/advisor people who are
   neither on the roster nor in any export** — Halyard has no proven route to
   the connector that the path depends on.

---

## 4. Three concrete examples

**R1017 / R1107 — Vireo Systems, same requester, one day apart.**
Nadia Okonkwo filed R1017 (2025-11-06, $250k) and R1107 (2025-11-05, $750k)
against the same account. R1017 was closed as "Closed - no path"; R1107 had a
connector respond, and its status claims "Intro sent" while its own outcome row
records `intro_sent=N`. Both had the same time-aware path (Marcus Aldridge).
One account, two requesters' worth of effort, three mutually inconsistent
answers, 273 days of silence.

**R1093 — $1.2M, closed as "no path" with nine pre-dating connections.**
Declared `Closed - no path`, yet six connectors (Elena Duvall, Marcus Aldridge,
Tomás Beckett and three investor-network alumni) held connections into the
account dated before the request. Derived state from the outcome row is actually
`asked_awaiting_connector_response` — the record closed itself while the ask was
still open.

**R1024 / R1180 — $2.0M each, status "Routed", nobody routed.**
Both declare `Routed` with no connector, no asked date and no outcome row of any
kind. There is no person in the corpus who can be said to own either request,
and neither has shown activity in over a month.

---

## 5. Five metrics that matter most

1. **159/200 (79.5%) requests are unresolved and silent for 30+ days**, carrying
   **$106.5M of $137.8M** requested pipeline.
2. **115/200 (57.5%) requests have no connector of record**; 85/200 were ever
   routed at all.
3. **150/200 (75%) requests contain at least one internal contradiction**;
   54 of those findings are high severity.
4. **46/109 (42.2%)** requests declared no-path/unknown had a connection into the
   account that pre-dated the request.
5. **Only 2/49 connector-months exceeded stated capacity** — the assumed
   bottleneck is not real.

---

## 6. Strongest competing hypothesis

*"The real problem is missed warm paths: 42% of the requests written off as 'no
path' had one, so a path-finding engine is the product."*

It is the best-supported alternative and it survives the time-aware test. Two
things keep it in second place:

- The paths are second-hop. 0/200 requests have a connector who knows the
  requested buyer; every path is "someone we know works there". Converting that
  into an intro still requires a human to be asked, to answer, and to be tracked
  — which is precisely the machinery that is missing.
- Path discovery only pays off when the answer is acted on. 83.7% of observable
  connector-request path pairs were never asked, and 57.5% of requests never
  reached a connector at all. Better search feeding the same broken hand-off
  would raise suggestions, not intros.

A weaker competing hypothesis — connector overload — is contradicted outright.

## 7. Most surprising finding

The corpus contains no evidence that any connector knows any requested buyer
(0/200), and 199/200 target people cannot be resolved to any identity in the
network data at all. The entire "warm intro" motion is running on second-hop
guesses that no one records, checks, or closes out.

---

## 8. Product implications (not built)

The evidence points at **request lifecycle ownership**, not path search, as the
highest-leverage failure:

- Every request needs a single owner of record and a state derived from events,
  not from a free-text status field that contradicts itself 75% of the time.
- Silence must be an event. 159 requests are neither alive nor dead; nothing in
  the current setup will ever surface them again.
- Path suggestions should be attached to the request as *candidates with
  confidence and limitations* (second-hop, undated, unreachable connector), and
  should feed the assignment step rather than being a standalone search tool.
- Account-level coordination beats duplicate detection: the collisions here are
  different buyers at one account, so the unit of coordination is the account.
- Leadership needs the six questions in §H6 answerable at a glance, with
  pipeline value attached.

Ranking with scores across prevalence, impact, confidence, actionability,
operator/leadership usefulness, generalizability, differentiation and
feasibility is in [`INITIAL_PROBLEM_RANKING.md`](INITIAL_PROBLEM_RANKING.md).

## 9. Open questions

1. Is a missing `intro_outcomes` row genuinely "never routed", or does routing
   sometimes happen off-system? The audit treats it as *unknown owner*, never as
   failure, but the answer changes 115 requests.
2. Are the 5 non-roster connectors real connectors, data-entry errors, or
   requesters mis-recorded? One of them files requests elsewhere.
3. Do the 6 shared-domain CRM pairs represent duplicates or genuine
   subsidiaries? They are deliberately held apart here.
4. Is there a meeting-date source outside this corpus? Without one, no
   intro→meeting conversion time can be measured.
5. What is the real "today"? Everything recency-based is anchored to the last
   observed activity (2026-08-10); a later true date makes staleness worse, not
   better.

## 10. Reproduction

```bash
pip install -r analysis/requirements.txt
python analysis/audit/run_audit.py     # rewrites analysis/output/
python -m pytest analysis/tests -q     # 51 tests
```
