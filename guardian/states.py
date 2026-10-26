"""Guardian Mode state machine. Transitions are enforced on the server in guardian.services.

INACTIVE is represented by the absence of an open activation.

ACKNOWLEDGED means a responder confirmed they SAW the alert. It does not mean anyone is travelling,
has arrived, or that any authority has been contacted. LESEDI has no emergency-service integration."""
from django.db import models


class State(models.TextChoices):
    ACTIVATED = "activated", "Activated"
    ALERTS_PENDING = "alerts_pending", "Preparing alerts"
    AWAITING_ACKNOWLEDGEMENT = "awaiting_acknowledgement", "Waiting for acknowledgement"
    ESCALATION_REQUIRED = "escalation_required", "Trying the next responder"
    BACKUP_CONTACTED = "backup_contacted", "Backup responder notified - waiting"
    ACKNOWLEDGED = "acknowledged", "A responder acknowledged"
    ESCALATION_EXHAUSTED = "escalation_exhausted", "No responder acknowledged"
    RESOLVED = "resolved", "Resolved"
    CANCELLED = "cancelled", "Cancelled"


OPEN_STATES = (
    State.ACTIVATED, State.ALERTS_PENDING, State.AWAITING_ACKNOWLEDGEMENT, State.ESCALATION_REQUIRED,
    State.BACKUP_CONTACTED, State.ACKNOWLEDGED, State.ESCALATION_EXHAUSTED,
)
TERMINAL_STATES = (State.RESOLVED, State.CANCELLED)
WAITING_STATES = (State.AWAITING_ACKNOWLEDGEMENT, State.BACKUP_CONTACTED)

_END = (State.RESOLVED, State.CANCELLED)
_RAW_TRANSITIONS = {
    State.ACTIVATED: (State.ALERTS_PENDING,) + _END,
    State.ALERTS_PENDING: (State.AWAITING_ACKNOWLEDGEMENT, State.ESCALATION_REQUIRED) + _END,
    State.AWAITING_ACKNOWLEDGEMENT: (State.ACKNOWLEDGED, State.ESCALATION_REQUIRED) + _END,
    State.ESCALATION_REQUIRED: (State.BACKUP_CONTACTED, State.ESCALATION_EXHAUSTED) + _END,
    State.BACKUP_CONTACTED: (State.ACKNOWLEDGED, State.ESCALATION_REQUIRED) + _END,
    State.ACKNOWLEDGED: _END,
    State.ESCALATION_EXHAUSTED: (State.ACKNOWLEDGED,) + _END,
    State.RESOLVED: (),
    State.CANCELLED: (),
}


def _v(x):
    return getattr(x, "value", x)


# Keyed by plain strings so lookups work whether a state is an enum member or a value read from the database.
ALLOWED_TRANSITIONS = {_v(k): tuple(_v(x) for x in v) for k, v in _RAW_TRANSITIONS.items()}


def can_transition(old, new) -> bool:
    return _v(new) in ALLOWED_TRANSITIONS.get(_v(old), ())
