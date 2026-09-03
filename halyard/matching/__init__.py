"""Entity-resolution primitives shared by the forensic audit and the application.

The audit and the product must agree, record for record, on what counts as the
same account and the same person. That is only true if they run the same code,
so this package is the single implementation of normalization, account
canonicalization, person resolution and Slack intent classification. Neither
``analysis/audit`` nor ``halyard/ingest`` may fork it.
"""

from .accounts import AccountMatch, AccountResolver, canonical_key
from .people import PersonMatch, PersonResolver
from .slack import classify, looks_like_ask, referred_person

__all__ = [
    "AccountMatch",
    "AccountResolver",
    "canonical_key",
    "PersonMatch",
    "PersonResolver",
    "classify",
    "looks_like_ask",
    "referred_person",
]
