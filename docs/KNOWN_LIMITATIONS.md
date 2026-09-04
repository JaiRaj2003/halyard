# Known limitations

What this system cannot tell you, and why. Read alongside
`ASSUMPTIONS_AND_LIMITATIONS.md`, which covers the audit's methodology.

## Limits imposed by the data

**The requested buyers are not in the network.** 199 of 200 historical targets
cannot be resolved to a person in the connection exports; the remaining one is
review-only. Every path the system can show is therefore second-hop — a
connector who knows *someone at the account*, not the buyer. No amount of
modelling fixes this; it needs better contact data.

**Undated relationships cannot be placed in time.** The investor network (73
rows) has no dates, so those edges are permanently `snapshot_only`: visible now,
unknown at the request date. They must never be counted as missed paths.

**168 of 200 requests have an honestly unknown outcome.** Where evidence is
absent the system says `UNKNOWN` rather than inferring. Any funnel metric built
on this corpus has that hole in it.

**Declared status is unreliable.** 63 requests contradict their own evidence —
18 declare an intro sent with no outcome row, 24 have a `path_found` flag
contradicted by an observable path, 12 declare no path where a dated connection
existed, 9 have outcomes ahead of their declared status. Declared values are
stored as claims and never used as truth.

**278 people have no profile URL.** They resolve on name plus company, which is
weaker and could collide. They are flagged, not hidden.

**Whether "no outcome row" means "never routed" is unknown.** 115 requests never
reached a connector in the data. If routing sometimes happened over a channel
that was not captured, that number is an artefact of instrumentation rather than
a failure. This is the single open question with the largest effect on the
headline finding.

## Limits of the implementation

**No migrations.** The database is rebuilt from `data/raw/`; a schema change
discards live rows. `make ingest` refuses to rebuild over live requests without
`--force`, which is a guard, not a migration strategy.

**Single-user, no auth.** Anyone who can reach the API can reassign ownership or
transition any request. Deliberate: authentication and permissions were out of
scope.

**No concurrency control.** Two simultaneous transitions on one request last-write-win. Fine for a local demo, wrong for a team.

**SQLite, in-process.** Sufficient for 5,075 connections and 200 requests; not a
multi-writer database.

**Path ordering is heuristic, not calibrated.** Weights in
`Settings.path_factor_weights` encode product judgment about what an operator
should check first. They are not fitted to outcomes and no composite number is
shown. See `SCORING_SPEC.md`.

**Coordination is pairwise.** Related activity is computed per request pair at
the same canonical account. The account view lists everything in flight there,
but nothing plans a coordinated multi-request campaign.

**The console is single-user and unauthenticated.** There is no login and no
permissions; every action is attributed to the request's own owner.

**Parsing is deterministic and narrow.** `halyard/intake/parse.py` recognises a
fixed set of ask grammars. Anything outside them yields low confidence, and the
request lands in triage with its raw text preserved rather than being guessed
at. That is the intended failure mode, but it means unusual phrasings need a
human.

**Ingestion is whole-corpus.** There is no incremental sync from a live source,
because there is no live source.

**Some requests are under path review with nothing to review.** They reached
that state because someone volunteered a route in Slack, and the connection
exports contain no edge that corroborates it. The detail view says so rather
than pretending one of the two sources is wrong; the underlying gap is in the
exports, not in the workflow.

## Things that would be wrong to conclude from this system

- That a candidate path means an introduction can be made. It means there is
  somewhere to investigate.
- That a stale request has failed. Staleness is silence, not an outcome.
- That a connector who was asked owns the request. They do not.
- That two asks at the same account are duplicates. They are related activity
  until a human says otherwise.
- That the connector roster is the set of people who make introductions — 46
  observed connectors are not on it.
- That historical ownership was as good as the current data suggests. 192 of 200
  requests were ownerless at ingest; the system supplied those owners.
- That "recommended to investigate first" predicts success. It ranks where to
  spend the next ten minutes, using the evidence listed beneath it.
- That connector load is complete. It counts asks recorded in this system;
  anything routed off-system is invisible to it.
- That "works in the same function as the requested buyer" is precise. It is a
  keyword match against coarse function groups: a CIO, a CTO and a director of
  engineering all read as "technology". The relevance tiers break ties between
  otherwise equal paths and nothing more.
