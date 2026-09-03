"""Step 04 - reconstruct one normalized record per intro request.

State and staleness are derived on separate axes. State comes only from explicit
evidence (outcome rows, explicit Slack statements, then the declared status
field); recency of chatter never implies a state. A request may legitimately be
``state=unknown`` and ``potentially_stale=True`` at the same time, and a missing
outcome row is never read as a failed intro.

Outputs:
  analysis/output/request_reconstruction.csv
  analysis/output/request_funnel.csv
  analysis/output/request_latency.csv
  analysis/output/stalled_requests.csv
  analysis/output/slack_reconciliation.csv
  analysis/output/slack_message_intents.csv
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for halyard.matching

from common import io
from halyard.matching.accounts import AccountResolver, canonical_key
from halyard.matching.normalize import extract_domains, norm_ws, parse_date, parse_timestamp, title_family
from halyard.matching.people import PersonResolver
from halyard.matching.slack import EXPLICIT_STATE_INTENTS, classify, looks_like_ask, referred_person

INACTIVITY_BUCKETS = ((7, "7-13d"), (14, "14-29d"), (30, "30d+"))


def as_of_date(dates: list[date]) -> date:
    """Reference "today" for staleness: the latest observed activity in the corpus."""
    return max(dates)


def inactivity_bucket(days: int | None) -> str:
    if days is None:
        return "unknown"
    for threshold, label in reversed(INACTIVITY_BUCKETS):
        if days >= threshold:
            return label
    return "<7d"


def derive_state(outcome: dict | None, slack_intents: list[str], declared_status: str) -> tuple[str, str, str, str]:
    """Return (state, evidence_rank, evidence, confidence).

    Evidence rank 1 = explicit outcome event, 2 = explicit Slack statement,
    3 = declared structured status only, 4 = no evidence.
    """
    if outcome:
        if outcome["opportunity_created"] == "Y":
            return "opportunity_created", "1_outcome_event", "intro_outcomes row: opportunity_created=Y", "high"
        if outcome["meeting_booked"] == "Y":
            return "meeting_booked", "1_outcome_event", "intro_outcomes row: meeting_booked=Y", "high"
        if outcome["intro_sent"] == "Y":
            return "intro_sent", "1_outcome_event", "intro_outcomes row: intro_sent=Y", "high"
        if outcome["responded"] == "Y":
            return (
                "connector_responded_no_intro_recorded",
                "1_outcome_event",
                "intro_outcomes row: responded=Y, intro_sent=N",
                "medium",
            )
        return (
            "asked_awaiting_connector_response",
            "1_outcome_event",
            "intro_outcomes row: connector asked, responded=N",
            "medium",
        )

    explicit = [intent for intent in slack_intents if intent in EXPLICIT_STATE_INTENTS]
    if explicit:
        return explicit[0], "2_explicit_slack_statement", f"Slack message classified as {explicit[0]}", "medium"

    if "volunteer_offer" in slack_intents:
        return (
            "volunteered_no_recorded_followup",
            "2_explicit_slack_statement",
            "someone offered to help in Slack; no outcome row and no recorded follow-up",
            "medium",
        )

    declared = norm_ws(declared_status)
    if declared:
        return (
            f"declared_only:{declared}",
            "3_declared_status_only",
            f"intro_requests.status='{declared}' with no corroborating event evidence",
            "low",
        )
    return "unknown", "4_no_evidence", "no outcome row, no explicit Slack statement, no declared status", "none"


def main() -> None:
    requests = io.load_requests()
    outcomes = io.load_outcomes()
    slack = io.slack_messages()
    crm = io.load_crm()
    connections = io.load_connections()

    account_resolver = AccountResolver(crm)
    person_resolver = PersonResolver(connections)

    slack["intent"] = slack["text"].map(classify)
    slack["is_ask_like"] = slack["text"].map(looks_like_ask)
    slack["referred_person"] = slack["text"].map(referred_person)
    slack["parsed_ts"] = slack["ts"].map(parse_timestamp)
    io.write_csv(
        slack[["request_id", "message_index", "ts", "user", "intent", "is_ask_like", "referred_person", "text"]],
        "slack_message_intents.csv",
    )

    outcome_by_request: dict[str, dict] = {}
    duplicate_outcome_rows: list[str] = []
    for row in outcomes.itertuples():
        record = {
            "connector_asked": norm_ws(row.connector_asked),
            "asked_date": parse_date(row.asked_date),
            "responded": norm_ws(row.responded),
            "response_date": parse_date(row.response_date),
            "intro_sent": norm_ws(row.intro_sent),
            "intro_date": parse_date(row.intro_date),
            "meeting_booked": norm_ws(row.meeting_booked),
            "opportunity_created": norm_ws(row.opportunity_created),
            "opportunity_value_usd": norm_ws(row.opportunity_value_usd),
        }
        if row.request_id in outcome_by_request:
            duplicate_outcome_rows.append(row.request_id)
        outcome_by_request[row.request_id] = record

    slack_by_request = {rid: group.sort_values("message_index") for rid, group in slack.groupby("request_id")}

    all_dates: list[date] = []
    for row in requests.itertuples():
        parsed = parse_date(row.request_date)
        if parsed:
            all_dates.append(parsed)
    for record in outcome_by_request.values():
        all_dates.extend(d for d in (record["asked_date"], record["response_date"], record["intro_date"]) if d)
    all_dates.extend(ts.date() for ts in slack["parsed_ts"].dropna())
    reference_date = as_of_date(all_dates)

    records = []
    for row in requests.itertuples():
        request_date = parse_date(row.request_date)
        thread = slack_by_request.get(row.request_id)
        intents = list(thread["intent"]) if thread is not None else []
        outcome = outcome_by_request.get(row.request_id)

        thread_text = " ".join(thread["text"]) if thread is not None else ""
        domain_hints = extract_domains(f"{norm_ws(row.raw_ask)} {thread_text}")
        account = account_resolver.resolve(row.target_company_raw, domain_hints)
        target_person = person_resolver.resolve(row.target_person_raw, row.target_company_raw, row.target_title_raw)

        state, evidence_rank, evidence, confidence = derive_state(outcome, intents, row.status)

        activity_dates: list[date] = [d for d in [request_date] if d]
        if thread is not None:
            activity_dates.extend(ts.date() for ts in thread["parsed_ts"].dropna())
        if outcome:
            activity_dates.extend(
                d for d in (outcome["asked_date"], outcome["response_date"], outcome["intro_date"]) if d
            )
        last_activity = max(activity_dates) if activity_dates else None
        days_since = (reference_date - last_activity).days if last_activity else None

        first_reply = None
        if thread is not None:
            replies = thread[thread["message_index"] > 0]["parsed_ts"].dropna()
            first_reply = replies.min().date() if len(replies) else None
        substantive = None
        if thread is not None:
            useful = thread[
                (thread["message_index"] > 0)
                & (thread["intent"].isin({"volunteer_offer", "referral_suggestion", "intro_confirmed"}))
            ]["parsed_ts"].dropna()
            substantive = useful.min().date() if len(useful) else None

        terminal = state in {"opportunity_created", "meeting_booked", "intro_sent", "closed", "declined"}
        records.append(
            {
                "request_id": row.request_id,
                "requested_by": norm_ws(row.requested_by),
                "requester_role": norm_ws(row.requester_role),
                "request_date": request_date,
                "target_company_raw": norm_ws(row.target_company_raw),
                "target_company_canonical_key": canonical_key(row.target_company_raw),
                "target_account_match_tier": account.tier,
                "crm_account_id": account.account_id,
                "crm_account_name": account.account_name,
                "crm_domain_group": account.domain_group,
                "crm_competing_candidates": "; ".join(account.competing_candidates),
                "domain_hints": "; ".join(domain_hints),
                "target_person_raw": norm_ws(row.target_person_raw),
                "target_person_match_tier": target_person.tier,
                "target_title_raw": norm_ws(row.target_title_raw),
                "target_title_family": title_family(row.target_title_raw),
                "deal_value_usd": int(row.deal_value_usd),
                "urgency": norm_ws(row.urgency),
                "declared_status": norm_ws(row.status),
                "declared_path_found_flag": norm_ws(row.path_found_flag),
                "connector_asked": outcome["connector_asked"] if outcome else "",
                "routed": bool(outcome),
                "asked_date": outcome["asked_date"] if outcome else None,
                "connector_responded": outcome["responded"] if outcome else "",
                "response_date": outcome["response_date"] if outcome else None,
                "intro_sent": outcome["intro_sent"] if outcome else "",
                "intro_date": outcome["intro_date"] if outcome else None,
                "meeting_booked": outcome["meeting_booked"] if outcome else "",
                "opportunity_created": outcome["opportunity_created"] if outcome else "",
                "derived_state": state,
                "state_evidence_rank": evidence_rank,
                "state_evidence": evidence,
                "state_confidence": confidence,
                "has_terminal_evidence": terminal,
                "owner_known": bool(outcome and outcome["connector_asked"]),
                # A next action is only "known" when the record either closes the
                # request or names an owner who still owes a step and has been
                # active recently; a named owner who went silent leaves the next
                # action undetermined.
                "next_action_known": bool(
                    terminal
                    or (
                        outcome
                        and outcome["connector_asked"]
                        and days_since is not None
                        and days_since < 30
                    )
                ),
                "slack_thread_present": thread is not None,
                "slack_message_count": len(thread) if thread is not None else 0,
                "slack_reply_count": (len(thread) - 1) if thread is not None else 0,
                "slack_intents": "; ".join(sorted(set(intents))),
                "slack_volunteer_offer": "volunteer_offer" in intents,
                "slack_referral_suggestion": "referral_suggestion" in intents,
                "slack_bump": "bump" in intents,
                "slack_duplicate_query": "possible_duplicate_query" in intents,
                "slack_explicit_state_statement": any(i in EXPLICIT_STATE_INTENTS for i in intents),
                "first_reply_date": first_reply,
                "first_substantive_reply_date": substantive,
                "last_observed_activity": last_activity,
                "days_since_activity": days_since,
                "inactivity_bucket": inactivity_bucket(days_since),
                "potentially_stale": bool(days_since is not None and days_since >= 30 and not terminal),
            }
        )

    reconstruction = pd.DataFrame(records)
    reconstruction.attrs["reference_date"] = reference_date

    # -- funnel ---------------------------------------------------------------
    total = len(reconstruction)
    funnel = pd.DataFrame(
        [
            {"stage": "requests_in_spine", "count": total, "denominator": total},
            {
                "stage": "slack_thread_present",
                "count": int(reconstruction["slack_thread_present"].sum()),
                "denominator": total,
            },
            {
                "stage": "any_slack_reply",
                "count": int((reconstruction["slack_reply_count"] > 0).sum()),
                "denominator": total,
            },
            {
                "stage": "substantive_slack_reply",
                "count": int(reconstruction["first_substantive_reply_date"].notna().sum()),
                "denominator": total,
            },
            {"stage": "routed_to_connector", "count": int(reconstruction["routed"].sum()), "denominator": total},
            {
                "stage": "connector_responded",
                "count": int((reconstruction["connector_responded"] == "Y").sum()),
                "denominator": total,
            },
            {"stage": "intro_sent", "count": int((reconstruction["intro_sent"] == "Y").sum()), "denominator": total},
            {
                "stage": "meeting_booked",
                "count": int((reconstruction["meeting_booked"] == "Y").sum()),
                "denominator": total,
            },
            {
                "stage": "opportunity_created",
                "count": int((reconstruction["opportunity_created"] == "Y").sum()),
                "denominator": total,
            },
        ]
    )
    funnel["pct_of_requests"] = (100.0 * funnel["count"] / funnel["denominator"]).round(1)

    # -- latency --------------------------------------------------------------
    def days_between(start: pd.Series, end: pd.Series) -> pd.Series:
        return (pd.to_datetime(end) - pd.to_datetime(start)).dt.days

    latency_specs = [
        ("request_to_first_slack_reply", "request_date", "first_reply_date"),
        ("request_to_substantive_slack_reply", "request_date", "first_substantive_reply_date"),
        ("request_to_connector_asked", "request_date", "asked_date"),
        ("connector_asked_to_response", "asked_date", "response_date"),
        ("request_to_intro", "request_date", "intro_date"),
        ("intro_to_meeting", "intro_date", None),
    ]
    latency_rows = []
    for name, start_col, end_col in latency_specs:
        if end_col is None:
            latency_rows.append(
                {
                    "metric": name,
                    "n_observed": 0,
                    "denominator": total,
                    "coverage_pct": 0.0,
                    "median_days": None,
                    "p90_days": None,
                    "max_days": None,
                    "note": "no meeting date is recorded anywhere in the corpus; metric not computable",
                }
            )
            continue
        series = days_between(reconstruction[start_col], reconstruction[end_col]).dropna()
        latency_rows.append(
            {
                "metric": name,
                "n_observed": int(len(series)),
                "denominator": total,
                "coverage_pct": round(100.0 * len(series) / total, 1),
                "median_days": float(series.median()) if len(series) else None,
                "p90_days": float(series.quantile(0.9)) if len(series) else None,
                "max_days": float(series.max()) if len(series) else None,
                "note": "",
            }
        )
    latency = pd.DataFrame(latency_rows)

    # -- staleness ------------------------------------------------------------
    stalled = reconstruction[
        ["request_id", "requested_by", "target_company_raw", "deal_value_usd", "urgency", "declared_status",
         "derived_state", "state_confidence", "has_terminal_evidence", "routed", "last_observed_activity",
         "days_since_activity", "inactivity_bucket", "potentially_stale"]
    ].copy()
    stalled["staleness_class"] = [
        "explicitly_resolved"
        if row.has_terminal_evidence
        else ("unresolved_no_activity_30d" if row.potentially_stale else "recent_or_unknown")
        for row in stalled.itertuples()
    ]

    # -- Slack reconciliation against the 200-row spine -----------------------
    spine_ids = set(reconstruction["request_id"])
    thread_ids = set(slack["request_id"])
    extra_asks = slack[(slack["message_index"] > 0) & (slack["is_ask_like"])]
    reconciliation_rows = [
        {"check": "requests_in_spine", "count": len(spine_ids), "detail": "authoritative denominator"},
        {
            "check": "requests_without_slack_thread",
            "count": len(spine_ids - thread_ids),
            "detail": "; ".join(sorted(spine_ids - thread_ids)) or "none",
        },
        {
            "check": "slack_threads_without_request_row",
            "count": len(thread_ids - spine_ids),
            "detail": "; ".join(sorted(thread_ids - spine_ids)) or "none",
        },
        {
            "check": "requests_with_multiple_slack_threads",
            "count": int((slack.groupby("request_id")["thread_index"].nunique() > 1).sum()),
            "detail": "threads are keyed 1:1 by request_id in the export",
        },
        {
            "check": "threads_containing_additional_ask_like_messages",
            "count": int(extra_asks["request_id"].nunique()),
            "detail": "; ".join(sorted(extra_asks["request_id"].unique())[:20]) or "none",
        },
        {
            "check": "outcome_rows_not_mappable_to_spine",
            "count": len(set(outcomes["request_id"]) - spine_ids),
            "detail": "; ".join(sorted(set(outcomes["request_id"]) - spine_ids)) or "none",
        },
        {
            "check": "duplicate_outcome_rows_per_request",
            "count": len(duplicate_outcome_rows),
            "detail": "; ".join(sorted(duplicate_outcome_rows)) or "none",
        },
    ]
    reconciliation = pd.DataFrame(reconciliation_rows)

    io.write_csv(reconstruction, "request_reconstruction.csv")
    io.write_csv(funnel, "request_funnel.csv")
    io.write_csv(latency, "request_latency.csv")
    io.write_csv(stalled, "stalled_requests.csv")
    io.write_csv(reconciliation, "slack_reconciliation.csv")
    io.write_json({"reference_date": str(reference_date)}, "audit_reference_date.json")

    print("reference (as-of) date:", reference_date)
    print(funnel.to_string(index=False))
    print()
    print(latency.to_string(index=False))
    print()
    print(reconstruction["derived_state"].value_counts().to_string())
    print()
    print(reconstruction["state_evidence_rank"].value_counts().to_string())
    print()
    print(stalled["staleness_class"].value_counts().to_string())
    print()
    print(reconciliation.to_string(index=False))


if __name__ == "__main__":
    main()
