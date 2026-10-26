"""Test settings: development-safe defaults, eager Celery, in-memory cache, simulation notifications.

Tests always run in development mode, whatever the shell or .env says, so they can never behave like production
(no HTTPS redirect, no manifest static storage that needs collectstatic) and can never send a real message.

Set DATABASE_ENGINE=sqlite for a quick run without PostgreSQL. The concurrency test is skipped on sqlite.
"""
import os

os.environ["DJANGO_DEBUG"] = "1"
os.environ["LESEDI_NOTIFICATION_MODE"] = "simulation"
os.environ["REDIS_URL"] = ""
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-not-for-any-real-use")

from .settings import *  # noqa: E402,F401,F403

DEBUG = True
CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EVIDENCE_STORAGE_DIR = BASE_DIR / ".test_private_storage"
ALLOWED_HOSTS = ["testserver", "localhost"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
