"""
No session-level advisory locks (JOBS_AND_INTEGRATIONS.md § 9). Behind a transaction-pooling
PgBouncer the "session" is shared by strangers, so a session lock is held for, and released by,
whoever gets the connection next. Only the transaction-scoped (_xact_) variants are safe:
core.locks.advisory_xact_lock. Text, not AST: the call lives inside SQL strings.
"""

import re

from tests.architecture.sources import iter_python_sources, rel

SESSION_LOCK = re.compile(r"pg_(?:try_)?advisory_(?:lock|unlock)(?:_shared|_all)?\s*\(", re.I)


def offenders(text: str) -> list[str]:
    return SESSION_LOCK.findall(text)


def test_no_session_advisory_locks():
    scanned, found = 0, []
    for path in iter_python_sources():
        scanned += 1
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if offenders(line):
                found.append(f"{rel(path)}:{line_no}: {line.strip()}")
    assert scanned, "scanned no files: the scan is looking in the wrong place"
    assert found == [], "use core.locks.advisory_xact_lock():\n" + "\n".join(found)


def test_the_scan_sees_each_form_and_spares_the_xact_one():
    bad = (
        "SELECT pg_advisory_lock(1)",
        "select pg_try_advisory_lock(hashtext(%s))",
        "SELECT pg_advisory_unlock(1)",
        "SELECT pg_advisory_lock_shared(1)",
        "SELECT pg_advisory_unlock_all()",
    )
    assert all(offenders(s) for s in bad)
    assert not offenders("SELECT pg_try_advisory_xact_lock(hashtext(%s))")
    assert not offenders("SELECT pg_advisory_xact_lock_shared(1)")
