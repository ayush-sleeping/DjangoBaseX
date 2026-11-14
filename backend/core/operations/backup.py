"""
A verified database backup (OPERATIONS.md § 9). A backup is not a backup until it is verified.

PostgreSQL: `pg_dump -Fc` to `<name>.dump.partial`, then verify, then an atomic rename. Verified
means `pg_restore --list` succeeds AND the archive holds at least as many `TABLE DATA` entries as
the live database has tables: "readable" and "contains the data" are different claims. SQLite
(development only): the sqlite3 online-backup API into the partial file, then
`PRAGMA integrity_check` and a table-count comparison. A `.partial` file is deleted on any failure
and is never renamed, so a crash cannot leave something that looks complete.

Credentials: the password reaches pg_dump through the child's PGPASSWORD, never argv, and every
message is scrubbed before it leaves this module.

Exit codes (BackupError.code): 2 configuration, 3 dump failed, 4 verification failed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

EXIT_CONFIG, EXIT_DUMP, EXIT_VERIFY = 2, 3, 4
LABEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
URL_USERINFO = re.compile(r"(\w+://[^/\s:@]*):[^@\s/]*@")
TABLE_DATA = re.compile(r"\bTABLE DATA\b")

Runner = Callable[..., subprocess.CompletedProcess]


class BackupError(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def scrub(text: str, password: str = "") -> str:
    """Remove a URL password and the database password from text bound for a log or a terminal."""
    text = URL_USERINFO.sub(r"\1:***@", text)
    return text.replace(password, "***") if password else text


@dataclass(frozen=True)
class Backup:
    path: Path
    meta_path: Path
    size: int
    sha256: str
    tables: int


def is_postgres(db: dict) -> bool:
    return "postgresql" in db.get("ENGINE", "") or "postgis" in db.get("ENGINE", "")


def is_sqlite(db: dict) -> bool:
    return db.get("ENGINE", "").endswith("sqlite3")


def pg_args(db: dict) -> list[str]:
    args = ["-h", str(db.get("HOST") or "localhost"), "-p", str(db.get("PORT") or "5432")]
    if db.get("USER"):
        args += ["-U", str(db["USER"])]
    return args


def pg_env(db: dict) -> dict[str, str]:
    env = dict(os.environ)
    if db.get("PASSWORD"):
        env["PGPASSWORD"] = str(db["PASSWORD"])
    return env


def sqlite_tables(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        return con.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
    finally:
        con.close()


def sqlite_check(path: Path) -> str | None:
    """Why the file is not a sound SQLite database, or None."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            verdict = con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        return str(exc)
    return None if verdict == "ok" else f"integrity_check said {verdict!r}"


def _dump_sqlite(db: dict, partial: Path) -> None:
    src = sqlite3.connect(f"file:{db['NAME']}?mode=ro", uri=True)
    dst = sqlite3.connect(partial)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _run(runner: Runner, argv: list[str], db: dict, code: int, what: str):
    password = str(db.get("PASSWORD") or "")
    try:
        done = runner(argv, env=pg_env(db), capture_output=True, text=True, check=False)
    except OSError as exc:
        raise BackupError(
            f"{what}: cannot run {argv[0]}: {scrub(str(exc), password)}", code
        ) from None
    if done.returncode != 0:
        detail = scrub((done.stderr or "").strip()[-400:], password)
        raise BackupError(f"{what} failed (exit {done.returncode}): {detail}", code)
    return done


def verify_postgres(db: dict, partial: Path, tables: int, runner: Runner) -> None:
    done = _run(
        runner, ["pg_restore", "--list", str(partial)], db, EXIT_VERIFY, "pg_restore --list"
    )
    found = len(TABLE_DATA.findall(done.stdout or ""))
    if found < tables:
        raise BackupError(
            f"the archive lists {found} TABLE DATA entries but the database has {tables} tables",
            EXIT_VERIFY,
        )


def verify_sqlite(partial: Path, tables: int) -> None:
    problem = sqlite_check(partial)
    if problem:
        raise BackupError(f"the copy is not a sound database: {problem}", EXIT_VERIFY)
    found = sqlite_tables(partial)
    if found < tables:
        raise BackupError(f"the copy has {found} tables but the database has {tables}", EXIT_VERIFY)


def create_backup(
    db: dict,
    directory: Path,
    label: str,
    *,
    tables: int,
    source_env: str,
    version: str = "unknown",
    migrations: dict[str, str] | None = None,
    runner: Runner = subprocess.run,
    now: datetime | None = None,
) -> Backup:
    """Dump, verify, record, rename. Raises BackupError (never returns a bad backup)."""
    if not LABEL.match(label):
        raise BackupError(f"label {label!r}: lowercase letters, digits, . _ - only", EXIT_CONFIG)
    if is_sqlite(db):
        if str(db.get("NAME")) in ("", ":memory:") or not Path(str(db["NAME"])).is_file():
            raise BackupError("the SQLite database is not a file on disk", EXIT_CONFIG)
        suffix = ".sqlite"
    elif is_postgres(db):
        suffix = ".dump"
    else:
        raise BackupError(f"unsupported database engine {db.get('ENGINE')!r}", EXIT_CONFIG)

    old_umask = os.umask(0o077)
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
        final = directory / f"{label}-{stamp}{suffix}"
        partial = final.with_name(final.name + ".partial")
        try:
            if is_sqlite(db):
                try:
                    _dump_sqlite(db, partial)
                except (sqlite3.Error, OSError) as exc:
                    raise BackupError(f"sqlite backup failed: {exc}", EXIT_DUMP) from None
            else:
                argv = ["pg_dump", "-Fc", "--no-owner", *pg_args(db), "-f", str(partial)]
                _run(runner, [*argv, "-d", str(db["NAME"])], db, EXIT_DUMP, "pg_dump")
            if not partial.is_file() or partial.stat().st_size == 0:
                raise BackupError("the dump is empty", EXIT_VERIFY)
            if is_sqlite(db):
                verify_sqlite(partial, tables)
            else:
                verify_postgres(db, partial, tables, runner)
            digest = hashlib.sha256(partial.read_bytes()).hexdigest()
            size = partial.stat().st_size
            os.replace(partial, final)
        finally:
            partial.unlink(missing_ok=True)
        meta = final.with_name(final.name + ".meta.json")
        meta.write_text(
            json.dumps(
                {
                    "label": label,
                    "created_at": stamp,
                    "source_env": source_env,
                    "app_version": version,
                    "engine": "postgresql" if is_postgres(db) else "sqlite",
                    "tables": tables,
                    "size": size,
                    "sha256": digest,
                    "migrations": migrations or {},
                },
                indent=2,
                sort_keys=True,
            )
        )
        os.chmod(meta, 0o600)
        os.chmod(final, 0o600)
    finally:
        os.umask(old_umask)
    return Backup(final, meta, size, digest, tables)
