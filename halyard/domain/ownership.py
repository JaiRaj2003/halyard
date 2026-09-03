"""Who is accountable for a request, and where that answer came from.

Two truths are kept at once. Historically, ownership of these asks was mostly
not evidenced anywhere — ingestion must not paper over that. Operationally, no
request may exist without an owner. So ingestion records the historical fact
(``was_ownerless_at_ingest``, ``observed_owner_id = NULL``) *and* assigns a
fallback operational owner, labelled as a fallback.

A connector is never made the owner. Being asked to help is not accountability.
"""

from __future__ import annotations

from dataclasses import dataclass


class OwnerSource(str):
    pass


OBSERVED_OWNER = "observed_owner"
FALLBACK_REQUESTER = "fallback_requester"
CONFIGURED_TRIAGE_OWNER = "configured_triage_owner"
EXPLICIT_INTAKE = "explicit_intake"
MANUAL_ASSIGNMENT = "manual_assignment"


class OwnershipError(RuntimeError):
    """Raised rather than commit a request with no operational owner."""


@dataclass(frozen=True)
class OwnerDecision:
    owner_id: int
    source: str
    observed_owner_id: int | None
    was_ownerless_at_ingest: bool


def resolve_live_owner(
    explicit_owner_id: int | None,
    triage_owner_id: int | None,
    requester_id: int | None,
) -> tuple[int, str]:
    """Owner for a newly intaken request: explicit → configured triage → requester.

    The caller may omit an owner; the persisted request may not. If none of the
    three yields a person the intake fails instead of committing an orphan.
    """
    if explicit_owner_id is not None:
        return explicit_owner_id, EXPLICIT_INTAKE
    if triage_owner_id is not None:
        return triage_owner_id, CONFIGURED_TRIAGE_OWNER
    if requester_id is not None:
        return requester_id, FALLBACK_REQUESTER
    raise OwnershipError("no operational owner could be resolved; refusing to create an ownerless request")


def resolve_historical_owner(observed_owner_id: int | None, requester_id: int) -> OwnerDecision:
    """Owner for a request ingested from the corpus.

    Evidenced ownership is preserved and carried forward. Where there is none,
    the requester holds it as an explicit fallback and the ownerlessness stays
    on the record permanently.
    """
    if observed_owner_id is not None:
        return OwnerDecision(observed_owner_id, OBSERVED_OWNER, observed_owner_id, False)
    return OwnerDecision(requester_id, FALLBACK_REQUESTER, None, True)
