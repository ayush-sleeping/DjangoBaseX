"""
Test settings — the only settings pytest uses (ENGINEERING_PRACTICES.md § 5).

Every environment value the base settings read is pinned here BEFORE they are imported.
`read_env` never overrides a variable that is already set, so a developer's `.env` (a kill switch,
a DATABASE_URL, a cache) cannot change what a test sees.
"""

import os

_PINNED_ENV = {
    "APP_ENV": "test",
    # Identity: a name, nothing else, so every derived value is exercised (CONFIGURATION § 7).
    "PRODUCT_NAME": "Test product",
    "PRODUCT_SLUG": "",
    "PRIMARY_DOMAIN": "",
    "PRODUCT_TAGLINE": "",
    "LOG_FORMAT": "console",
    "SECRET_KEY": "test-only-insecure-key-never-used-outside-pytest",
    "DEBUG": "False",
    "ALLOWED_HOSTS": "testserver,localhost",
    "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
    "CSRF_TRUSTED_ORIGINS": "http://localhost:3000",
    # In-memory SQLite unless CI points the suite at a real test database server on purpose.
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "sqlite://:memory:"),
    "CACHE_URL": "locmemcache://",
    "TRUSTED_PROXY_COUNT": "0",
    "ADMIN_ENABLED": "True",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "DEFAULT_FROM_EMAIL": "",
    "FRONTEND_BASE_URL": "http://localhost:3000",
    "JWT_SIGNING_KEY": "test-only-jwt-key-never-used-outside-pytest",
    "ACCESS_TOKEN_LIFETIME": "600",
    "REFRESH_TOKEN_LIFETIME": "1209600",
    "REFRESH_IDLE_LIFETIME": "604800",
    "REFRESH_ROTATION_GRACE": "15",
    "SESSION_LIVENESS_CACHE_TTL": "60",
    "AUTH_COOKIE_DOMAIN": "",
    "AUTH_COOKIE_PREFIX": "",
    # Production-like: Secure cookies with the __Host- prefix, the path most deployments take.
    "AUTH_COOKIE_SECURE": "True",
    "LOCKOUT_THRESHOLD": "10",
    "LOCKOUT_WINDOW": "900",
    "LOCKOUT_DURATION": "900",
    "PASSWORD_RESET_TOKEN_LIFETIME": "1800",
    "PASSWORD_SETUP_TOKEN_LIFETIME": "259200",
    "INVITATION_LIFETIME": "604800",
    "JWT_SIGNING_KEY_FALLBACKS": "",
    "MAX_SESSIONS_PER_USER": "10",
    "LOGIN_ATTEMPT_RETENTION_DAYS": "90",
    "SESSION_RETENTION_DAYS": "30",
    "PASSWORD_RESET_TOKEN_RETENTION_DAYS": "7",
    # A valid, test-only Fernet key (32 zero bytes, urlsafe-base64). Never used outside pytest.
    "FIELD_ENCRYPTION_KEYS": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "MFA_ISSUER": "",
    "MFA_TOKEN_LIFETIME": "300",
}
os.environ.update(_PINNED_ENV)

from .settings import *  # noqa: E402, F403

# Never the developer's files or bucket. Every alias in memory.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
}

# Tests use a per-process cache on purpose (cleared per test by conftest), with DEBUG=False. That is
# exactly what dbx.E005 refuses for a deployment, so it is silenced here and only here.
SILENCED_SYSTEM_CHECKS = ["dbx.E005"]

# Hashing is deliberately slow; tests only need it to be correct.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
