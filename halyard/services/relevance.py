"""Organizational relevance between a known contact and the requested buyer.

A colleague path says "the connector knows somebody at the account". That is
true of a Controller and of a junior engineer alike, and today the ranker treats
them identically unless their title family is an exact match. This module adds
the one distinction an operator makes instinctively: whether the person we
actually know sits close enough to the requested buyer, organizationally, to be
worth walking through first.

It is deliberately coarse. Three tiers, keyword-driven, no scoring of seniority
beyond "is this person a senior leader or not", and an empty answer whenever the
title is missing or unrecognised — an unknown title never penalises a path, it
simply produces no factor. The vocabulary lives here rather than in
``halyard.matching.normalize`` so that the audit's entity matching is untouched
by a presentation-order heuristic.
"""

from __future__ import annotations

from ..matching.normalize import norm_text

SAME_FUNCTION = "same_function"
ADJACENT_FUNCTION = "adjacent_function"
SENIOR_PEER = "senior_peer"

#: Coarse functional areas, matched on the normalized title text. A title may
#: hit several groups; the first match in this order wins, so the more specific
#: functions are listed before the general ones.
FUNCTION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "security",
        ("chief information security", "ciso", "chief security", "head of security", "security officer",
         "vp security", "vp of security", "director of security", "information security"),
    ),
    (
        "finance",
        ("chief financial", "cfo", "controller", "vp finance", "vp of finance", "head of finance",
         "director of finance", "finance director", "treasurer", "financial planning", "chief accounting"),
    ),
    (
        "data",
        ("chief data", "head of data", "vp data", "vp of data", "data and analytics", "data & analytics",
         "chief analytics"),
    ),
    (
        "product",
        ("chief product", "cpo", "head of product", "vp product", "vp of product", "director of product",
         "product director"),
    ),
    (
        "marketing",
        ("chief marketing", "cmo", "head of marketing", "vp marketing", "vp of marketing", "demand generation"),
    ),
    (
        "technology",
        ("chief technology", "chief technical", "cto", "chief information officer", "cio", "chief digital",
         "chief architect", "head of engineering", "vp engineering", "vp of engineering", "svp engineering",
         "head of platform", "platform engineering", "head of infrastructure", "principal architect",
         "enterprise architecture", "director of it", "head of automation",
         "engineering manager", "director of software engineering", "staff engineer", "principal engineer",
         "software engineer", "developer productivity", "developer experience"),
    ),
    (
        "operations",
        ("chief operating", "coo", "head of operations", "vp operations", "vp of operations", "chief of staff"),
    ),
    (
        "executive",
        ("chief executive", "ceo", "president", "founder", "managing director", "general manager"),
    ),
)

#: Functions that routinely sit at the same table as one another. Symmetric.
ADJACENT_FUNCTIONS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"security", "technology"}),
        frozenset({"data", "technology"}),
        frozenset({"product", "technology"}),
        frozenset({"finance", "executive"}),
        frozenset({"operations", "executive"}),
        frozenset({"finance", "operations"}),
        frozenset({"marketing", "product"}),
    }
)

#: Marks a title as leadership. Presence of any of these is the whole test — no
#: attempt is made to grade seniority beyond this line, so an "Engineering
#: Manager" or a "Staff Engineer" simply carries no leadership marker and
#: produces no tier.
SENIOR_NEEDLES: tuple[str, ...] = (
    "chief", "ceo", "cfo", "coo", "cto", "cio", "ciso", "cmo", "cpo", "cdo",
    "president", "founder", "partner", "managing director", "head of",
    "director", "vp ", "vp of", "vice president", "svp", "evp",
    "controller", "treasurer",
)


def function_group(title: object) -> str:
    """The coarse functional area of a title, or "" when it is unrecognised."""
    text = norm_text(title)
    if not text:
        return ""
    for group, needles in FUNCTION_GROUPS:
        if any(needle in text for needle in needles):
            return group
    return ""


def is_senior(title: object) -> bool:
    """Whether a title carries a leadership marker rather than reading as a
    manager or an individual contributor."""
    text = norm_text(title)
    if not text:
        return False
    padded = f" {text} "
    return any(needle in padded for needle in SENIOR_NEEDLES)


def relevance_tier(target_title: object, contact_title: object) -> str:
    """How organizationally close the known contact is to the requested buyer.

    Returns ``same_function``, ``adjacent_function``, ``senior_peer`` or "".
    Both titles must be recognised for anything but "" to come back: a missing
    or unusual title yields no tier and therefore no ranking factor.
    """
    target_group = function_group(target_title)
    contact_group = function_group(contact_title)
    if not target_group or not contact_group:
        return ""
    if not is_senior(contact_title):
        return ""
    if target_group == contact_group:
        return SAME_FUNCTION
    if frozenset({target_group, contact_group}) in ADJACENT_FUNCTIONS:
        return ADJACENT_FUNCTION
    if is_senior(target_title):
        return SENIOR_PEER
    return ""


#: Operator-facing sentence for each tier. ``{contact}`` is the known contact's
#: title as recorded, so the operator sees the fact the tier was derived from.
TIER_STATEMENTS: dict[str, str] = {
    SAME_FUNCTION: "Known contact ({contact}) works in the same function as the requested buyer",
    ADJACENT_FUNCTION: "Known contact ({contact}) works alongside the requested buyer's function",
    SENIOR_PEER: "Known contact ({contact}) is a senior peer of the requested buyer",
}


def tier_statement(tier: str, contact_title: str) -> str:
    return TIER_STATEMENTS[tier].format(contact=contact_title.strip() or "title unrecorded")


__all__ = [
    "ADJACENT_FUNCTION",
    "ADJACENT_FUNCTIONS",
    "FUNCTION_GROUPS",
    "SAME_FUNCTION",
    "SENIOR_PEER",
    "function_group",
    "is_senior",
    "relevance_tier",
    "tier_statement",
]
