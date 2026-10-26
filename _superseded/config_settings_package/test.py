"""Test settings. External services are never contacted."""
import tempfile
from pathlib import Path

from .base import derive_fernet_key
from .dev import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-only-secret-key-not-for-any-real-deployment"
ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

NOTIFICATIONS_MODE = "simulation"
NOTIFICATION_MAX_ATTEMPTS = 3
NOTIFICATION_RETRY_DELAY_SECONDS = 0

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"

EVIDENCE_ROOT = Path(tempfile.mkdtemp(prefix="lesedi-test-evidence-"))
EVIDENCE_MAX_BYTES = 200 * 1024  # small, so size-limit tests are cheap
EVIDENCE_ENCRYPTION_KEY = derive_fernet_key(SECRET_KEY)
