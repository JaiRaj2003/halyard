"""The deterministic ask parser.

The corpus tests assert coverage against the *structured* columns of
`intro_requests.csv`, which is the only ground truth available: where a column is
populated but the sentence never mentions it, the parser is expected to leave the
field empty rather than invent one.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from halyard.intake.parse import ParsedAsk, looks_like_person, looks_like_title, parse_ask, strict_title_family

RAW_REQUESTS = Path(__file__).resolve().parents[1] / "data" / "raw" / "intro_requests.csv"


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


@pytest.fixture(scope="module")
def corpus() -> list[dict[str, str]]:
    with RAW_REQUESTS.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize(
    ("ask", "account", "person", "title"),
    [
        (
            "Can someone introduce us to the VP of Security at Acme?",
            "Acme",
            "",
            "VP of Security",
        ),
        (
            "trying to reach Head of Developer Productivity at Thistledown Energy — anyone have a path?",
            "Thistledown Energy",
            "",
            "Head of Developer Productivity",
        ),
        (
            "who do we know at Apex Logistics? Director of Software Engineering would be ideal but I'll take anyone senior",
            "Apex Logistics",
            "",
            "Director of Software Engineering",
        ),
        (
            "asking again: Ellerby Semiconductor. VP Engineering. Happy to draft the forward myself if someone can vouch.",
            "Ellerby Semiconductor",
            "",
            "VP Engineering",
        ),
        (
            "long shot — Sundermere Bank. Margot Vasquez-Salcedo (Chief Data Officer). Anyone?",
            "Sundermere Bank",
            "Margot Vasquez-Salcedo",
            "Chief Data Officer",
        ),
        (
            "need help getting to Harrowgate Health. Freya Lindqvist-Eastcott is the Chief Digital Officer there, "
            "cold outbound is going nowhere",
            "Harrowgate Health",
            "Freya Lindqvist-Eastcott",
            "Chief Digital Officer",
        ),
        (
            "does anyone know anyone at Pemberton Retail? looking for Head of Developer Productivity, ideally warm",
            "Pemberton Retail",
            "",
            "Head of Developer Productivity",
        ),
        (
            "any connections into Vireo Systems? we're up against a renewal window and I need an intro to "
            "Head of Developer Productivity",
            "Vireo Systems",
            "",
            "Head of Developer Productivity",
        ),
        (
            "Duncastle Hotels introduced us to Calderon Aerospace, but the account I actually need is "
            "Marchford Clinics (Chief Digital Officer).",
            "Marchford Clinics",
            "",
            "Chief Digital Officer",
        ),
        ("who knows someone at Meridian Peak?", "Meridian Peak", "", ""),
    ],
)
def test_grammars_from_the_supplied_corpus(ask: str, account: str, person: str, title: str) -> None:
    parsed = parse_ask(ask)
    assert parsed.account_text == account
    assert parsed.person_name == person
    assert parsed.title == title
    assert parsed.evidence


def test_target_persona_is_not_read_as_a_person() -> None:
    parsed = parse_ask("Can someone introduce us to the VP of Security at Acme?")
    assert parsed.person_name == ""
    assert parsed.title == "VP of Security"


def test_named_individual_is_read_as_a_person_not_a_role() -> None:
    parsed = parse_ask("intro to Jane Doe at Acme Corp")
    assert parsed.person_name == "Jane Doe"
    assert parsed.title == ""


def test_person_without_an_account_warns_rather_than_guessing() -> None:
    parsed = parse_ask(
        "Yusuf Sandoval-Drummond is the person I need. Pretty sure they're a Chief Digital Officer somewhere in Transport."
    )
    assert parsed.person_name == "Yusuf Sandoval-Drummond"
    assert parsed.title == "Chief Digital Officer"
    assert parsed.account_text == ""
    assert "no target account identified" in " ".join(parsed.warnings)


def test_domains_are_extracted_as_matching_evidence() -> None:
    parsed = parse_ask("looking for a path to Noor Isenberg-Havercamp — email domain is vireosystems.com, that's all I have")
    assert parsed.person_name == "Noor Isenberg-Havercamp"
    assert "vireosystems.com" in parsed.domains


def test_unparseable_text_is_a_normal_outcome() -> None:
    parsed = parse_ask("hmm. thoughts?")
    assert parsed == ParsedAsk(
        confidence="none",
        evidence=parsed.evidence,
        warnings=parsed.warnings,
    )
    assert parsed.parsed_anything is False
    assert parsed.warnings


@pytest.mark.parametrize("value", ["", None, 123, "   "])
def test_parse_never_raises(value: object) -> None:
    assert parse_ask(value).confidence == "none"


def test_parse_is_deterministic(corpus: list[dict[str, str]]) -> None:
    for row in corpus[:25]:
        assert parse_ask(row["raw_ask"]) == parse_ask(row["raw_ask"])


def test_a_warning_downgrades_confidence() -> None:
    confident = parse_ask("trying to reach Chief Data Officer at Vireo Systems")
    warned = parse_ask("trying to reach Head of Widget Polishing at Vireo Systems")
    assert confident.confidence == "high"
    assert warned.title == "Head of Widget Polishing"
    assert warned.normalized_title_family == ""
    assert warned.confidence == "medium"


def test_company_names_containing_role_substrings_are_not_titles() -> None:
    # "semiconductor" contains "cto"; "leadenhall" contains "lead".
    assert looks_like_title("Ellerby Semiconductor") is False
    assert strict_title_family("Ellerby Semiconductor") == ""
    assert looks_like_title("VP Engineering") is True
    assert looks_like_person("Margot Vasquez-Salcedo") is True
    assert looks_like_person("Chief Data Officer") is False


def test_every_account_stated_in_the_corpus_text_is_recovered(corpus: list[dict[str, str]]) -> None:
    """Where the supplied text names the account, the parser must find exactly it."""
    stated = [row for row in corpus if row["target_company_raw"] and row["target_company_raw"] in row["raw_ask"]]
    assert len(stated) >= 150
    wrong = [
        row["raw_ask"]
        for row in stated
        if _norm(parse_ask(row["raw_ask"]).account_text) != _norm(row["target_company_raw"])
    ]
    assert wrong == []


def test_the_parser_never_invents_an_account_or_person(corpus: list[dict[str, str]]) -> None:
    for row in corpus:
        parsed = parse_ask(row["raw_ask"])
        ask = _norm(row["raw_ask"])
        assert _norm(parsed.account_text) in ask
        assert _norm(parsed.person_name) in ask
        assert _norm(parsed.title) in ask
