import pandas as pd
import pytest

from common.accounts import (
    TIER_AMBIGUOUS,
    TIER_EXACT_ID,
    TIER_PROBABLE_DOMAIN_GROUP,
    TIER_PROBABLE_NAME,
    TIER_SIMILAR_DISTINCT,
    TIER_UNMATCHED,
    AccountResolver,
    canonical_key,
)
from common.people import T1, T3, T5, T6, T_AMBIGUOUS, PersonResolver

CRM = pd.DataFrame(
    [
        {"account_id": "A1", "account_name": "Apex Logistics, Inc.", "domain": "apexlogistics.com", "industry": "Logistics", "hq_country": "US", "employee_count": "9000"},
        {"account_id": "A2", "account_name": "Apex Logistics", "domain": "www.apexlogistics.com", "industry": "Logistics", "hq_country": "US", "employee_count": "9000"},
        {"account_id": "A3", "account_name": "Apex Holdings", "domain": "apexholdings.com", "industry": "Financial Services", "hq_country": "UK", "employee_count": "300"},
        {"account_id": "A4", "account_name": "Thornbury Financial", "domain": "thornburyfin.com", "industry": "Financial Services", "hq_country": "US", "employee_count": "5000"},
    ]
)


@pytest.fixture(scope="module")
def accounts() -> AccountResolver:
    return AccountResolver(CRM)


def test_canonical_key_ignores_spacing_and_legal_suffixes():
    assert canonical_key("Thornbury Financial") == canonical_key("THORNBURYFINANCIAL")
    assert canonical_key("Apex Logistics, Inc.") == canonical_key("apex logistics")
    assert canonical_key("Apex Holdings") != canonical_key("Apex Logistics")


def test_exact_crm_account_id_is_definitive(accounts):
    match = accounts.resolve("A3")
    assert match.tier == TIER_EXACT_ID
    assert match.account_id == "A3"


def test_shared_domain_records_are_never_silently_merged(accounts):
    """A1 and A2 share a domain, so the name resolves to the group, not to one id."""
    match = accounts.resolve("Apex Logistics")
    assert match.tier in {TIER_PROBABLE_NAME, TIER_PROBABLE_DOMAIN_GROUP}
    assert match.account_id == "" or match.account_id in {"A1", "A2"}
    assert set(match.competing_candidates) >= {"A1", "A2"} or match.domain_group


def test_must_not_match_pair_stays_apart(accounts):
    """Deliberate look-alike: 'Apex Holdings' must never resolve to Apex Logistics."""
    match = accounts.resolve("Apex Holdings")
    assert match.account_id == "A3"
    for other in accounts.resolve("Apex Logistics").competing_candidates:
        assert other != "A3"


def test_unknown_company_is_unmatched_not_guessed(accounts):
    match = accounts.resolve("Copperline Water")
    assert match.tier in {TIER_UNMATCHED, TIER_SIMILAR_DISTINCT, TIER_AMBIGUOUS}
    assert match.account_id == ""


def test_unique_domain_hint_maps_an_external_record(accounts):
    match = accounts.resolve("Thornbury Fin. Group", domain_hints=["thornburyfin.com"])
    assert match.account_id == "A4"


CONNECTIONS = pd.DataFrame(
    [
        {"connector": "Dana Whitfield", "name": "Rowan Ellis", "title": "Chief Data Officer", "company": "Apex Logistics", "connected_on": "2024-01-05", "profile_url": "https://prof.example/rowan-ellis", "_source_file": "connections_whitfield.csv", "_source_row": 2},
        {"connector": "Owen Trask", "name": "Rowan Ellis", "title": "VP Data & Analytics", "company": "Apex Logistics", "connected_on": "2024-02-05", "profile_url": "https://prof.example/rowan-ellis", "_source_file": "connections_trask.csv", "_source_row": 2},
        {"connector": "Owen Trask", "name": "Rowan Ellis", "title": "Chief Executive Officer", "company": "Brightmoor Energy", "connected_on": "2024-03-05", "profile_url": "https://prof.example/rowan-ellis-2", "_source_file": "connections_trask.csv", "_source_row": 3},
        {"connector": "Dana Whitfield", "name": "Marguerite Okonkwo", "title": "Chief Operating Officer", "company": "Redtree Foods", "connected_on": "2024-04-05", "profile_url": "", "_source_file": "connections_whitfield.csv", "_source_row": 4},
    ]
)


@pytest.fixture(scope="module")
def people() -> PersonResolver:
    return PersonResolver(CONNECTIONS)


def test_profile_url_is_the_strongest_tier(people):
    match = people.resolve("R. Ellis", url="http://prof.example/rowan-ellis/")
    assert match.tier == T1


def test_name_plus_org_resolves_a_collision(people):
    match = people.resolve("Rowan Ellis", org="Apex Logistics, Inc.")
    assert match.tier == T3


def test_bare_colliding_name_stays_ambiguous(people):
    match = people.resolve("Rowan Ellis")
    assert match.tier == T_AMBIGUOUS
    assert len(match.candidates) > 1


def test_near_miss_name_is_review_only_never_applied(people):
    match = people.resolve("Marguerit Okonkwo")
    assert match.tier == T5
    assert match.person_key == ""


def test_absent_person_is_unmatched(people):
    assert people.resolve("Perrine Salcedo-Oyelaran").tier == T6
