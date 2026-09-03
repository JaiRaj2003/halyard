# Initial problem ranking

Each candidate problem is scored 1–5 on nine dimensions (max 45). Scores are in
`analysis/output/problem_scores.csv`; the evidence behind each is in
[`DATA_AUDIT.md`](DATA_AUDIT.md).

Dimensions: prevalence · business impact · evidence confidence · actionability ·
operator usefulness · leadership usefulness · live-request generalisability ·
product differentiation · feasibility.

| Rank | Problem | Score | Headline evidence |
| --- | --- | --- | --- |
| P1 | Requests have no owner and no state of record; they die silently | **43** | 159/200 unresolved with 30+ days of silence ($106.5M of $137.8M pipeline); 115/200 have no connector of record; 111/200 have no state evidence beyond a self-declared status |
| P2 | The record of truth contradicts itself; "no path" is often false | **39** | 150/200 requests carry ≥1 contradiction; 46/109 no-path/unknown requests had a pre-dating connection into the account |
| P3 | Path discovery is manual, so known paths go unused | **36** | 97/200 requests had a time-aware path; roster connectors sat on 220/263 request-paths they were never asked about |
| P4 | Duplicate and repeat asks collide on the same accounts | **34** | 42/200 asks self-describe as repeats; 200 requests cover only 51 accounts; 70/200 have someone in Slack asking whether it is a duplicate |
| P5 | Entity resolution is unreliable across sources | **28** | 94/200 requests name a target that does not resolve cleanly to CRM; 6 CRM domain pairs are near-duplicates; 199/200 target people unresolvable |
| P6 | Connector overload throttles throughput | **21** | only 2/49 connector-months exceed stated capacity; recorded asks run far below capacity |

## Score detail

| Problem | Prev | Impact | Conf | Action | Operator | Leader | Generalises | Differentiation | Feasible | Total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 5 | 43 |
| P2 | 5 | 4 | 4 | 4 | 5 | 4 | 5 | 4 | 4 | 39 |
| P3 | 4 | 4 | 3 | 4 | 5 | 3 | 5 | 5 | 3 | 36 |
| P4 | 4 | 3 | 4 | 4 | 4 | 3 | 4 | 3 | 5 | 34 |
| P5 | 4 | 3 | 4 | 3 | 3 | 2 | 4 | 2 | 3 | 28 |
| P6 | 1 | 2 | 4 | 2 | 2 | 2 | 2 | 2 | 4 | 21 |

## Reading of the ranking

P1 wins on every dimension except differentiation: an ownership-and-state system
of record is not a novel idea, but it is the failure the data actually shows, it
applies unchanged to new live requests, and nothing else can be measured
reliably until it exists.

P2 and P3 are close and complementary — a request record that contradicts itself
and a path graph nobody queries are two halves of the same missing loop. P3 is
the most differentiated capability, and the natural second layer once requests
have owners and states.

P4 is prevalent and cheap to address but reads as a **symptom** of P1: people
re-ask because their first ask vanished (14 of 31 identifiable repeats had a
prior ask that was never routed).

P5 is real infrastructure debt that constrains P2/P3 accuracy, but it is not
itself the operational failure.

P6 — the intuitive answer — is the only hypothesis the data contradicts.
Connectors are not saturated; the asks never reach them.
