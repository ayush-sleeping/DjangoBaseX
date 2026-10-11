"""
Django settings for DjangoBaseX.

All environment-specific values come from `.env` (see `.env.example`).
Never read os.environ directly elsewhere — add a setting here and import it.
"""

from pathlib import Path

import environ
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent

# Environment
# -------------------------------------------------------------------------------------------- ::
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000"]),
    CSRF_TRUSTED_ORIGINS=(list, ["http://localhost:3000"]),
    TRUSTED_PROXY_COUNT=(int, 0),
    EMAIL_BACKEND=(str, "django.core.mail.backends.console.EmailBackend"),
    DEFAULT_FROM_EMAIL=(str, "no-reply@example.com"),
    FRONTEND_BASE_URL=(str, "http://localhost:3000"),
    ACCESS_TOKEN_LIFETIME=(int, 600),
    REFRESH_TOKEN_LIFETIME=(int, 1_209_600),
    REFRESH_IDLE_LIFETIME=(int, 604_800),
    REFRESH_ROTATION_GRACE=(int, 15),
    SESSION_LIVENESS_CACHE_TTL=(int, 60),
    AUTH_COOKIE_DOMAIN=(str, ""),
    AUTH_COOKIE_PREFIX=(str, "dbx"),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Applications
# -------------------------------------------------------------------------------------------- ::
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    # Local
    "core",
    "users",
]

# Set before the first migration and never changed after (ADR-0008).
AUTH_USER_MODEL = "users.User"

# Authenticates inactive users too, so login can record *why* it refused (AUTH_BLUEPRINT § 6.2).
# The is_active decision is made in users.services.auth, never by the backend.
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.AllowAllUsersModelBackend"]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # must sit above CommonMiddleware
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.NoStoreForAuthenticatedMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database — SQLite by default; set DATABASE_URL=postgres://... for PostgreSQL
# -------------------------------------------------------------------------------------------- ::
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache — part of the security model, not a performance detail (AUTH_BLUEPRINT § 17.4)
# -------------------------------------------------------------------------------------------- ::
# Throttles, lockout, session liveness and the permission version all live here. LocMem is per
# process, so with more than one worker each of them silently becomes per worker: a shared cache
# (redis://) is required anywhere more than one process serves requests.
CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://")}

# Passwords
# -------------------------------------------------------------------------------------------- ::
# Argon2 first; existing PBKDF2 hashes still verify and are re-hashed on the next login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
# -------------------------------------------------------------------------------------------- ::
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static & media
# -------------------------------------------------------------------------------------------- ::
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# CORS / CSRF — the Next.js frontend runs on a different origin
# -------------------------------------------------------------------------------------------- ::
# Exact origins, scheme included. Never CORS_ALLOW_ALL_ORIGINS with credentials: the library then
# reflects any origin, so every site can make authenticated calls (AUTH_BLUEPRINT § 17.2).
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
# The cookie-auth CSRF header (§ 6.1) must pass preflight, or every unsafe request fails as a
# "CORS error" that hides the auth problem behind it.
CORS_ALLOW_HEADERS = [*default_headers, "x-csrf-token"]
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# Deployment contract (AUTH_BLUEPRINT Ch. 17–20)
# -------------------------------------------------------------------------------------------- ::
# Proxies in front of the app. 0 trusts REMOTE_ADDR; N takes the Nth X-Forwarded-For entry from
# the RIGHT. Wrong here makes per-IP lockout global. Read only through core.http.client_ip().
TRUSTED_PROXY_COUNT = env("TRUSTED_PROXY_COUNT")
# The Django admin is a second auth system; /admin/ is mounted only when this is on (Ch. 20).
ADMIN_ENABLED = env.bool("ADMIN_ENABLED", default=DEBUG)
# Console in development, so a missing SMTP configuration is visible rather than silent (Ch. 18).
EMAIL_BACKEND = env("EMAIL_BACKEND")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
# Where emailed links point. Never derived from the request's Host header.
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL")

# Cookie JWT auth (ADR-0009, AUTH_BLUEPRINT Ch. 6 and § 12)
# -------------------------------------------------------------------------------------------- ::
# Separate from SECRET_KEY: rotating one must not invalidate the other. No default — required.
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY")
ACCESS_TOKEN_LIFETIME = env("ACCESS_TOKEN_LIFETIME")  # seconds
REFRESH_TOKEN_LIFETIME = env("REFRESH_TOKEN_LIFETIME")  # seconds, absolute
REFRESH_IDLE_LIFETIME = env("REFRESH_IDLE_LIFETIME")  # seconds since last refresh
# Two tabs refreshing at once is ordinary use, not theft. 0 disables this and logs people out (A23).
REFRESH_ROTATION_GRACE = env("REFRESH_ROTATION_GRACE")
# The revocation-latency trade (§ 6.4): how long "is this session live" is cached. 0 = always ask.
SESSION_LIVENESS_CACHE_TTL = env("SESSION_LIVENESS_CACHE_TTL")
AUTH_COOKIE_DOMAIN = env("AUTH_COOKIE_DOMAIN")
AUTH_COOKIE_PREFIX = env("AUTH_COOKIE_PREFIX")
# Never hard-code False: it would ship to production.
AUTH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", default=not DEBUG)

# Django REST Framework
# -------------------------------------------------------------------------------------------- ::
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "users.authentication.CookieJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "600/min"},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "DjangoBaseX API",
    "DESCRIPTION": "REST API for DjangoBaseX — a Django 5 + Next.js starter boilerplate.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
