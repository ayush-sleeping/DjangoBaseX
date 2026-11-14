"""manage.py backup / restore and the config_snapshot hold (9.5; OPERATIONS §§ 9, 10)."""

import json
import sqlite3
import subprocess
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from core.operations import backup as bk
from core.operations import restore as rs

PG = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "app",
    "USER": "app",
    "PASSWORD": "s3cr3t-pw",
    "HOST": "db",
    "PORT": "5432",
}


def sqlite_db(tmp_path: Path, tables: int = 2) -> dict:
    path = tmp_path / "live.sqlite3"
    con = sqlite3.connect(path)
    for i in range(tables):
        con.execute(f"CREATE TABLE t{i} (id INTEGER)")
        con.execute(f"INSERT INTO t{i} VALUES (1)")
    con.commit()
    con.close()
    return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(path)}


def make(db, tmp_path, **kw):
    args = {"tables": 2, "source_env": "staging", "version": "1.0.0"}
    return bk.create_backup(db, tmp_path / "backups", kw.pop("label", "manual"), **{**args, **kw})


# --- backup ------------------------------------------------------------------------------------


def test_sqlite_backup_is_verified_recorded_and_private(tmp_path):
    result = make(sqlite_db(tmp_path), tmp_path)
    assert result.size > 0 and result.path.suffix == ".sqlite"
    assert (result.path.stat().st_mode & 0o777) == 0o600
    assert (result.path.parent.stat().st_mode & 0o777) == 0o700
    meta = json.loads(result.meta_path.read_text())
    assert meta["source_env"] == "staging" and meta["sha256"] == result.sha256
    assert not list(result.path.parent.glob("*.partial"))


def test_a_backup_with_fewer_tables_than_the_database_is_refused_and_leaves_nothing(tmp_path):
    with pytest.raises(bk.BackupError) as err:
        make(sqlite_db(tmp_path, tables=2), tmp_path, tables=5)
    assert err.value.code == bk.EXIT_VERIFY
    assert list((tmp_path / "backups").iterdir()) == []  # no .partial, no final


def test_an_in_memory_database_is_a_configuration_error(tmp_path):
    with pytest.raises(bk.BackupError) as err:
        make({"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}, tmp_path)
    assert err.value.code == bk.EXIT_CONFIG


def test_a_bad_label_is_refused(tmp_path):
    with pytest.raises(bk.BackupError):
        make(sqlite_db(tmp_path), tmp_path, label="../escape")


class PgRunner:
    """Stands in for pg_dump / pg_restore: records argv and env, writes the partial file."""

    def __init__(self, data_entries=2, dump_status=0, list_status=0):
        self.calls, self.envs = [], []
        self.data_entries, self.dump_status, self.list_status = (
            data_entries,
            dump_status,
            list_status,
        )

    def __call__(self, argv, env=None, **kw):
        self.calls.append(argv)
        self.envs.append(env)
        if argv[0] == "pg_dump":
            Path(argv[argv.index("-f") + 1]).write_bytes(b"PGDMP" if self.dump_status == 0 else b"")
            return subprocess.CompletedProcess(
                argv, self.dump_status, "", "boom postgres://u:s3cr3t-pw@h/d"
            )
        if argv[0] == "pg_restore" and "--list" in argv:
            out = "; TABLE DATA\n" * self.data_entries
            return subprocess.CompletedProcess(argv, self.list_status, out, "")
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_postgres_backup_passes_the_password_by_env_never_argv(tmp_path):
    runner = PgRunner()
    make(PG, tmp_path, runner=runner)
    assert all("s3cr3t-pw" not in " ".join(c) for c in runner.calls)
    assert runner.envs[0]["PGPASSWORD"] == "s3cr3t-pw"


def test_postgres_archive_with_too_few_table_data_entries_fails_verification(tmp_path):
    with pytest.raises(bk.BackupError) as err:
        make(PG, tmp_path, runner=PgRunner(data_entries=1), tables=3)
    assert err.value.code == bk.EXIT_VERIFY
    assert list((tmp_path / "backups").iterdir()) == []


def test_a_failed_dump_is_exit_3_and_the_error_is_scrubbed(tmp_path):
    with pytest.raises(bk.BackupError) as err:
        make(PG, tmp_path, runner=PgRunner(dump_status=1))
    assert err.value.code == bk.EXIT_DUMP
    assert "s3cr3t-pw" not in str(err.value)


@pytest.mark.django_db
def test_the_command_exits_with_the_backup_code(tmp_path, monkeypatch):
    # An engine the backup cannot dump is a configuration failure, surfaced as returncode 2.
    # Forced so it holds on every test database: PostgreSQL really is dumpable, in-memory SQLite
    # is not.
    monkeypatch.setitem(connection.settings_dict, "ENGINE", "django.db.backends.unsupported")
    with pytest.raises(CommandError) as err:
        call_command("backup", "--dir", str(tmp_path / "b"))
    assert err.value.returncode == bk.EXIT_CONFIG


# --- restore -----------------------------------------------------------------------------------


def test_an_unreadable_dump_stops_before_touching_the_target(tmp_path):
    live = sqlite_db(tmp_path)
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"not a database at all, certainly not")
    before = Path(live["NAME"]).read_bytes()
    with pytest.raises(rs.RestoreError):
        rs.restore_data(live, junk)
    assert Path(live["NAME"]).read_bytes() == before


def test_sqlite_restore_round_trips(tmp_path):
    live = sqlite_db(tmp_path)
    dump = make(live, tmp_path).path
    sqlite3.connect(live["NAME"]).execute("DROP TABLE t0").connection.commit()
    rs.restore_data(live, dump)
    assert bk.sqlite_tables(Path(live["NAME"])) == 2


def test_postgres_restore_reads_first_drops_and_recreates_and_never_cleans(tmp_path):
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    runner = PgRunner()
    rs.restore_data(PG, dump, runner)
    names = [c[0] for c in runner.calls]
    assert names == ["pg_restore", "dropdb", "createdb", "pg_restore"]
    assert "--list" in runner.calls[0]
    assert all("--clean" not in c for c in runner.calls)
    assert "--exit-on-error" in runner.calls[3]


def test_postgres_restore_with_an_unreadable_archive_never_drops(tmp_path):
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    runner = PgRunner(list_status=1)
    with pytest.raises(rs.RestoreError):
        rs.restore_data(PG, dump, runner)
    assert [c[0] for c in runner.calls] == ["pg_restore"]


# --- the hold ----------------------------------------------------------------------------------


@pytest.fixture
def integrations(db):
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    from core.models import NotificationRoute, NotificationSetting, WebhookEndpoint

    every = IntervalSchedule.objects.create(every=5, period=IntervalSchedule.MINUTES)
    on = PeriodicTask.objects.create(name="restored-on", task="x.y", interval=every, enabled=True)
    off = PeriodicTask.objects.create(
        name="restored-off", task="x.y", interval=every, enabled=False
    )
    hook = WebhookEndpoint.objects.create(
        name="h", url="https://hooks.example.test/x", secret_ciphertext="c", is_active=True
    )
    route = NotificationRoute.objects.create(
        purpose_code="p", channel="email", target={"to": ["a@example.test"]}, target_hash="h"
    )
    setting = NotificationSetting.objects.create(purpose_code="p", channel="email", enabled=True)
    return {"on": on, "off": off, "hook": hook, "route": route, "setting": setting}


def state(rows):
    for row in rows.values():
        row.refresh_from_db()
    return {
        "schedule": rows["on"].enabled,
        "hook": rows["hook"].is_active,
        "route": rows["route"].is_active,
        "setting": rows["setting"].enabled,
    }


def test_a_restored_dump_from_another_environment_comes_up_with_its_schedules_and_integrations_disabled(  # noqa: E501
    tmp_path, integrations
):
    out = StringIO()
    call_command(
        "restore", "--post-only", "--source-env", "production", "--allow-unsanitised",
        "--dir", str(tmp_path), stdout=out,
    )  # fmt: skip
    assert state(integrations) == {
        "schedule": False, "hook": False, "route": False, "setting": False,
    }  # fmt: skip
    assert "turned off, not deleted" in out.getvalue()
    # Nothing was deleted, and what was already off is not in the snapshot.
    snap = json.loads(next(tmp_path.glob("config_snapshot-*.json")).read_text())
    assert integrations["on"].pk in snap["held"]["schedules"]  # beat's own rows are held too
    assert integrations["off"].pk not in snap["held"]["schedules"]


def test_reenable_turns_back_on_exactly_what_the_hold_turned_off(tmp_path, integrations):
    call_command("restore", "--post-only", "--source-env", "staging", "--dir", str(tmp_path))
    snapshot = next(tmp_path.glob("config_snapshot-*.json"))
    call_command("restore", "--reenable", str(snapshot))
    assert all(state(integrations).values())
    integrations["off"].refresh_from_db()
    assert integrations["off"].enabled is False  # it was off before; it stays off


def test_the_same_environment_is_left_alone(tmp_path, integrations):
    call_command("restore", "--post-only", "--source-env", "test", "--dir", str(tmp_path))
    assert all(state(integrations).values())
    assert not list(tmp_path.glob("config_snapshot-*"))


def test_an_unknown_source_environment_is_refused_not_assumed(tmp_path, integrations):
    with pytest.raises(CommandError, match="unknown"):
        call_command("restore", "--post-only", "--dir", str(tmp_path))
    assert all(state(integrations).values())


def test_a_production_dump_into_non_production_needs_an_explicit_override(tmp_path, integrations):
    with pytest.raises(CommandError, match="allow-unsanitised"):
        call_command("restore", "--post-only", "--source-env", "production", "--dir", str(tmp_path))
    assert all(state(integrations).values())


def test_restoring_a_dump_without_yes_is_refused(tmp_path):
    with pytest.raises(CommandError, match="--yes"):
        call_command("restore", str(tmp_path / "x.dump"))


def test_the_source_environment_is_read_from_the_dump_meta(tmp_path):
    live = sqlite_db(tmp_path)
    dump = make(live, tmp_path, source_env="production").path
    assert rs.read_meta(dump)["source_env"] == "production"
    assert rs.read_meta(tmp_path / "nope.dump") is None


def test_hold_is_idempotent(tmp_path, integrations):
    first, _ = rs.hold("staging", "test", tmp_path)
    second, _ = rs.hold("staging", "test", tmp_path / "again")
    assert first.counts()["schedules"] >= 1 and second.counts()["schedules"] == 0
