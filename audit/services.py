from .models import AuditEvent

# Only these metadata keys are ever persisted, so callers cannot leak sensitive values by accident.
ALLOWED_METADATA_KEYS = {"role", "state", "from_state", "to_state", "channel", "status", "permission", "count", "kind", "rank", "mode"}


def record(action, *, actor=None, obj=None, metadata=None):
    clean = {k: v for k, v in (metadata or {}).items() if k in ALLOWED_METADATA_KEYS}
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(getattr(obj, "pk", "")) if obj is not None else "",
        metadata=clean,
    )
