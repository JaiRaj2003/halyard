"""Request bodies. Deliberately permissive about ownership, strict about intent.

``CreateRequest`` has no required owner field: intake should read like a Slack
message. The server resolves the owner and the persisted row can never be
ownerless. ``target_person_evidenced`` is the only way live input creates a
canonical person, and persona wording still never does.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateRequest(BaseModel):
    requester_name: str = Field(min_length=1)
    target_account_text: str = Field(min_length=1)
    raw_ask: str = ""
    target_person_name: str = ""
    target_title: str = ""
    deal_value_usd: int = 0
    urgency: str = ""
    request_id: str | None = None
    operational_owner_id: int | None = None
    target_person_evidenced: bool = False


class IntakeStart(BaseModel):
    """A Slack-style ask. Structured fields are optional overrides of the parse."""

    raw_ask: str = ""
    requester_name: str = Field(min_length=1)
    account_text: str = ""
    target_person_name: str = ""
    target_title: str = ""
    deal_value_usd: int = 0
    urgency: str = ""
    operational_owner_id: int | None = None
    request_id: str | None = None
    target_person_evidenced: bool = False


class ConfirmTarget(BaseModel):
    account_id: int | None = None
    person_id: int | None = None
    target_title: str = ""
    actor: str = "operator"
    note: str = ""


class RouteDecision(BaseModel):
    path_id: int
    decision: str = Field(pattern="^(confirm|reject)$")
    actor: str = "operator"
    note: str = ""


class TransitionRequest(BaseModel):
    to_state: str
    actor: str = "operator"
    note: str = ""
    route_status: str | None = None
    outcome: str | None = None
    connector_id: int | None = None
    closure_reason: str = ""


class OwnerRequest(BaseModel):
    operational_owner_id: int
    actor: str = "operator"
    note: str = ""
