from datetime import date

from halyard.matching.normalize import (
    extract_domains,
    has_casing_defect,
    has_whitespace_defect,
    is_malformed_name,
    norm_company,
    norm_domain,
    norm_person,
    norm_ws,
    parse_date,
    parse_partial_date,
    title_family,
)


def test_norm_ws_collapses_and_handles_non_strings():
    assert norm_ws("  Apex   Logistics \t") == "Apex Logistics"
    assert norm_ws(None) == ""
    assert norm_ws(float("nan")) == ""


def test_norm_company_strips_legal_suffixes_but_not_meaningful_words():
    assert norm_company("Apex Logistics, Inc.") == norm_company("Apex Logistics")
    assert norm_company("Silverbrook Paper Corp") == norm_company("Silverbrook Paper")
    assert norm_company("Apex Holdings") != norm_company("Apex Logistics")


def test_norm_person_is_accent_insensitive():
    assert norm_person("Tomás Beckett") == norm_person("tomas  beckett")
    assert norm_person("Sunniva Højgaard") == norm_person("Sunniva Hojgaard")
    assert norm_person("Dana Whitfield") != norm_person("Dana Whitfeld")


def test_norm_domain_and_extraction():
    assert norm_domain("HTTPS://WWW.Example.com/careers") == "example.com"
    assert norm_domain("example.com") == "example.com"
    assert extract_domains("reach out via anna@apexlogistics.com or apex.io") == [
        "apexlogistics.com",
        "apex.io",
    ]


def test_title_family_groups_synonyms_and_separates_distinct_roles():
    assert title_family("Chief Data Officer") == title_family("VP Data & Analytics")
    assert title_family("Chief Operating Officer") != title_family("Chief Technology Officer")
    assert title_family("Head of Platform Engineering") != title_family("Chief Executive Officer")


def test_parse_date_accepts_iso_and_rejects_garbage():
    assert parse_date("2026-03-06") == date(2026, 3, 6)
    assert parse_date("") is None
    assert parse_date("not a date") is None


def test_parse_partial_date_coarsens_year_only_values():
    assert parse_partial_date("2013") == date(2013, 1, 1)
    assert parse_partial_date("2013-06-02") == date(2013, 6, 2)
    assert parse_partial_date("") is None


def test_defect_detectors():
    assert has_whitespace_defect(" Apex")
    assert not has_whitespace_defect("Apex")
    assert has_casing_defect("APEX LOGISTICS")
    assert not has_casing_defect("Apex Logistics")
    assert is_malformed_name("???")
    assert not is_malformed_name("Priya Raghunathan")
