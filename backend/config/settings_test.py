"""
Test settings — the only settings pytest uses (ENGINEERING_PRACTICES.md § 5).

Every environment value the base settings read is pinned here BEFORE they are imported.
`read_env` never overrides a variable that is already set, so a developer's `.env` (a kill switch,
a DATABASE_URL, a cache) cannot change what a test sees.
"""

import os

_PINNED_ENV = {
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
    "DEFAULT_FROM_EMAIL": "no-reply@example.com",
    "FRONTEND_BASE_URL": "http://localhost:3000",
}
os.environ.update(_PINNED_ENV)

from .settings import *  # noqa: E402, F403

# Never the developer's files or bucket. Every alias in memory.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
}

# Hashing is deliberately slow; tests only need it to be correct.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
