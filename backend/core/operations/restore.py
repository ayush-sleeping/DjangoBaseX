"""
Restore, and the hold that makes restoring another environment's data safe (OPERATIONS.md § 10).

The incident this answers: a production dump loaded into staging carried working credentials, and
the staging scheduler started acting on production's integrations within a minute. So a restore
whose source environment differs from the target's comes up with every schedule, webhook endpoint
and outbound notification switch OFF. The hold only flips switches: it never deletes a row. What it
turned off is written to a `config_snapshot` file beside the backups, and `reenable()` turns exactly
those back on, deliberately, by an operator.

Order matters (§ 10): the data is restored, THEN hold() runs, THEN beat starts. Beat must stay
stopped until the hold has run; the driver and the runbook say so.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from django.db import transaction

from .backup import (
    EXIT_CONFIG,
    BackupError,
    Runner,
    _run,
    is_postgres,
    is_sqlite,
    pg_args,
    scrub,
    sqlite_check,
)

SNAPSHOT_VERSION = 1
PRODUCTION = "production"


class RestoreError(Exception):
    pass


def read_meta(dump: Path) -> dict | None:
    meta = dump.with_name(dump.name + ".meta.json")
    if not meta.is_file():
        return None
    try:
        return json.loads(meta.read_text())
    except ValueError:
        return None


def read_dump(db: dict, dump: Path, runner: Runner = subprocess.run) -> None:
    """Step 1: read the archive before anything is touched. Raises RestoreError if unreadable."""
    if not dump.is_file() or dump.stat().st_size == 0:
        raise RestoreError(f"{dump} is missing or empty; the target database was not touched")
    try:
        if is_sqlite(db):
            problem = sqlite_check(dump)
            if problem:
                raise RestoreError(f"{dump} is unreadable ({problem}); nothing was touched")
        else:
            _run(runner, ["pg_restore", "--list", str(dump)], db, EXIT_CONFIG, "pg_restore --list")
    except BackupError as exc:
        raise RestoreError(f"{exc}; the target database was not touched") from None


def restore_data(db: dict, dump: Path, runner: Runner = subprocess.run) -> None:
    """Drop and recreate, then load. Never `pg_restore --clean`: it leaves a half-restored
    database when it cannot drop an object other objects reference."""
    read_dump(db, dump, runner)
    try:
        if is_sqlite(db):
            src = sqlite3.connect(f"file:{dump}?mode=ro", uri=True)
            dst = sqlite3.connect(str(db["NAME"]))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            return
        if not is_postgres(db):
            raise RestoreError(f"unsupported database engine {db.get('ENGINE')!r}")
        name, host = str(db["NAME"]), pg_args(db)
        _run(runner, ["dropdb", "--if-exists", "--force", *host, name], db, 3, "dropdb")
        owner = ["-O", str(db["USER"])] if db.get("USER") else []
        _run(runner, ["createdb", *owner, *host, name], db, 3, "createdb")
        restore = ["pg_restore", "--exit-on-error", "--no-owner", *host, "-d", name, str(dump)]
        _run(runner, restore, db, 3, "pg_restore")
    except BackupError as exc:
        raise RestoreError(scrub(str(exc), str(db.get("PASSWORD") or ""))) from None


def is_other_environment(source_env: str, target_env: str) -> bool:
    return source_env.strip().lower() != target_env.strip().lower()


@dataclass
class Snapshot:
    source_env: str
    target_env: str
    taken_at: str
    held: dict[str, list] = field(default_factory=dict)  # kind -> primary keys switched off

    def counts(self) -> dict[str, int]:
        return {kind: len(ids) for kind, ids in self.held.items()}


def hold(source_env: str, target_env: str, directory: Path) -> tuple[Snapshot, Path]:
    """Switch off every schedule, webhook endpoint and outbound notification switch that is on,
    recording exactly what was on. One transaction: a half-held restore is not a state."""
    from django_celery_beat.models import PeriodicTask, PeriodicTasks

    from core.models import NotificationRoute, NotificationSetting, WebhookEndpoint

    targets = (
        ("schedules", PeriodicTask, "enabled"),
        ("webhook_endpoints", WebhookEndpoint, "is_active"),
        ("notification_routes", NotificationRoute, "is_active"),
        ("notification_settings", NotificationSetting, "enabled"),
    )
    snap = Snapshot(source_env, target_env, datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    with transaction.atomic():
        for kind, model, flag in targets:
            rows = model.objects.filter(**{flag: True})
            snap.held[kind] = sorted(rows.values_list("pk", flat=True))
            rows.update(**{flag: False})
        PeriodicTasks.update_changed()  # the DatabaseScheduler only notices through this marker
    old = os.umask(0o077)
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / f"config_snapshot-{snap.taken_at}.json"
        path.write_text(
            json.dumps({"version": SNAPSHOT_VERSION, **snap.__dict__}, indent=2, sort_keys=True)
        )
        os.chmod(path, 0o600)
    finally:
        os.umask(old)
    return snap, path


def reenable(path: Path) -> dict[str, int]:
    """Turn back on exactly what a snapshot turned off. Rows deleted since are skipped."""
    from django_celery_beat.models import PeriodicTask, PeriodicTasks

    from core.models import NotificationRoute, NotificationSetting, WebhookEndpoint

    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise RestoreError(f"cannot read snapshot {path}: {exc}") from None
    if data.get("version") != SNAPSHOT_VERSION or not isinstance(data.get("held"), dict):
        raise RestoreError(f"{path} is not a version {SNAPSHOT_VERSION} config snapshot")
    targets = {
        "schedules": (PeriodicTask, "enabled"),
        "webhook_endpoints": (WebhookEndpoint, "is_active"),
        "notification_routes": (NotificationRoute, "is_active"),
        "notification_settings": (NotificationSetting, "enabled"),
    }
    done: dict[str, int] = {}
    with transaction.atomic():
        for kind, (model, flag) in targets.items():
            done[kind] = model.objects.filter(pk__in=data["held"].get(kind, [])).update(
                **{flag: True}
            )
        PeriodicTasks.update_changed()
    return done
