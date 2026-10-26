"""Development settings. Never use in production."""
from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS as _HOSTS
from .base import derive_fernet_key, env, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = env("DJANGO_SECRET_KEY") or "dev-only-insecure-secret-key-do-not-use-in-production"
ALLOWED_HOSTS = _HOSTS or ["localhost", "127.0.0.1", "[::1]"]
EVIDENCE_ENCRYPTION_KEY = env("EVIDENCE_ENCRYPTION_KEY") or derive_fernet_key(SECRET_KEY)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
