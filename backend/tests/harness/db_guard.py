"""
The test-database guard (OPERATIONS.md § 11, ENGINEERING_PRACTICES.md § 5).

A test run creates, flushes and destroys its database. This refuses to start one against anything
that is not unambiguously a test database. pytest-django's `test_` prefix is defeated by exactly
the configurations that turn up in practice: an empty NAME (PostgreSQL then defaults to the user's
own database), a custom TEST["NAME"], or a test name equal to the real one.

Messages name the alias, the database and the host. Never the password.
"""

import os
from pathlib import PurePath

# "" is a local socket or file. Anything else must be named here or in TEST_DB_ALLOWED_HOSTS.
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "db", "postgres")


class UnsafeTestDatabase(Exception):
    pass


def allowed_hosts() -> tuple[str, ...]:
    raw = os.environ.get("TEST_DB_ALLOWED_HOSTS", "")
    hosts = tuple(h.strip() for h in raw.split(",") if h.strip()) or DEFAULT_ALLOWED_HOSTS
    return ("", *hosts)


def check_test_databases(databases: dict, hosts: tuple[str, ...] | None = None) -> None:
    """Raise UnsafeTestDatabase for the first alias a test run must not touch."""
    hosts = allowed_hosts() if hosts is None else hosts
    for alias, db in databases.items():
        name = str(db.get("NAME") or "")
        test_name = str((db.get("TEST") or {}).get("NAME") or "")

        if "sqlite" in db.get("ENGINE", ""):
            # No TEST.NAME means Django tests in memory: nothing on disk can be touched.
            if not test_name or test_name == ":memory:" or "mode=memory" in test_name:
                continue
            effective = PurePath(test_name).name
            if not effective.startswith("test_") or test_name == name:
                raise UnsafeTestDatabase(
                    f"refusing to test against {alias!r}: SQLite test file {effective!r} "
                    "is not a test_ database"
                )
            continue

        effective = test_name or (f"test_{name}" if name else "")
        if not effective:
            raise UnsafeTestDatabase(
                f"refusing to test against {alias!r}: the database name is empty, and the "
                "driver would fall back to the connecting user's own database"
            )
        if not effective.startswith("test_") or effective == name:
            raise UnsafeTestDatabase(
                f"refusing to test against {alias!r}: effective test database {effective!r} "
                "is not a separate test_ database"
            )
        host = str(db.get("HOST") or "")
        if host not in hosts:
            raise UnsafeTestDatabase(
                f"refusing to test against {alias!r}: host {host!r} is not in TEST_DB_ALLOWED_HOSTS"
            )
