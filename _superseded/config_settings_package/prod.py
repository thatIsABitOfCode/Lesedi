"""Production settings. Fails fast when required configuration is missing."""
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS as _HOSTS
from .base import env, env_bool, env_int, require_env

DEBUG = False

SECRET_KEY = require_env("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith(("dev-only", "replace-me")):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a long, random, non-placeholder value.")

ALLOWED_HOSTS = _HOSTS
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list your real hostnames.")

EVIDENCE_ENCRYPTION_KEY = require_env("EVIDENCE_ENCRYPTION_KEY")
try:
    Fernet(EVIDENCE_ENCRYPTION_KEY)
except (ValueError, TypeError) as exc:
    raise ImproperlyConfigured("EVIDENCE_ENCRYPTION_KEY is not a valid Fernet key.") from exc

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False  # enable only once you are certain about preload
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# A shared cache is required so rate limits work across processes.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": require_env("REDIS_URL"),
    }
}

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = True
