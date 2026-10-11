"""
Meta-tests: state written in one test is gone in the next. These two run in file order on purpose;
the second fails if rows or cache keys leak across tests.
"""

import pytest
from django.core.cache import cache

from tests.factories import UserFactory
from users.models import User

PROBE_EMAIL = "isolation-probe@example.com"
PROBE_KEY = "harness:isolation-probe"


@pytest.mark.django_db
def test_write_state():
    UserFactory(email=PROBE_EMAIL)
    cache.set(PROBE_KEY, "leaked", 300)
    assert User.objects.filter(email=PROBE_EMAIL).exists()


@pytest.mark.django_db
def test_state_from_previous_test_is_gone():
    assert not User.objects.filter(email=PROBE_EMAIL).exists()
    assert cache.get(PROBE_KEY) is None
