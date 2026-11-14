"""
The retention engine (BUILD_ORDER 7.5; DATA_LIFECYCLE.md § 6). Real rows through the real engine:
JobRun and ActivityLog are written by their own code paths. JobRun is backdated with a queryset
update; ActivityLog is append-only (a trigger refuses UPDATE), so its row is born old instead.

Custom shapes (a small cap, a small batch) replace a REAL policy's declaration in the catalog for
one test, so the real setting keys, floors and gates are still the ones exercised.
"""

import dataclasses
import io
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.core.management import CommandError, call_command
from django.db.models.signals import post_delete, pre_delete
from django.utils import timezone

from core import audit
from core.models import ActivityLog, JobRun, Setting
from core.registry import Registry, RegistryError, RetentionPolicy, registry
from core.retention import engine
from core.retention import register as register_policy
from core.settings_registry import SettingInvalid, stored
from core.settings_service import definition, set_value
from users.models import LoginAttempt

pytestmark = pytest.mark.django_db

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
COMPLETED = "core.job_run_completed"
FAILED = "core.job_run_failed"
AUDIT = "core.activity_log"


def ago(delta):
    return timezone.now() - delta


def job_run(status="succeeded", age=timedelta(0), job="core.probe"):
    row = JobRun.objects.create(
        task_id=uuid.uuid4().hex, job_name=job, status=status, finished_at=ago(age)
    )
    return row


def old_audit_row(age, action="core.setting.changed"):
    # The append-only trigger refuses UPDATE on PostgreSQL, so the row is born old: `created_at`
    # is auto_now_add, which reads the clock at insert time through the real write path.
    born = ago(age)
    with mock.patch.object(timezone, "now", return_value=born):
        row = audit.record(action)
    assert row is not None
    assert row.created_at == born
    return row


def alive(*rows) -> list[bool]:
    return [type(r).objects.filter(pk=r.pk).exists() for r in rows]


def reshape(monkeypatch, key, **changes):
    """Swap one registered policy for a copy with other caps/batches (same settings, same floor)."""
    policy = dataclasses.replace(registry.retention.get(key), **changes)
    monkeypatch.setitem(registry.retention._policies, key, policy)
    return policy


def only(key, **kwargs):
    (result,) = engine.run(only=[key], **kwargs)
    return result


# --- Registration ------------------------------------------------------------------------------


def declared(**changes):
    base = dict(
        key="core.probe",
        model="core.JobRun",
        timestamp_field="finished_at",
        description="A probe.",
        data_class="operational_log",
        max_age_days=14,
        min_age_days=1,
    )
    return RetentionPolicy(**{**base, **changes})


@pytest.mark.parametrize("data_class", ["evidence", "security_log"])
def test_a_row_cap_is_refused_on_evidence_and_security_logs(data_class):
    fresh = Registry()
    with pytest.raises(RegistryError, match="max_rows is refused"):
        register_policy(fresh, declared(data_class=data_class, max_rows=10, requires_opt_in=True))
    assert fresh.retention.policies() == ()  # all or nothing: no setting left behind
    assert fresh.settings.defs() == ()


def test_evidence_must_be_opt_in():
    with pytest.raises(RegistryError, match="evidence is opt-in"):
        register_policy(Registry(), declared(data_class="evidence"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"strategy": "anonymise"}, "strategy"),
        ({"min_age_days": 0}, "floor"),
        ({"max_age_days": 3, "min_age_days": 7}, "at least min_age_days"),
        ({"model": "JobRun"}, "app_label.ModelName"),
        ({"key": "probe"}, "not <owner>.<name>"),
        ({"data_class": "gossip"}, "data_class"),
    ],
)
def test_a_malformed_policy_is_refused_at_registration(changes, message):
    with pytest.raises(RegistryError, match=message):
        register_policy(Registry(), declared(**changes))


def test_registering_declares_the_window_and_the_opt_in_switch_as_settings():
    fresh = Registry()
    register_policy(fresh, declared(data_class="evidence", requires_opt_in=True))
    assert {d.key for d in fresh.settings.defs()} == {
        "retention.core_probe.days",
        "retention.core_probe.enabled",
    }


def test_the_audit_log_policy_is_opt_in_evidence_without_a_cap():
    policy = registry.retention.get(AUDIT)
    assert (policy.requires_opt_in, policy.data_class, policy.max_rows) == (True, "evidence", None)
    assert registry.retention.get(COMPLETED).max_rows and registry.retention.get(FAILED).max_rows


# --- Floors (§ 6.3) ----------------------------------------------------------------------------


@pytest.mark.parametrize("policy", registry.retention.policies(), ids=lambda p: p.key)
@pytest.mark.parametrize("bad", [0, -1])
def test_zero_and_negative_are_refused_at_save(policy, bad):
    with pytest.raises(SettingInvalid):
        set_value(policy.days_setting, bad)


@pytest.mark.parametrize("policy", registry.retention.policies(), ids=lambda p: p.key)
def test_a_value_under_the_floor_is_refused_and_the_floor_itself_is_accepted(policy):
    if policy.min_age_days > 1:
        with pytest.raises(SettingInvalid):
            set_value(policy.days_setting, policy.min_age_days - 1)
    set_value(policy.days_setting, policy.min_age_days)
    assert definition(policy.days_setting).default == policy.max_age_days


def test_a_stored_zero_is_clamped_to_the_floor_before_it_reaches_the_engine():
    # A row written around the validator (a raw DB edit): the settings read clamps it.
    Setting.objects.create(
        key="retention.core_job_run_failed.days", scope_type="platform", value=stored(0)
    )
    old = job_run("failed", 5 * DAY)
    inside = job_run("failed", 6 * DAY)  # younger than the 7-day floor: must survive
    outside = job_run("failed", 8 * DAY)
    result = only(FAILED)
    assert (result.deleted, alive(old, inside, outside)) == (1, [True, True, False])


def test_a_raw_zero_reaching_the_engine_is_clamped_to_the_floor_with_a_warning(monkeypatch, caplog):
    monkeypatch.setattr(engine, "get_setting", lambda key, user=None: 0)
    now = timezone.now()
    cutoff = engine.cutoff_for(registry.retention.get(COMPLETED), now)
    assert cutoff == now - DAY  # the floor of 1 day, never "now"
    assert "core.retention.window_clamped" in caplog.text
    keep, drop = job_run("succeeded", 12 * HOUR), job_run("succeeded", 2 * DAY)
    assert (only(COMPLETED).deleted, alive(keep, drop)) == (1, [True, False])


def test_an_empty_window_keeps_forever_and_the_policy_is_skipped():
    set_value("retention.core_job_run_completed.days", None)
    row = job_run("succeeded", 900 * DAY)
    assert only(COMPLETED).state == engine.DISABLED
    assert only(COMPLETED, dry_run=True).state == engine.DISABLED
    assert alive(row) == [True]


# --- One cutoff, dry run and the real run ------------------------------------------------------


def test_dry_run_deletes_nothing_and_reports_what_the_real_run_then_deletes():
    rows = [job_run("succeeded", 20 * DAY) for _ in range(3)] + [job_run("succeeded", DAY)]
    now = timezone.now()
    dry = only(COMPLETED, dry_run=True, now=now)
    assert (dry.state, dry.eligible, dry.deleted) == (engine.DRY_RUN, 3, 0)
    assert JobRun.objects.count() == 4 and all(alive(*rows))
    real = only(COMPLETED, now=now)
    assert (real.state, real.deleted) == (engine.RAN, dry.eligible)
    assert alive(*rows) == [False, False, False, True]


def test_dry_run_and_status_and_the_run_all_use_the_one_cutoff_helper(monkeypatch):
    calls = []
    real = engine.cutoff_for
    monkeypatch.setattr(engine, "cutoff_for", lambda p, now: calls.append(p.key) or real(p, now))
    job_run("succeeded", 20 * DAY)
    only(COMPLETED, dry_run=True)
    engine.status(only=[COMPLETED])
    only(COMPLETED)
    assert calls == [COMPLETED] * 3


def test_status_reports_rows_oldest_cutoff_and_eligible_without_deleting():
    oldest, _ = job_run("succeeded", 30 * DAY), job_run("succeeded", DAY)
    now = timezone.now()
    (item,) = engine.status(only=[COMPLETED], now=now)
    assert (item.state, item.rows, item.eligible, item.max_rows) == ("active", 2, 1, 200_000)
    assert item.oldest == oldest.finished_at and item.cutoff == now - 14 * DAY
    assert JobRun.objects.count() == 2


# --- Age cut and population --------------------------------------------------------------------


def test_the_age_cut_has_its_boundary_at_the_window():
    inside = job_run("succeeded", 14 * DAY - HOUR)
    outside = job_run("succeeded", 14 * DAY + HOUR)
    only(COMPLETED)
    assert alive(inside, outside) == [True, False]


def test_completed_and_failed_runs_age_out_on_their_own_windows_and_live_runs_never():
    done_old, done_new = job_run("succeeded", 20 * DAY), job_run("skipped", 3 * DAY)
    failed_mid, failed_old = job_run("failed", 30 * DAY), job_run("dead", 100 * DAY)
    live = [job_run(s, 400 * DAY) for s in ("queued", "started", "retrying")]
    engine.run(only=[COMPLETED, FAILED])
    assert alive(done_old, done_new, failed_mid, failed_old, *live) == [
        False,
        True,
        True,
        False,
        True,
        True,
        True,
    ]


# --- The cap -----------------------------------------------------------------------------------


def test_the_cap_keeps_exactly_max_rows_newest_with_a_pk_tiebreak_on_equal_timestamps(monkeypatch):
    reshape(monkeypatch, COMPLETED, max_rows=3, batch_size=2)
    same = ago(DAY)
    rows = [job_run("succeeded") for _ in range(5)]
    JobRun.objects.filter(pk__in=[r.pk for r in rows]).update(finished_at=same)
    newest = job_run("succeeded")  # strictly newer than the five tied rows
    dry = only(COMPLETED, dry_run=True)
    result = only(COMPLETED)
    assert (dry.eligible, result.deleted, result.truncated) == (3, 3, False)
    # Keep window = the newest row, then the two highest pks of the tied five.
    assert alive(*rows, newest) == [False, False, False, True, True, True]


def test_the_cap_counts_only_what_the_age_cut_leaves(monkeypatch):
    reshape(monkeypatch, COMPLETED, max_rows=2)
    aged = [job_run("succeeded", 30 * DAY) for _ in range(4)]
    young = [job_run("succeeded", DAY * i / 10) for i in range(1, 4)]  # newest first by age
    result = only(COMPLETED)
    # 4 by age, then 1 over the cap of 2 among the 3 survivors: the oldest survivor.
    assert result.deleted == 5
    assert alive(*aged) == [False] * 4
    assert alive(*young) == [True, True, False]  # the oldest survivor went, the two newest stay


def test_the_cap_never_touches_other_statuses(monkeypatch):
    reshape(monkeypatch, COMPLETED, max_rows=1)
    keep = [job_run("failed"), job_run("queued"), job_run("started")]
    [job_run("succeeded") for _ in range(3)]
    only(COMPLETED)
    assert all(alive(*keep)) and JobRun.objects.filter(status="succeeded").count() == 1


# --- Batching ----------------------------------------------------------------------------------


def test_each_batch_commits_on_its_own(monkeypatch):
    reshape(monkeypatch, COMPLETED, batch_size=2)
    for _ in range(5):
        job_run("succeeded", 20 * DAY)
    commits = []
    real = engine._delete_batch
    monkeypatch.setattr(
        engine, "_delete_batch", lambda m, pks: commits.append(len(pks)) or real(m, pks)
    )
    result = only(COMPLETED)
    assert (result.deleted, commits, result.truncated) == (5, [2, 2, 1], False)


def test_max_batches_stops_the_run_and_reports_truncated_and_a_second_run_finishes(monkeypatch):
    reshape(monkeypatch, COMPLETED, batch_size=2, max_batches=2)
    for _ in range(5):
        job_run("succeeded", 20 * DAY)
    first = only(COMPLETED)
    assert (first.deleted, first.truncated, JobRun.objects.count()) == (4, True, 1)
    assert engine.status(only=[COMPLETED])[0].eligible == 1
    second = only(COMPLETED)
    assert (second.deleted, second.truncated, JobRun.objects.count()) == (1, False, 0)


def test_a_failure_in_a_later_batch_keeps_the_progress_of_the_earlier_ones(monkeypatch):
    reshape(monkeypatch, COMPLETED, batch_size=2)
    for _ in range(5):
        job_run("succeeded", 20 * DAY)
    real, calls = engine._delete_batch, []

    def flaky(model, pks):
        calls.append(pks)
        if len(calls) == 2:
            raise RuntimeError("the connection dropped")
        return real(model, pks)

    monkeypatch.setattr(engine, "_delete_batch", flaky)
    with pytest.raises(RuntimeError):
        only(COMPLETED)
    assert JobRun.objects.count() == 3  # the first batch is already committed


def test_the_fast_path_no_retention_managed_model_has_delete_receivers():
    # A receiver makes QuerySet.delete() load every row to fire signals: a memory spike per batch.
    for policy in registry.retention.policies():
        from django.apps import apps

        model = apps.get_model(policy.model)
        assert not pre_delete.has_listeners(model), policy.key
        assert not post_delete.has_listeners(model), policy.key


# --- Opt-in: the audit log ---------------------------------------------------------------------


def test_the_audit_log_is_untouched_by_the_scheduled_run_and_the_cli_without_the_flag():
    old = old_audit_row(2 * 365 * DAY)
    engine.run(scheduled=True)
    assert alive(old) == [True]
    call_command("retention", stdout=io.StringIO())
    call_command("retention", "--policy", AUDIT, stdout=io.StringIO())  # naming it is not enough
    assert alive(old) == [True]
    assert only(AUDIT, scheduled=True).state == engine.OPT_IN


def test_the_cli_prunes_the_audit_log_with_include_opt_in_and_records_it_afterwards():
    old = old_audit_row(2 * 365 * DAY)
    recent = old_audit_row(DAY)
    out = io.StringIO()
    call_command("retention", "--policy", AUDIT, "--include-opt-in", stdout=out)
    assert "core.activity_log: deleted 1" in out.getvalue()
    assert alive(old, recent) == [False, True]
    (summary,) = ActivityLog.objects.filter(action="core.retention.purged")
    assert summary.meta["policy"] == AUDIT and summary.meta["deleted"] == 1


def test_the_scheduled_run_prunes_the_audit_log_once_its_setting_is_on():
    old = old_audit_row(2 * 365 * DAY)
    set_value("retention.core_activity_log.enabled", True)
    result = only(AUDIT, scheduled=True)
    assert (result.state, result.deleted, alive(old)) == (engine.RAN, 1, [False])


def test_the_audit_log_dry_run_with_the_flag_deletes_nothing():
    old = old_audit_row(2 * 365 * DAY)
    out = io.StringIO()
    call_command("retention", "--dry-run", "--include-opt-in", "--policy", AUDIT, stdout=out)
    assert "would delete 1" in out.getvalue() and alive(old) == [True]


# --- The summary audit row ---------------------------------------------------------------------


def test_one_summary_row_per_policy_per_run_and_only_when_something_was_removed():
    only(COMPLETED)  # nothing to remove
    assert not ActivityLog.objects.filter(action="core.retention.purged").exists()
    for _ in range(3):
        job_run("succeeded", 20 * DAY)
    only(COMPLETED, dry_run=True)  # a dry run records nothing either
    assert not ActivityLog.objects.filter(action="core.retention.purged").exists()
    only(COMPLETED)
    (row,) = ActivityLog.objects.filter(action="core.retention.purged")
    assert row.meta["policy"] == COMPLETED and row.meta["deleted"] == 3
    assert row.meta["truncated"] is False and row.meta["data_class"] == "operational_log"


# --- Missing tables, unknown keys, the job and the CLI -----------------------------------------


def test_a_policy_whose_model_is_not_installed_or_migrated_is_missing_not_an_error(monkeypatch):
    ghost = declared(key="core.ghost", model="ghost.Nothing")
    monkeypatch.setitem(registry.retention._policies, "core.ghost", ghost)
    (result,) = engine.run(only=["core.ghost"])
    (item,) = engine.status(only=["core.ghost"])
    assert (result.state, item.state) == (engine.MISSING, engine.MISSING)


def test_an_unknown_policy_key_is_refused():
    with pytest.raises(engine.UnknownPolicy):
        engine.run(only=["core.nope"])
    with pytest.raises(CommandError, match="unknown retention policy"):
        call_command("retention", "--policy", "core.nope")


def test_the_job_runs_every_policy_and_never_the_opt_in_one_by_default():
    from core.jobs import JobContext
    from core.retention.jobs import run_retention

    old_run, old_audit = job_run("succeeded", 20 * DAY), old_audit_row(2 * 365 * DAY)
    old_attempt = LoginAttempt.objects.create(identifier="x@example.com", succeeded=False)
    LoginAttempt.objects.filter(pk=old_attempt.pk).update(created_at=ago(120 * DAY))
    removed = run_retention(JobContext(run_id="r", job_name="core.retention"))
    assert removed == 2
    assert alive(old_run, old_audit, old_attempt) == [False, True, False]


def test_status_prints_one_row_per_policy():
    out = io.StringIO()
    call_command("retention", "--status", stdout=out)
    text = out.getvalue()
    for policy in registry.retention.policies():
        assert policy.key in text
    assert "eligible" in text and "cap" in text


def test_the_cli_dry_run_reports_counts_and_deletes_nothing():
    for _ in range(2):
        job_run("succeeded", 20 * DAY)
    out = io.StringIO()
    call_command("retention", "--dry-run", "--policy", COMPLETED, stdout=out)
    assert "core.job_run_completed: would delete 2" in out.getvalue()
    assert JobRun.objects.count() == 2


def test_the_job_is_registered_daily_and_idempotent():
    spec = registry.jobs.get("core.retention")
    assert spec.idempotent and spec.schedule is not None and spec.queue == "bulk"
    only(COMPLETED)
    assert only(COMPLETED).deleted == 0  # a second run finds nothing
