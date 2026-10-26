"""The Guardian Mode state machine. Valid transitions are enforced on the server."""
from .models import State

TRANSITIONS = {
    State.ACTIVATED: {
        State.ALERTS_PENDING,
        State.ESCALATION_REQUIRED,
        State.CANCELLED,
        State.RESOLVED,
    },
    State.ALERTS_PENDING: {
        State.AWAITING_ACKNOWLEDGEMENT,
        State.ESCALATION_REQUIRED,
        State.ACKNOWLEDGED,
        State.CANCELLED,
        State.RESOLVED,
    },
    State.AWAITING_ACKNOWLEDGEMENT: {
        State.ACKNOWLEDGED,
        State.ESCALATION_REQUIRED,
        State.CANCELLED,
        State.RESOLVED,
    },
    State.ESCALATION_REQUIRED: {
        State.BACKUP_CONTACTED,
        State.ACKNOWLEDGED,
        State.CANCELLED,
        State.RESOLVED,
    },
    State.BACKUP_CONTACTED: {
        State.ACKNOWLEDGED,
        State.ESCALATION_REQUIRED,
        State.CANCELLED,
        State.RESOLVED,
    },
    State.ACKNOWLEDGED: {State.RESOLVED, State.CANCELLED},
    State.RESOLVED: set(),
    State.CANCELLED: set(),
}


def allowed_next(state):
    return TRANSITIONS.get(State(state), set())
