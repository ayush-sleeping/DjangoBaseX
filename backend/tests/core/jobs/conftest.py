import pytest
from django.db import connections

from tests.core.jobs.dbs import SEPARATE_CONNECTION


@pytest.fixture(scope="session", autouse=True)
def _close_the_monitor_connection(django_db_setup, django_db_blocker):
    """
    On PostgreSQL the recorder holds a second connection (the "monitor" alias). pytest-django
    closes only the connections it opened, so an open monitor session stops the test database
    from being dropped ("being accessed by other users") and leaves a stale test_app for the next
    run. Requesting django_db_setup makes this teardown run before the database is dropped.
    """
    yield
    if SEPARATE_CONNECTION:
        with django_db_blocker.unblock():
            for alias in connections:
                connections[alias].close()
