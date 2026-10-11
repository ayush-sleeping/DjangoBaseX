"""The guard refuses every bypass OPERATIONS.md § 11 names, and never prints the password."""

import pytest

from tests.harness.db_guard import UnsafeTestDatabase, check_test_databases

PG = "django.db.backends.postgresql"
SQLITE = "django.db.backends.sqlite3"
HOSTS = ("", "localhost", "db")
SECRET = "hunter2-do-not-print"


def pg(**overrides):
    db = {"ENGINE": PG, "NAME": "app", "HOST": "localhost", "PASSWORD": SECRET, "TEST": {}}
    db.update(overrides)
    return {"default": db}


@pytest.mark.parametrize(
    ("databases", "reason"),
    [
        (pg(NAME=""), "the database name is empty"),
        (pg(TEST={"NAME": "app"}), "is not a separate test_ database"),
        (pg(TEST={"NAME": "staging_copy"}), "is not a separate test_ database"),
        (pg(NAME="test_app", TEST={"NAME": "test_app"}), "is not a separate test_ database"),
        (pg(HOST="db.staging.internal"), "is not in TEST_DB_ALLOWED_HOSTS"),
        (
            {"default": {"ENGINE": SQLITE, "NAME": "db.sqlite3", "TEST": {"NAME": "db.sqlite3"}}},
            "is not a test_ database",
        ),
    ],
    ids=[
        "empty-name",
        "test-name-is-real-name",
        "test-name-without-prefix",
        "prefixed-real-name",
        "host-not-allowed",
        "sqlite-test-file-is-real-file",
    ],
)
def test_refuses_unsafe_configuration(databases, reason):
    with pytest.raises(UnsafeTestDatabase, match=reason) as excinfo:
        check_test_databases(databases, hosts=HOSTS)
    assert SECRET not in str(excinfo.value)


@pytest.mark.parametrize(
    "databases",
    [
        pg(),
        pg(TEST={"NAME": "test_app_ci"}),
        pg(HOST="db"),
        {"default": {"ENGINE": SQLITE, "NAME": "db.sqlite3", "TEST": {}}},
        {"default": {"ENGINE": SQLITE, "NAME": ":memory:", "TEST": {"NAME": ":memory:"}}},
        {"default": {"ENGINE": SQLITE, "NAME": "db.sqlite3", "TEST": {"NAME": "test_db.sqlite3"}}},
    ],
    ids=[
        "derived-test-prefix",
        "explicit-test-name",
        "compose-host",
        "sqlite-in-memory",
        "sqlite-memory-name",
        "sqlite-test-file",
    ],
)
def test_allows_safe_configuration(databases):
    check_test_databases(databases, hosts=HOSTS)


def test_this_suite_runs_against_a_safe_database(settings):
    check_test_databases(settings.DATABASES)
