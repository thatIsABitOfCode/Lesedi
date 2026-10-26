def record(*args, **kwargs):
    """Convenience wrapper: `from apps import audit; audit.record(...)`.

    Imported lazily so this package can be imported before apps are loaded.
    """
    from .services import record as _record

    return _record(*args, **kwargs)
