"""Workflow state, routing state and outcome — three separate axes.

Why three and not one:

* **workflow state** answers "what does a human have to do next?";
* **route status** answers "how far has a route to the target been taken?";
* **outcome** answers "what actually happened?" and only ever records observed
  facts.

Consequences that the state machine has to guarantee:

* Silence is not an outcome. There is no ``NO_RESPONSE`` state; a quiet request
  keeps its workflow state and is flagged ``potentially_stale`` separately.
* ``NO_OBSERVABLE_PATH`` is an active operational condition. It keeps an owner,
  a next action and a due date, and it stays in the working queue.
* Ambiguous entity resolution is actionable (``NEEDS_ENTITY_REVIEW``), never a
  dead end.
* A connector is only ``CONNECTOR_CONFIRMED`` after a human route review; path
  discovery never confirms anybody.
* Nothing reaches ``CLOSED`` automatically — only an explicit transition
  carrying a reason.
"""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    NEEDS_TRIAGE = "NEEDS_TRIAGE"
    NEEDS_ENTITY_REVIEW = "NEEDS_ENTITY_REVIEW"
    PATH_REVIEW = "PATH_REVIEW"
    AWAITING_CONNECTOR = "AWAITING_CONNECTOR"
    INTRO_SENT = "INTRO_SENT"
    COMPLETED = "COMPLETED"
    NO_OBSERVABLE_PATH = "NO_OBSERVABLE_PATH"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


class RouteStatus(str, Enum):
    NONE = "NONE"
    CANDIDATES_IDENTIFIED = "CANDIDATES_IDENTIFIED"
    ROUTE_SELECTED = "ROUTE_SELECTED"
    CONNECTOR_CONFIRMED = "CONNECTOR_CONFIRMED"
    ROUTE_FAILED = "ROUTE_FAILED"


class Outcome(str, Enum):
    UNKNOWN = "UNKNOWN"
    INTRO_SENT = "INTRO_SENT"
    MEETING_BOOKED = "MEETING_BOOKED"
    OPPORTUNITY_CREATED = "OPPORTUNITY_CREATED"
    DECLINED = "DECLINED"
    NO_INTRO = "NO_INTRO"


class StateSource(str, Enum):
    """How the state was arrived at — never hidden from the operator."""

    OBSERVED_EVENT = "observed_event"
    EXPLICIT_STATEMENT = "explicit_statement"
    DECLARED_ONLY = "declared_only"
    NO_EVIDENCE = "no_evidence"
    OPERATOR_TRANSITION = "operator_transition"
    LIVE_INTAKE = "live_intake"


#: The only state a request may reach without a human saying so is the one it is
#: derived into at ingest; every later move is an explicit transition.
ALLOWED_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.NEEDS_TRIAGE: {
        WorkflowState.NEEDS_ENTITY_REVIEW,
        WorkflowState.PATH_REVIEW,
        WorkflowState.NO_OBSERVABLE_PATH,
        WorkflowState.BLOCKED,
        WorkflowState.CLOSED,
    },
    WorkflowState.NEEDS_ENTITY_REVIEW: {
        WorkflowState.NEEDS_TRIAGE,
        WorkflowState.PATH_REVIEW,
        WorkflowState.NO_OBSERVABLE_PATH,
        WorkflowState.BLOCKED,
        WorkflowState.CLOSED,
    },
    WorkflowState.PATH_REVIEW: {
        WorkflowState.NEEDS_ENTITY_REVIEW,
        WorkflowState.AWAITING_CONNECTOR,
        WorkflowState.NO_OBSERVABLE_PATH,
        WorkflowState.BLOCKED,
        WorkflowState.CLOSED,
    },
    WorkflowState.AWAITING_CONNECTOR: {
        WorkflowState.PATH_REVIEW,
        WorkflowState.INTRO_SENT,
        WorkflowState.BLOCKED,
        WorkflowState.NO_OBSERVABLE_PATH,
        WorkflowState.CLOSED,
    },
    WorkflowState.INTRO_SENT: {
        WorkflowState.COMPLETED,
        WorkflowState.BLOCKED,
        WorkflowState.PATH_REVIEW,
        WorkflowState.CLOSED,
    },
    WorkflowState.COMPLETED: {WorkflowState.CLOSED},
    WorkflowState.NO_OBSERVABLE_PATH: {
        WorkflowState.PATH_REVIEW,
        WorkflowState.NEEDS_ENTITY_REVIEW,
        WorkflowState.BLOCKED,
        WorkflowState.CLOSED,
    },
    WorkflowState.BLOCKED: {
        WorkflowState.NEEDS_TRIAGE,
        WorkflowState.PATH_REVIEW,
        WorkflowState.AWAITING_CONNECTOR,
        WorkflowState.NO_OBSERVABLE_PATH,
        WorkflowState.CLOSED,
    },
    #: Terminal. Reopening is a deliberate act and goes back through triage.
    WorkflowState.CLOSED: {WorkflowState.NEEDS_TRIAGE},
}

#: States that still owe somebody a next action.
ACTIVE_STATES = frozenset(
    {
        WorkflowState.NEEDS_TRIAGE,
        WorkflowState.NEEDS_ENTITY_REVIEW,
        WorkflowState.PATH_REVIEW,
        WorkflowState.AWAITING_CONNECTOR,
        WorkflowState.INTRO_SENT,
        WorkflowState.NO_OBSERVABLE_PATH,
        WorkflowState.BLOCKED,
    }
)

#: Only these two mean "nobody needs to do anything else".
SETTLED_STATES = frozenset({WorkflowState.COMPLETED, WorkflowState.CLOSED})

NEXT_ACTIONS: dict[WorkflowState, str] = {
    WorkflowState.NEEDS_TRIAGE: "Triage: confirm the owner, the target and whether this ask is still live",
    WorkflowState.NEEDS_ENTITY_REVIEW: "Resolve the target account / person against the candidate matches",
    WorkflowState.PATH_REVIEW: "Review candidate paths and select a route to ask",
    WorkflowState.AWAITING_CONNECTOR: "Follow up with the selected connector",
    WorkflowState.INTRO_SENT: "Confirm whether the introduction produced a meeting",
    WorkflowState.NO_OBSERVABLE_PATH: "Escalate: no path is observable — decide on sourcing a new route or standing down",
    WorkflowState.BLOCKED: "Escalate the blocker and decide the next route",
    WorkflowState.COMPLETED: "",
    WorkflowState.CLOSED: "",
}


class TransitionError(ValueError):
    """Raised when a caller asks for a transition the state machine forbids."""

    def __init__(self, current: WorkflowState, requested: WorkflowState):
        self.current = current
        self.requested = requested
        self.allowed = sorted(s.value for s in ALLOWED_TRANSITIONS[current])
        super().__init__(
            f"{current.value} -> {requested.value} is not an allowed transition; allowed: {', '.join(self.allowed)}"
        )


def check_transition(current: WorkflowState, requested: WorkflowState) -> None:
    if requested not in ALLOWED_TRANSITIONS[current]:
        raise TransitionError(current, requested)
