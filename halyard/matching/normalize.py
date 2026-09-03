"""Normalization primitives shared by every audit step.

Normalized values are for *matching only*. Display values always keep the raw
form so that provenance back to the source file is never lost.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

LEGAL_SUFFIXES = {
    "inc",
    "inc.",
    "incorporated",
    "llc",
    "l.l.c.",
    "ltd",
    "ltd.",
    "limited",
    "plc",
    "corp",
    "corp.",
    "corporation",
    "co",
    "co.",
    "company",
    "gmbh",
    "ag",
    "sa",
    "s.a.",
    "nv",
    "bv",
    "ab",
    "oy",
    "as",
    "pty",
    "llp",
    "lp",
    "group",
    "holdings",
}

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_DOMAIN_RE = re.compile(r"\b([a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+)\b", flags=re.IGNORECASE)

TITLE_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    ("ceo", ("chief executive", "ceo")),
    ("coo", ("chief operating", "coo")),
    ("cfo", ("chief financial", "cfo")),
    ("cto", ("chief technology", "chief technical", "cto")),
    ("cio", ("chief information officer", "cio")),
    ("ciso", ("chief information security", "ciso")),
    ("cdo_data", ("chief data", "vp data", "head of data", "data & analytics", "data and analytics")),
    ("cdo_digital", ("chief digital", "svp digital", "head of digital", "digital transformation")),
    ("cpo", ("chief product", "cpo")),
    ("cmo", ("chief marketing", "cmo")),
    ("engineering_exec", ("vp engineering", "vp of engineering", "svp engineering", "head of engineering")),
    ("platform", ("platform engineering", "platform lead", "head of platform", "principal architect")),
    ("devprod", ("developer productivity", "developer experience")),
    ("product", ("product director", "director of product", "head of product", "vp product")),
    ("innovation", ("head of innovation", "innovation")),
    ("eng_manager", ("engineering manager", "director of software engineering", "senior manager, engineering")),
    ("ic_engineering", ("staff engineer", "principal engineer", "software engineer")),
]


def norm_ws(value: object) -> str:
    """Trim and collapse internal whitespace; non-strings become ""."""
    if value is None:
        return ""
    text = str(value)
    if text.strip().lower() in {"nan", "none"}:
        return ""
    return _WS_RE.sub(" ", text).strip()


def norm_text(value: object) -> str:
    """Casefolded, unicode-normalized, punctuation-stripped comparison key."""
    text = norm_ws(value)
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip().casefold()


# Letters that carry no combining mark and therefore survive NFKD decomposition.
_TRANSLITERATIONS = str.maketrans(
    {"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ß": "ss", "đ": "d", "Đ": "D", "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L"}
)


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.translate(_TRANSLITERATIONS))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def norm_person(value: object) -> str:
    """Comparison key for a person name (accent-insensitive, hyphens kept apart)."""
    text = norm_text(value)
    return strip_accents(text)


def strip_legal_suffix(tokens: list[str]) -> list[str]:
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens = tokens[:-1]
    return tokens


def norm_company(value: object) -> str:
    """Comparison key for a company name: accents, punctuation and trailing
    legal suffixes removed. ``Ellerby Semiconductor, Inc.`` -> ``ellerby
    semiconductor``. Never used on its own to merge two entities."""
    text = strip_accents(norm_text(value))
    tokens = strip_legal_suffix(text.split())
    return " ".join(tokens)


def company_core(value: object) -> str:
    """First token of a normalized company name; used only to *detect* look-alike
    entities that must be held apart (``Apex Holdings`` vs ``Apex Logistics``)."""
    normalized = norm_company(value)
    return normalized.split(" ")[0] if normalized else ""


def norm_domain(value: object) -> str:
    """Lowercase registrable-ish domain: scheme, ``www.`` and paths removed."""
    text = norm_ws(value).casefold()
    if not text:
        return ""
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/")[0].split("?")[0]
    text = text.removeprefix("www.")
    return text.strip(". ")


def extract_domains(text: object) -> list[str]:
    """Domains mentioned in free text (Slack asks sometimes carry only a domain)."""
    raw = norm_ws(text)
    if not raw:
        return []
    found = [norm_domain(m.group(1)) for m in _DOMAIN_RE.finditer(raw)]
    return [d for d in found if "." in d]


def norm_url(value: object) -> str:
    """Comparison key for a profile URL (unique identifier tier)."""
    text = norm_ws(value).casefold()
    if not text:
        return ""
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.removeprefix("www.")
    return text.rstrip("/")


def title_family(value: object) -> str:
    """Coarse role bucket used to spot operationally equivalent asks.

    Returns "" when no family matches - callers must treat that as unknown
    rather than as a match.
    """
    text = norm_text(value)
    if not text:
        return ""
    for family, needles in TITLE_FAMILIES:
        if any(needle in text for needle in needles):
            return family
    return ""


def parse_date(value: object) -> date | None:
    """Parse an ISO-ish date; unparseable or empty values return None."""
    text = norm_ws(value)
    if not text:
        return None
    text = text.split("T")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_partial_date(value: object) -> date | None:
    """Parse a date that may be year-only.

    ``investor_network`` records employment as a bare year; a bare year is
    coarsened to 1 January of that year, which is only ever used to test whether
    a relationship pre-dates a request.
    """
    text = norm_ws(value)
    if re.fullmatch(r"\d{4}", text):
        return date(int(text), 1, 1)
    return parse_date(text)


def parse_timestamp(value: object) -> datetime | None:
    text = norm_ws(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_malformed_name(value: object) -> bool:
    """Names that look like data defects rather than people."""
    text = norm_ws(value)
    if not text:
        return False
    if not any(ch.isalpha() for ch in text):
        return True
    if text != text.strip():
        return True
    if len(text) < 3:
        return True
    if text.isupper() and len(text.split()) > 1:
        return True
    if re.search(r"\d", text):
        return True
    if re.search(r"\s{2,}", str(value)):
        return True
    return False


def has_casing_defect(value: object) -> bool:
    """ALL-CAPS or all-lowercase multi-character display values."""
    text = norm_ws(value)
    if len(text) < 3 or not any(ch.isalpha() for ch in text):
        return False
    letters = [ch for ch in text if ch.isalpha()]
    return all(ch.isupper() for ch in letters) or all(ch.islower() for ch in letters)


def has_whitespace_defect(value: object) -> bool:
    if value is None:
        return False
    text = str(value)
    if text.strip().lower() in {"nan", "none"}:
        return False
    return text != _WS_RE.sub(" ", text).strip()
