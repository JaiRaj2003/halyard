"""Deterministic parsing of a free-text ask.

No model, no network, no key: a short ordered list of grammars observed in the
supplied Slack corpus, each one naming itself in the evidence string so an
operator can see *why* a field was filled in. Nothing here is applied silently —
every field it produces is a proposal that a human confirms, and a failure to
parse is a normal outcome that leaves the request owned and in triage rather
than rejecting the input.

Adding a grammar means adding a row to :data:`GRAMMARS`; the classification of a
target phrase as a title or a person name is separate and shared by all of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ..matching.normalize import TITLE_FAMILIES, extract_domains, norm_text, norm_ws

Confidence = Literal["high", "medium", "low", "none"]

#: Words that make a phrase a role rather than a person. Matched on whole words
#: only — "semiconductor" contains "cto" and is not a job title.
TITLE_MARKERS = (
    "chief", "officer", "vp", "svp", "evp", "avp", "head", "director", "president",
    "founder", "partner", "lead", "manager", "engineer", "engineering", "architect",
    "principal", "ceo", "coo", "cfo", "cto", "cio", "ciso", "cmo", "cpo", "cdo", "cro",
)
_TITLE_MARKER_RE = re.compile(r"\b(?:%s)\b" % "|".join(TITLE_MARKERS), flags=re.IGNORECASE)
#: Whole-word form of the shared title-family needles. ``title_family`` matches
#: on substrings, which is right for the audit's title columns but wrong here:
#: it reads "Ellerby Semiconductor" as a CTO. Classification of free text needs
#: word boundaries; the shared function is left alone so the audit is unchanged.
_FAMILY_WORD_RE = re.compile(
    r"\b(?:%s)\b" % "|".join(re.escape(needle) for _, needles in TITLE_FAMILIES for needle in needles),
    flags=re.IGNORECASE,
)

#: Trailing conversational noise that is never part of an account or a name.
_TRAILING_NOISE = re.compile(
    r"\s*(?:—|-|,)?\s*(?:anyone(?:\s+have\s+a\s+path)?|any(?:one)?\s+ideas?|ideally\s+warm|"
    r"happy\s+to\s+draft.*|cold\s+outbound.*|we'?re\s+up\s+against.*|thanks?.*)\s*$",
    flags=re.IGNORECASE,
)
_LEADING_NOISE = re.compile(
    r"^\s*(?:asking\s+again|long\s+shot|quick\s+one|hey\s+all|folks|team)\s*[:\-—,]?\s*",
    flags=re.IGNORECASE,
)
_ARTICLE = re.compile(r"^\s*(?:the|a|an|their|our)\s+", flags=re.IGNORECASE)
#: Conversational lead-in that a greedy target capture drags along:
#: "introduce **us to the** VP of Security".
_TARGET_LEAD_IN = re.compile(
    r"^\s*(?:(?:us|me|our\s+team|somebody|someone|anyone)\b\s*)?"
    r"(?:(?:an?|the)\s+)?(?:warm\s+)?(?:intro(?:duction)?|connection)?\s*"
    r"(?:\b(?:to|with|into)\b\s*)?(?:(?:the|a|an|their|our)\s+)?",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedAsk:
    """What a grammar proposes. Every field may legitimately be empty."""

    account_text: str = ""
    person_name: str = ""
    title: str = ""
    normalized_title_family: str = ""
    domains: tuple[str, ...] = ()
    confidence: Confidence = "none"
    grammar: str = ""
    evidence: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def parsed_anything(self) -> bool:
        return bool(self.account_text or self.person_name or self.title)


def _clean(value: str) -> str:
    text = norm_ws(value)
    text = _TRAILING_NOISE.sub("", text)
    text = _LEADING_NOISE.sub("", text)
    text = text.strip(" .,;:!?—-–")
    return _ARTICLE.sub("", text).strip()


def looks_like_title(value: str) -> bool:
    text = _clean(value).casefold()
    if not text:
        return False
    return bool(_FAMILY_WORD_RE.search(text) or _TITLE_MARKER_RE.search(text))


def strict_title_family(value: object) -> str:
    """Title family, but only when the needle matches on word boundaries."""
    text = norm_text(value)
    if not text:
        return ""
    for family, needles in TITLE_FAMILIES:
        if any(re.search(rf"\b{re.escape(needle)}\b", text) for needle in needles):
            return family
    return ""


def looks_like_person(value: str) -> bool:
    """A name is two or more capitalised words carrying no role marker."""
    text = _clean(value)
    if not text or looks_like_title(text):
        return False
    tokens = text.split()
    if len(tokens) < 2 or len(tokens) > 4:
        return False
    return all(token[:1].isupper() and token.replace("-", "").replace("'", "").isalpha() for token in tokens)


#: Ordered. The first grammar that matches *and validates* wins; earlier entries
#: are the more specific ones. ``account``/``person``/``title`` name the capture
#: groups. The title slot is greedy so that "Head of Data at Acme" splits on the
#: last "at" rather than the first "of".
GRAMMARS: list[tuple[str, str, Confidence, str]] = [
    (
        "corrected_account_parenthetical_title",
        r"\bthe\s+account\s+(?:i\s+)?(?:actually\s+)?(?:need|want)s?\s+is\s+(?P<account>[^(.,]+?)\s*\(\s*(?P<title>[^)]+)\s*\)",
        "high",
        "an explicit correction naming the account actually wanted, with the role in brackets",
    ),
    (
        "who_do_we_know_at_account",
        r"\bknow\w*\s+(?:someone|anyone|anybody)?\s*(?:at|into)\s+(?P<account>[^,.?!]+)\s*[?.]\s*"
        r"(?P<title>[^,.?!]+?)\s+would\s+be\s+ideal",
        "high",
        "'who do we know at <account>? <target> would be ideal'",
    ),
    (
        "person_is_the_person_i_need",
        r"^(?P<person>[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)+)\s+is\s+the\s+person\s+I\s+need\b"
        r".*?\b(?:a|an)\s+(?P<title>[A-Z][\w&' -]+?)(?:\s+somewhere\b|[.,]|$)",
        "medium",
        "a named person and their stated role, with no account given",
    ),
    (
        "path_to_named_person",
        r"\b(?:anyone\s+connected\s+to|looking\s+for\s+a\s+path\s+to)\s+(?P<person>[^,.?!—–]+)",
        "medium",
        "a named person with no account stated",
    ),
    (
        "account_is_the_target",
        r"^(?P<account>[A-Z][^.]{2,60}?)\s+is\s+the\s+target\b",
        "medium",
        "'<account> is the target'",
    ),
    (
        "we_need_account",
        r"^we\s+need\s+(?P<account>[^.]+?)\s*[.]",
        "medium",
        "'we need <account>'",
    ),
    (
        "account_then_person_parenthetical_title",
        r"(?P<account>[^.—–:]+?)\s*[.:]\s*(?P<person>[^(.]+?)\s*\(\s*(?P<title>[^)]+)\s*\)",
        "high",
        "account, then a named person with their title in brackets",
    ),
    (
        "person_is_the_title_there",
        r"(?:getting\s+to|reach|into|at)\s+(?P<account>[^.]+?)\s*[.,]\s*"
        r"(?P<person>[A-Z][^.]*?)\s+is\s+the\s+(?P<title>[^.,]+?)\s+there",
        "high",
        "'<person> is the <title> there' after a named account",
    ),
    (
        "account_then_looking_for_title",
        r"\b(?:at|into|with)\s+(?P<account>[^,.?!]+)\s*[?.,]\s*.{0,80}?"
        r"\b(?:looking\s+for|need\s+an?\s+intro(?:duction)?\s+to)\s+(?P<title>[^,.?!]+)",
        "high",
        "'<account> ... looking for <target>'",
    ),
    (
        "target_at_account",
        r"\b(?:introduc\w*|intro|connect(?:ed)?|put\s+(?:us|me)\s+in\s+touch|trying\s+to\s+reach"
        r"|looking\s+to\s+reach|need\s+to\s+reach|reach)\b[^,.?!]*?\b(?:to|with|into)?\s*"
        r"(?P<title>.+)\s+at\s+(?P<account>[^,.?!—–]+)",
        "high",
        "'<verb> ... <target> at <account>'",
    ),
    (
        "target_of_account",
        r"\b(?:introduc\w*|intro|connect(?:ed)?|trying\s+to\s+reach|reach)\b[^,.?!]*?"
        r"\b(?:to|with|into)?\s*(?P<title>.+?)\s+of\s+(?P<account>[^,.?!—–]+)",
        "medium",
        "'<verb> ... <target> of <account>'",
    ),
    (
        "person_then_role_no_account",
        r"^(?P<person>[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)+)\s+is\s+the\s+person\b.*?\b(?:a|an)\s+(?P<title>[A-Z][^.,]+)",
        "medium",
        "a named person and their role, with no account stated",
    ),
    (
        "account_then_title",
        r"^(?P<account>[^.—–:]+?)\s*[.:]\s*(?P<title>[^.]+?)\s*[.]",
        "medium",
        "account followed by a bare role",
    ),
    (
        "bare_at_account",
        r"\b(?:at|into|with)\s+(?P<account>[A-Z][^,.?!]*)",
        "low",
        "an account name after 'at'/'into', with no target role identified",
    ),
]

#: Wording that means the captured phrase is a clause, not an entity name.
_CLAUSE_MARKERS = re.compile(
    r"\b(?:is|are|was|were|need|needs|needed|want|know|knows|have|has|looking|trying|"
    r"pretty\s+sure|somewhere|anyone|someone)\b",
    flags=re.IGNORECASE,
)


def _downgrade(confidence: Confidence) -> Confidence:
    """One notch less certain, for a match that carries a warning."""
    return {"high": "medium", "medium": "low", "low": "low", "none": "none"}[confidence]  # type: ignore[return-value]


def _plausible_entity(value: str, max_tokens: int) -> bool:
    """Reject a capture that is really a sentence fragment rather than a name."""
    if not value:
        return False
    if len(value.split()) > max_tokens:
        return False
    return not _CLAUSE_MARKERS.search(value)


def parse_ask(text: object) -> ParsedAsk:
    """Best-effort structure for a free-text ask.

    Never raises and never guesses silently: an unparseable ask comes back with
    ``confidence='none'`` and an evidence string saying so, which the caller
    turns into an entity-review action rather than a rejection.
    """
    raw = norm_ws(text)
    if not raw:
        return ParsedAsk(confidence="none", grammar="", evidence="no request text supplied")

    body = _LEADING_NOISE.sub("", raw)
    domains = tuple(extract_domains(raw))

    for name, pattern, confidence, description in GRAMMARS:
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        account = _clean(groups.get("account") or "")
        person = _clean(groups.get("person") or "")
        title = _clean(_TARGET_LEAD_IN.sub("", norm_ws(groups.get("title") or "")))

        # A grammar's "title" slot may in fact hold a person's name.
        if title and not person and looks_like_person(title) and not looks_like_title(title):
            person, title = title, ""
        if person and looks_like_title(person) and not title:
            person, title = "", person
        if person and not looks_like_person(person):
            person = ""
        if not _plausible_entity(account, max_tokens=6) or looks_like_title(account):
            account = ""
        if not _plausible_entity(title, max_tokens=7) or not looks_like_title(title):
            title = ""

        if not account and not person and not title:
            continue

        warnings: list[str] = []
        if title and not strict_title_family(title):
            warnings.append("the role does not map to a known title family, so equivalent asks may not be spotted")
        if not account:
            warnings.append("no target account identified in the request text")

        return ParsedAsk(
            account_text=account,
            person_name=person,
            title=title,
            normalized_title_family=strict_title_family(title),
            domains=domains,
            confidence=_downgrade(confidence) if warnings else confidence,
            grammar=name,
            evidence=f"matched {description}",
            warnings=tuple(warnings),
        )

    return ParsedAsk(
        domains=domains,
        confidence="none",
        grammar="",
        evidence="no known request grammar matched; the target must be entered by hand",
        warnings=("the request text could not be parsed automatically",),
    )
