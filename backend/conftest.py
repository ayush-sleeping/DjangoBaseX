"""
The root test harness: applies to every test in the backend (ENGINEERING_PRACTICES.md § 5).

Settings are `config.settings_test` (pyproject.toml): pinned env, in-memory cache, email and
storage, and a fast hasher. This file adds what settings cannot.
"""

import pytest

from tests.harness.db_guard import UnsafeTestDatabase, check_test_databases


def pytest_configure(config):
    # Runs before any test database is created. A refusal stops the whole session.
    from django.conf import settings

    try:
        check_test_databases(settings.DATABASES)
    except UnsafeTestDatabase as exc:
        raise pytest.UsageError(str(exc)) from None


@pytest.fixture(autouse=True)
def _hermetic_cache():
    """A cache that starts empty for every test, so no test sees another's throttle or lockout."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def setting_override(db):
    """
    setting_override(key, value): a platform override through the real writer, so a test exercises
    the same coercion, cache and audit path as production. Rolled back with the test's transaction.
    """
    from core.settings_service import set_value

    def apply(key, value, **where):
        return set_value(key, value, reason="test", **where)

    return apply


@pytest.fixture
def audit_rows(db):
    """The rows the audit trail wrote since this fixture was requested, oldest first: `rows()` or
    `rows("core.setting.changed")`. Row assertions replace the old caplog ones (DB-41)."""
    from core.models import ActivityLog

    start = ActivityLog.objects.order_by("-id").values_list("id", flat=True).first() or 0

    def rows(action: str | None = None):
        found = ActivityLog.objects.filter(id__gt=start).order_by("id")
        return list(found.filter(action=action) if action else found)

    return rows
