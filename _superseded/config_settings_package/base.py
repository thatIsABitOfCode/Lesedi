"""LESEDI base settings.

All secrets and provider credentials come from environment variables. Nothing
in this file is a real credential.
"""
import base64
import hashlib
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name, default=""):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer.") from exc


def env_list(name):
    return [item.strip() for item in env(name).split(",") if item.strip()]


def require_env(name):
    value = os.environ.get(name, "")
    if not value:
        raise ImproperlyConfigured(f"Required environment variable {name} is not set.")
    return value


def derive_fernet_key(secret):
    """Development/test only: derive a Fernet key from the Django secret."""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()).decode()


DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
ADMIN_URL = env("ADMIN_URL", "admin/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.accounts",
    "apps.audit",
    "apps.notifications",
    "apps.safety_plans",
    "apps.safety_circle",
    "apps.guardian",
    "apps.shield",
    "apps.evidence",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.SessionVersionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.dashboard.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.dashboard.context.lesedi",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=60,
    )
}

AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "dashboard:landing"

# Sessions: sliding 8-hour expiry, HttpOnly, SameSite=Lax. "Sign out everywhere"
# is implemented with User.session_version (see accounts.middleware).
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Johannesburg"
USE_I18N = False  # Translation files are NOT implemented yet; see docs/LIMITATIONS.md
USE_TZ = True

# Target languages (11 official languages + SASL information). Selecting one
# stores a preference only; the interface is English-only in this build.
SUPPORTED_LANGUAGES = [
    ("en", "English"),
    ("zu", "isiZulu"),
    ("xh", "isiXhosa"),
    ("af", "Afrikaans"),
    ("nso", "Sepedi"),
    ("tn", "Setswana"),
    ("st", "Sesotho"),
    ("ts", "Xitsonga"),
    ("ss", "siSwati"),
    ("ve", "Tshivenda"),
    ("nr", "isiNdebele"),
    ("sasl", "South African Sign Language (information only)"),
]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# There is deliberately no MEDIA_URL/MEDIA_ROOT: uploaded evidence is never
# served from a public path. See apps/evidence/storage.py.

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "20/min", "user": "120/min"},
}

# --- Celery ---
CELERY_BROKER_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "guardian-timeouts": {"task": "guardian.process_timeouts", "schedule": 10.0},
    "notifications-requeue": {"task": "notifications.requeue_stuck", "schedule": 30.0},
}

# --- Notifications ---
NOTIFICATIONS_MODE = env("NOTIFICATIONS_MODE", "simulation")
if NOTIFICATIONS_MODE not in {"simulation", "live"}:
    raise ImproperlyConfigured("NOTIFICATIONS_MODE must be 'simulation' or 'live'.")
NOTIFICATION_MAX_ATTEMPTS = env_int("NOTIFICATION_MAX_ATTEMPTS", 3)
NOTIFICATION_RETRY_DELAY_SECONDS = env_int("NOTIFICATION_RETRY_DELAY_SECONDS", 15)

# --- Evidence Vault ---
EVIDENCE_ROOT = Path(env("EVIDENCE_ROOT", str(BASE_DIR / "private_evidence")))
EVIDENCE_MAX_BYTES = env_int("EVIDENCE_MAX_BYTES", 10 * 1024 * 1024)
EVIDENCE_ENCRYPTION_KEY = env("EVIDENCE_ENCRYPTION_KEY")
# Django buffers uploads in memory up to this size, then spools to temp files.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# --- UI / policy ---
QUICK_EXIT_URL = env("QUICK_EXIT_URL", "https://www.wikipedia.org")
POLICY_DRAFT_VERSION = "draft-0.1"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "LESEDI <no-reply@example.org>")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
