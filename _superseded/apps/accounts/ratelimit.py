"""Small cache-based rate limiter for sensitive endpoints.

Uses Django's cache, so production needs the shared Redis cache configured in
settings.prod. Keys are hashed so IP addresses and emails are not stored in
clear text in the cache.
"""
import hashlib
from functools import wraps

from django.core.cache import cache
from django.shortcuts import render


def client_ip(request):
    # NOTE: behind a reverse proxy REMOTE_ADDR is the proxy. Configure the proxy
    # to pass the real address and adapt this function; see README.
    return request.META.get("REMOTE_ADDR", "unknown")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def allow(key, limit, window):
    """Count one hit for `key`. Returns False once `limit` is exceeded in `window` seconds."""
    cache_key = f"rl:{digest(key)}"
    if cache.add(cache_key, 1, timeout=window):
        return True
    try:
        count = cache.incr(cache_key)
    except ValueError:  # key expired between add() and incr()
        cache.set(cache_key, 1, timeout=window)
        return True
    return count <= limit


def too_many(request):
    return render(request, "429.html", status=429)


def throttle(scope, limit, window, methods=("POST",)):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method in methods and not allow(f"{scope}:{client_ip(request)}", limit, window):
                return too_many(request)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
