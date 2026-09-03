import pytest
from conftest import load_step

reconstruct = load_step("04_reconstruct_requests.py")


def outcome(**overrides) -> dict:
    row = {
        "connector_asked": "Dana Whitfield",
        "responded": "N",
        "intro_sent": "N",
        "meeting_booked": "N",
        "opportunity_created": "N",
    }
    row.update(overrides)
    return row


TRUTH_TABLE = [
    (outcome(opportunity_created="Y", meeting_booked="Y", intro_sent="Y", responded="Y"), [], "Open", "opportunity_created", "1_outcome_event"),
    (outcome(meeting_booked="Y", intro_sent="Y", responded="Y"), [], "Open", "meeting_booked", "1_outcome_event"),
    (outcome(intro_sent="Y", responded="Y"), [], "Stalled", "intro_sent", "1_outcome_event"),
    (outcome(responded="Y"), [], "Open", "connector_responded_no_intro_recorded", "1_outcome_event"),
    (outcome(), [], "Open", "asked_awaiting_connector_response", "1_outcome_event"),
    (None, ["declined"], "Open", "declined", "2_explicit_slack_statement"),
    (None, ["volunteer_offer", "bump"], "Open", "volunteered_no_recorded_followup", "2_explicit_slack_statement"),
    (None, ["bump", "no_knowledge"], "Stalled", "declared_only:Stalled", "3_declared_status_only"),
    (None, [], "", "unknown", "4_no_evidence"),
]


@pytest.mark.parametrize("outcome_row,intents,declared,expected_state,expected_rank", TRUTH_TABLE)
def test_state_truth_table(outcome_row, intents, declared, expected_state, expected_rank):
    state, rank, evidence, confidence = reconstruct.derive_state(outcome_row, intents, declared)
    assert (state, rank) == (expected_state, expected_rank)
    assert evidence


def test_missing_outcome_row_is_never_read_as_failure():
    state, rank, _, confidence = reconstruct.derive_state(None, [], "Open")
    assert "fail" not in state and "no_path" not in state
    assert rank == "3_declared_status_only"
    assert confidence == "low"


def test_slack_chatter_alone_does_not_create_state():
    state, rank, _, _ = reconstruct.derive_state(None, ["bump", "qualification_question"], "Open")
    assert state == "declared_only:Open"
    assert rank == "3_declared_status_only"


@pytest.mark.parametrize(
    "days,bucket",
    [(None, "unknown"), (0, "<7d"), (6, "<7d"), (7, "7-13d"), (13, "7-13d"), (14, "14-29d"), (29, "14-29d"), (30, "30d+"), (400, "30d+")],
)
def test_inactivity_buckets(days, bucket):
    assert reconstruct.inactivity_bucket(days) == bucket


def test_reference_date_is_the_latest_observed_activity():
    from datetime import date

    assert reconstruct.as_of_date([date(2025, 1, 1), date(2026, 8, 10), date(2026, 2, 2)]) == date(2026, 8, 10)
