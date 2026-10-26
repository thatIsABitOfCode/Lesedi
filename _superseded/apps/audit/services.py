"""Audit recording with built-in data minimisation."""
import logging

from .models import AuditEvent

logger = logging.getLogger(__name__)

# Any metadata key containing one of these words (split on "_") is dropped.
FORBIDDEN_TOKENS = {
    "password", "token", "secret", "phone", "email", "address", "location",
    "latitude", "longitude", "lat", "lng", "note", "message", "body", "content",
    "filename", "name", "destination", "instruction", "text", "description",
}
MAX_VALUE_LENGTH = 80


def _clean(metadata):
    clean = {}
    for key, value in metadata.items():
        tokens = set(str(key).lower().split("_"))
        if tokens & FORBIDDEN_TOKENS:
            logger.warning("Audit metadata key %r dropped as potentially sensitive", key)
            continue
        if isinstance(value, (bool, int, float)) or value is None:
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:MAX_VALUE_LENGTH]
        else:
            clean[key] = str(value)[:MAX_VALUE_LENGTH]
    return clean


def record(actor, action, target=None, **metadata):
    """Write an audit event. `target` is any model instance (only type and id are stored)."""
    actor = actor if getattr(actor, "pk", None) else None
    return AuditEvent.objects.create(
        actor=actor,
        action=action[:64],
        target_type=target.__class__.__name__ if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        metadata=_clean(metadata),
    )
