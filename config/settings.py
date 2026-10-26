"""LESEDI settings. All secrets and environment-specific values come from environment variables."""
import base64
import hashlib
import os
from pathlib import Path
from dotenv import load_dotenv

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-outside-development"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set in production.")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
ADMIN_URL = os.environ.get("DJANGO_ADMIN_URL", "admin/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "audit",
    "safety",
    "notifications",
    "guardian",
    "shield",
    "evidence",
    "community",
    "core",
    "amani",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SafetyHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
                "core.context_processors.lesedi",
            ],
        },
    },
]

# --- Database -------------------------------------------------------------
if os.environ.get("DATABASE_ENGINE", "sqlite") == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "lesedi"),
            "USER": os.environ.get("POSTGRES_USER", "lesedi"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Cache / Celery ---------------------------------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_TIME_LIMIT = 60
CELERY_BEAT_SCHEDULE = {
    # Guardian Mode escalation: find activations whose acknowledgement deadline has passed.
    "guardian-process-due": {"task": "guardian.process_due_actions", "schedule": 15.0},
    # Community feed retention: delete rejected/resolved reports and closed concerns past their date.
    "community-purge-expired": {"task": "community.purge_expired", "schedule": 24 * 3600.0},
}

# --- Auth -------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:landing"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "20/min", "user": "240/min", "guardian_activate": "10/min"},
}

# --- Sessions / cookies / headers -------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True  # sliding expiry
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = False  # enable deliberately once you are sure
    if env_bool("DJANGO_BEHIND_TLS_PROXY", False):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Uploads up to 12 MB are held in memory. Anything larger is spooled by Django to a temporary file (deleted
# after the request) before the vault rejects it for exceeding EVIDENCE_MAX_BYTES (10 MB by default).
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# --- Static files -------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# --- Email ----------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@lesedi.invalid")

# --- LESEDI -----------------------------------------------------------------------
LESEDI_NOTIFICATION_MODE = os.environ.get("LESEDI_NOTIFICATION_MODE", "simulation")
LESEDI_PUBLIC_BASE_URL = os.environ.get("LESEDI_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
LESEDI_QUICK_EXIT_URL = os.environ.get("LESEDI_QUICK_EXIT_URL", "https://www.wikipedia.org")
GUARDIAN_MAX_SEND_ATTEMPTS = int(os.environ.get("GUARDIAN_MAX_SEND_ATTEMPTS", "2"))
GUARDIAN_ACK_TOKEN_MAX_AGE = int(os.environ.get("GUARDIAN_ACK_TOKEN_MAX_AGE", str(24 * 3600)))
INVITATION_MAX_AGE = 7 * 24 * 3600
# Rejected or resolved community reports and closed Witness concerns are deleted after this many days
# by `python manage.py purge_community` (schedule it).
COMMUNITY_RETENTION_DAYS = int(os.environ.get("COMMUNITY_RETENTION_DAYS", "90"))

EVIDENCE_STORAGE_DIR = Path(os.environ.get("EVIDENCE_STORAGE_DIR", BASE_DIR / "private_storage"))
EVIDENCE_MAX_BYTES = int(os.environ.get("EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
EVIDENCE_ENCRYPTION_KEYS = env_list("EVIDENCE_ENCRYPTION_KEYS")
if not EVIDENCE_ENCRYPTION_KEYS:
    if DEBUG:
        EVIDENCE_ENCRYPTION_KEYS = [
            base64.urlsafe_b64encode(hashlib.sha256(("evidence:" + SECRET_KEY).encode()).digest()).decode()
        ]
    else:
        raise ImproperlyConfigured("EVIDENCE_ENCRYPTION_KEYS must be set in production.")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Johannesburg"
USE_I18N = True
USE_TZ = True

# Optional Groq AI companion: secret stays on server.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
