"""Classification of Slack thread messages into evidence types.

The channel is template-heavy, so classification is rule based and auditable:
every pattern below is a literal phrase observed in the corpus. Anything that
matches nothing is ``unclassified`` and is reported rather than assumed.

Only ``intro_confirmed`` / ``declined`` / ``closed`` intents would constitute
explicit state evidence; the rest are activity, not state.
"""

from __future__ import annotations

import re

INTENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("intro_confirmed", ("i made the intro", "intro is out", "sent the intro", "intro sent", "connected you both")),
    ("declined", ("can't help", "cannot help", "not comfortable", "won't be able to", "passing on this")),
    ("closed", ("closing this", "we lost this", "dead", "no longer needed", "closed out")),
    ("volunteer_offer", ("happy to reach out", "happy to intro", "leave it with me", "i'll take this one", "direct line to their exec")),
    ("referral_suggestion", ("who might know",)),
    ("no_knowledge", ("no idea sorry",)),
    ("bump", ("bumping this", "asking again")),
    ("possible_duplicate_query", ("same as the one from last month", "did we not already lose this one")),
    ("routing_challenge", ("wrong channel",)),
    ("qualification_question", ("deal size",)),
    ("blocker_note", ("procurement is frozen",)),
    ("entity_warning", ("completely different companies", "that's a different entity")),
]

ASK_PATTERNS: tuple[str, ...] = (
    "who do we know at",
    "need help getting to",
    "trying to reach",
    "any connections into",
    "does anyone know anyone at",
    "long shot",
    "anyone have a path",
    "need an intro at",
    "who knows someone at",
    "anyone connected to",
    "is the person i need",
    "looking for a path to",
    "path into",
    "is the target",
    "the account i actually need",
    "we need",
)

EXPLICIT_STATE_INTENTS = {"intro_confirmed", "declined", "closed"}

_ADDING_RE = re.compile(r"adding\s+(.+?)\s+who might know", flags=re.IGNORECASE)

#: Someone naming a person who may hold a route. Names are matched
#: case-sensitively so ordinary sentence words cannot pose as people.
_NAME = r"(?-i:(?P<name>[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)*))"
_SUGGESTION_RES: tuple[re.Pattern[str], ...] = (
    re.compile(rf"adding\s+{_NAME}\s+who might know", flags=re.IGNORECASE),
    re.compile(
        rf"{_NAME}\s+(?:said|says|mentioned|reckons|thinks|told me)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        rf"{_NAME}\s+(?:might know|may know|knows someone|knows people|has a contact|has a line|"
        r"has a direct line|offered to|can introduce|can intro|could intro)",
        flags=re.IGNORECASE,
    ),
    re.compile(rf"(?:ask|try|speak to|talk to|check with)\s+{_NAME}\b", flags=re.IGNORECASE),
)


def classify(text: str) -> str:
    lowered = text.casefold()
    for intent, needles in INTENT_PATTERNS:
        if any(needle in lowered for needle in needles):
            return intent
    return "unclassified"


def looks_like_ask(text: str) -> bool:
    lowered = text.casefold()
    return any(pattern in lowered for pattern in ASK_PATTERNS)


def referred_person(text: str) -> str:
    match = _ADDING_RE.search(text)
    return match.group(1).strip() if match else ""


def suggested_route_person(text: str) -> str:
    """Who a message says may hold a route. Never a claim that they do."""
    for pattern in _SUGGESTION_RES:
        match = pattern.search(text)
        if match:
            return match.group("name").strip()
    return ""
