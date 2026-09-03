"""Domain rules: matching, ownership, state machine, SLA, staleness, clock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from halyard.clock import AUDIT_AS_OF, FixedClock, SystemClock, audit_clock, get_clock
from halyard.config import Settings
from halyard.domain.ownership import (
    CONFIGURED_TRIAGE_OWNER,
    EXPLICIT_INTAKE,
    FALLBACK_REQUESTER,
    OBSERVED_OWNER,
    OwnershipError,
    resolve_historical_owner,
    resolve_live_owner,
)
from halyard.domain.states import (
    SETTLED_STATES,
    TransitionError,
    WorkflowState,
    check_transition,
)
from halyard.domain.workflow import (
    age_days,
    assign_next_action,
    inactivity_bucket,
    is_overdue,
    is_potentially_stale,
)
from halyard.matching.accounts import AccountResolver, canonical_key
from halyard.matching.normalize import norm_company, norm_person
from halyard.matching.people import PersonResolver

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
SETTINGS = Settings()


# -- matching ---------------------------------------------------------------

CRM = pd.DataFrame(
    [
        {"account_id": "A1", "account_name": "Apex Logistics, Inc.", "domain": "apex.com", "industry": "",
         "employee_count": "", "hq": "", "stage": "", "arr_potential_usd": "", "owner": ""},
        {"account_id": "A2", "account_name": "Apex Logistics Group", "domain": "apex.com", "industry": "",
         "employee_count": "", "hq": "", "stage": "", "arr_potential_usd": "", "owner": ""},
        {"account_id": "A3", "account_name": "Northwind Robotics", "domain": "northwind.io", "industry": "",
         "employee_count": "", "hq": "", "stage": "", "arr_potential_usd": "", "owner": ""},
    ]
)


def test_exact_name_match_resolves():
    match = AccountResolver(CRM).resolve("Northwind Robotics", [])
    assert match.account_id == "A3"
    assert match.tier.startswith(("A", "B"))


def test_normalized_match_ignores_suffixes_and_case():
    assert canonical_key("Northwind Robotics, LLC") == canonical_key("northwind robotics")
    assert norm_company("Acme Corp.") == norm_company("ACME  corp")


def test_shared_domain_stays_ambiguous_rather_than_collapsing_accounts():
    match = AccountResolver(CRM).resolve("Apex", ["apex.com"])
    assert not match.account_id
    assert match.domain_group
    assert len(match.competing_candidates) >= 2


def test_unknown_account_is_unmatched_not_guessed():
    match = AccountResolver(CRM).resolve("Some Company Nobody Has Heard Of", [])
    assert not match.account_id
    assert match.tier.startswith(("D", "E", "U"))


CONNECTIONS = pd.DataFrame(
    [
        {"connector": "Trask", "name": "Jane Doe", "title": "VP Engineering", "company": "Northwind Robotics",
         "connected_on": "2024-01-01", "profile_url": "https://x/jane-1", "_source_file": "connections_trask.csv"},
        {"connector": "Duvall", "name": "Jane Doe", "title": "Head of Sales", "company": "Apex Logistics",
         "connected_on": "2024-02-01", "profile_url": "https://x/jane-2", "_source_file": "connections_duvall.csv"},
    ]
)


def test_ambiguous_person_name_is_preserved_as_ambiguous():
    match = PersonResolver(CONNECTIONS).resolve("Jane Doe", "", "")
    assert match.tier.startswith("T2")
    assert len(match.candidates) == 2


def test_name_plus_company_disambiguates():
    match = PersonResolver(CONNECTIONS).resolve("Jane Doe", "Northwind Robotics", "")
    assert match.tier.startswith(("T1", "T3"))


def test_person_normalization_is_transliterating():
    assert norm_person("Sunniva Højgaard") == norm_person("Sunniva Hojgaard")


# -- ownership --------------------------------------------------------------


def test_historical_ownership_is_preserved_when_evidenced():
    decision = resolve_historical_owner(observed_owner_id=7, requester_id=3)
    assert (decision.owner_id, decision.source, decision.observed_owner_id) == (7, OBSERVED_OWNER, 7)
    assert decision.was_ownerless_at_ingest is False


def test_historical_ownerlessness_is_recorded_not_hidden():
    decision = resolve_historical_owner(observed_owner_id=None, requester_id=3)
    assert (decision.owner_id, decision.source) == (3, FALLBACK_REQUESTER)
    assert decision.observed_owner_id is None
    assert decision.was_ownerless_at_ingest is True


@pytest.mark.parametrize(
    "explicit,triage,requester,expected",
    [
        (9, 5, 3, (9, EXPLICIT_INTAKE)),
        (None, 5, 3, (5, CONFIGURED_TRIAGE_OWNER)),
        (None, None, 3, (3, FALLBACK_REQUESTER)),
    ],
)
def test_live_owner_resolution_order(explicit, triage, requester, expected):
    assert resolve_live_owner(explicit, triage, requester) == expected


def test_live_owner_resolution_refuses_to_produce_an_ownerless_request():
    with pytest.raises(OwnershipError):
        resolve_live_owner(None, None, None)


# -- state machine ----------------------------------------------------------


def test_allowed_transition():
    check_transition(WorkflowState.PATH_REVIEW, WorkflowState.AWAITING_CONNECTOR)


def test_forbidden_transition_names_what_is_allowed():
    with pytest.raises(TransitionError) as exc:
        check_transition(WorkflowState.NEEDS_TRIAGE, WorkflowState.COMPLETED)
    assert "NEEDS_TRIAGE -> COMPLETED" in str(exc.value)
    assert exc.value.allowed


def test_no_response_is_not_a_state():
    assert "NO_RESPONSE" not in {state.value for state in WorkflowState}


def test_no_observable_path_is_active_and_keeps_a_next_action():
    assert WorkflowState.NO_OBSERVABLE_PATH not in SETTLED_STATES
    action = assign_next_action(WorkflowState.NO_OBSERVABLE_PATH, NOW, SETTINGS)
    assert action.action
    assert action.due_at == NOW + timedelta(days=5)


def test_settled_states_owe_nothing():
    for state in SETTLED_STATES:
        action = assign_next_action(state, NOW, SETTINGS)
        assert (action.action, action.due_at) == ("", None)


@pytest.mark.parametrize(
    "state,days",
    [
        (WorkflowState.NEEDS_TRIAGE, 2),
        (WorkflowState.NEEDS_ENTITY_REVIEW, 2),
        (WorkflowState.PATH_REVIEW, 2),
        (WorkflowState.AWAITING_CONNECTOR, 5),
        (WorkflowState.BLOCKED, 5),
    ],
)
def test_sla_defaults_are_measured_from_assignment(state, days):
    action = assign_next_action(state, NOW, SETTINGS)
    assert action.due_at == NOW + timedelta(days=days)


def test_reassigning_an_action_resets_its_clock():
    first = assign_next_action(WorkflowState.PATH_REVIEW, NOW, SETTINGS)
    later = NOW + timedelta(days=10)
    second = assign_next_action(WorkflowState.PATH_REVIEW, later, SETTINGS)
    assert is_overdue(first.due_at, later)
    assert not is_overdue(second.due_at, later)


# -- staleness --------------------------------------------------------------


def test_staleness_is_a_flag_not_a_state():
    quiet = NOW - timedelta(days=200)
    assert is_potentially_stale(WorkflowState.AWAITING_CONNECTOR.value, quiet, NOW, SETTINGS)
    assert not is_potentially_stale(WorkflowState.COMPLETED.value, quiet, NOW, SETTINGS)


def test_recent_activity_is_not_stale():
    assert not is_potentially_stale(
        WorkflowState.PATH_REVIEW.value, NOW - timedelta(days=3), NOW, SETTINGS
    )


def test_inactivity_buckets():
    assert inactivity_bucket(None) == "unknown"
    assert inactivity_bucket(2) == "0-6d"
    assert inactivity_bucket(45) == "30-59d"
    assert inactivity_bucket(400) == "90d+"


# -- clock ------------------------------------------------------------------


def test_application_clock_defaults_to_real_time():
    clock = get_clock({})
    assert isinstance(clock, SystemClock)
    assert clock.now().year >= 2024


def test_as_of_override_is_explicit_only():
    clock = get_clock({"HALYARD_AS_OF": "2026-08-10"})
    assert isinstance(clock, FixedClock)
    assert clock.now() == AUDIT_AS_OF


def test_audit_clock_is_separate_from_the_application_clock():
    assert audit_clock().now() == AUDIT_AS_OF
    assert get_clock({}).now() != AUDIT_AS_OF


def test_a_request_created_now_is_zero_days_old():
    assert age_days(NOW, NOW) == 0
