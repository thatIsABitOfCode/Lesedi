"""Small fixed-window rate limiter on the Django cache (Redis in compose, locmem in tests).

Note: client_ip uses REMOTE_ADDR. Behind a reverse proxy, configure the proxy to set it correctly
(do not trust X-Forwarded-For blindly)."""
from django.core.cache import cache


def client_ip(request) -> str:
    return request.META.get("REMOTE_ADDR", "unknown")


def hit(key: str, *, limit: int, window: int) -> bool:
    """Record one hit; return True while the caller is within the limit."""
    cache_key = f"rl:{key}"
    cache.add(cache_key, 0, window)
    try:
        count = cache.incr(cache_key)
    except ValueError:  # key expired between add and incr
        cache.set(cache_key, 1, window)
        count = 1
    return count <= limit
