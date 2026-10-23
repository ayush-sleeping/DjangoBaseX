"""
Reading and writing settings through the one service (CONFIGURATION.md § 9.5–9.8; BUILD 5.3).

The cascade tests run against their own Registry (monkeypatched in), so they can declare scopes;
the end-to-end tests use the real registered security.reauth.* keys.
"""

import logging
from dataclasses import dataclass, field

import pytest
from django.db import DatabaseError

from core import settings_service
from core.models import Setting
from core.registry import Registry
from core.settings_registry import Int, SettingInvalid, UnknownSetting, meta, stored
from core.settings_service import get_setting, report, reset, resolve, resolve_setting, set_value
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

KEY = "security.reauth.window_minutes"
ACTIONS = "security.reauth.actions"


# --- A registry of our own, for scope tests -------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    limit: int = field(
        default=10,
        metadata=meta(
            Int(min=1, max=100),
            label="A limit",
            description="d",
            changed_by_event="e",
            used_by=("Tests",),
            scopes=("platform", "tenant", "user"),
        ),
    )


@pytest.fixture
def scoped(monkeypatch):
    reg = Registry()
    reg.settings.register_group(Probe, prefix="users.probe", module="users", group="Probes")
    monkeypatch.setattr(settings_service, "registry", reg)
    return reg


# --- Reading (§ 9.5, § 9.6) -----------------------------------------------------------------------


def test_the_code_default_applies_with_no_row_and_an_unregistered_key_raises():
    resolved = resolve_setting(KEY)
    assert (resolved.value, resolved.source) == (15, "default")
    with pytest.raises(UnknownSetting):
        get_setting("security.reauth.typo")
    with pytest.raises(UnknownSetting):
        set_value("security.reauth.typo", 1)


def test_the_cascade_is_user_then_tenant_then_platform(scoped):
    user = UserFactory()
    scoped.settings.set_tenant_resolver(lambda u: "tenant-1")
    assert resolve_setting("users.probe.limit", user).source == "default"
    set_value("users.probe.limit", 30)
    assert resolve_setting("users.probe.limit", user).source == "platform"
    set_value("users.probe.limit", 40, scope="tenant", scope_id="tenant-1")
    assert get_setting("users.probe.limit", user) == 40
    set_value("users.probe.limit", 50, scope="user", scope_id=str(user.public_id))
    assert resolve_setting("users.probe.limit", user).source == "user"
    assert get_setting("users.probe.limit") == 30  # no user: the platform's value


def test_a_locked_platform_row_stops_the_cascade(scoped):
    user = UserFactory()
    set_value("users.probe.limit", 50, scope="user", scope_id=str(user.public_id))
    set_value("users.probe.limit", 30, locked=True)
    resolved = resolve_setting("users.probe.limit", user)
    assert (resolved.value, resolved.source, resolved.locked) == (30, "platform", True)


def test_an_undeclared_scope_is_refused():
    with pytest.raises(SettingInvalid, match="cannot be set at user scope"):
        set_value(KEY, 30, scope="user", scope_id="x")  # KEY declares platform only


def test_tenant_scope_is_inert_until_a_resolver_registers(scoped):
    with pytest.raises(SettingInvalid, match="no tenancy module"):
        set_value("users.probe.limit", 30, scope="tenant", scope_id="x")  # declared, no resolver


def test_a_stored_row_below_a_later_floor_is_clamped_on_read():
    Setting.objects.create(key=KEY, scope_type="platform", value=stored(0))
    assert get_setting(KEY) == 1  # Int(min=1): validated on write, clamped on read


def test_a_row_that_no_longer_coerces_falls_back_logged(caplog):
    Setting.objects.create(key=KEY, scope_type="platform", value=stored("soon"))
    with caplog.at_level(logging.WARNING, logger="core.settings"):
        assert get_setting(KEY) == 15
    assert any(r.message == "core.setting.fallback" for r in caplog.records)


def test_a_database_failure_degrades_to_the_default_not_an_exception(monkeypatch, caplog):
    def boom(*a, **k):
        raise DatabaseError("down")

    monkeypatch.setattr(settings_service.Setting.objects, "for_key", boom)
    with caplog.at_level(logging.WARNING, logger="core.settings"):
        assert get_setting(KEY) == 15
    assert any(getattr(r, "reason", "") == "database" for r in caplog.records), (
        "the fallback names its reason"
    )


def test_resolve_returns_the_frozen_policy():
    from users.reauth import ReauthPolicy

    set_value(ACTIONS, ["mfa_disable"])
    policy = resolve(ReauthPolicy)
    assert policy == ReauthPolicy(actions=("mfa_disable",), window_minutes=15)
    with pytest.raises(UnknownSetting):
        resolve(Probe)  # never registered in the real registry


# --- Writing and audit (§ 9.8) --------------------------------------------------------------------


def test_every_change_is_audited_old_to_new(audit_rows, django_capture_on_commit_callbacks):
    actor = UserFactory()
    with django_capture_on_commit_callbacks(execute=True):
        set_value(KEY, 30, actor=actor, reason="an audit finding")
    with django_capture_on_commit_callbacks(execute=True):
        set_value(KEY, 45, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        assert reset(KEY, actor=actor) is True
    events = [r for r in audit_rows() if r.action.startswith("core.setting.")]
    assert [e.action for e in events] == [
        "core.setting.changed",
        "core.setting.changed",
        "core.setting.reset",
    ]
    first, second, third = (e.meta for e in events)
    assert (first["old"], first["new"], first["old_source"]) == (15, 30, "default")
    assert (second["old"], second["new"]) == (30, 45)
    assert (third["old"], third["new"]) == (45, 15)
    assert events[0].actor_id == str(actor.public_id)
    assert events[0].actor_label == actor.email  # the snapshot that survives the actor's deletion


def test_a_write_that_changes_nothing_is_not_a_change(
    audit_rows, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        set_value(KEY, 30)
    assert len(audit_rows("core.setting.changed")) == 1
    with django_capture_on_commit_callbacks(execute=True):
        set_value(KEY, 30)
    assert len(audit_rows("core.setting.changed")) == 1  # the second wrote nothing
    assert Setting.objects.count() == 1


def test_reset_with_no_override_removes_nothing():
    assert reset(KEY) is False


def test_a_writer_reads_its_own_write_within_one_snapshot():
    token = settings_service.begin_snapshot()
    try:
        assert get_setting(KEY) == 15
        set_value(KEY, 30)
        assert get_setting(KEY) == 30  # the memo was invalidated by the write
    finally:
        settings_service.end_snapshot(token)


def test_an_admin_save_is_seen_at_once_not_after_a_ttl():
    assert get_setting(KEY) == 15  # cached, absence included
    set_value(KEY, 30)
    assert get_setting(KEY) == 30  # the generation bump abandons the cached absence


# --- sync_settings: reports, never writes (§ 9.2) -------------------------------------------------


def test_the_report_finds_orphans_and_invalid_rows_and_writes_nothing(
    django_assert_num_queries,
):
    set_value(KEY, 30)
    Setting.objects.create(key="users.gone.key", scope_type="platform", value=stored(1))
    Setting.objects.create(key=ACTIONS, scope_type="user", scope_id="u1", value=stored([]))
    Setting.objects.create(key=KEY, scope_type="user", scope_id="u2", value=stored("x"))

    before = list(Setting.objects.values())
    problems = {(f.key, f.scope): f.problem for f in report()}
    assert ("users.gone.key", "platform") in problems  # kept, reported, never deleted
    assert "scope" in problems[(ACTIONS, "user:u1")]
    assert (KEY, "user:u2") in problems
    assert list(Setting.objects.values()) == before  # byte for byte: nothing reset
    assert {(f.key, f.scope): f.problem for f in report()} == problems  # and again


def test_the_cli_wraps_the_same_service(capsys):
    from django.core.management import CommandError, call_command

    call_command("set_setting", KEY, "30")
    assert get_setting(KEY) == 30
    with pytest.raises(CommandError, match="whole number"):
        call_command("set_setting", KEY, "soon")
    with pytest.raises(CommandError, match="not a registered setting"):
        call_command("set_setting", "security.reauth.typo", "1")
    call_command("set_setting", KEY, "--reset")
    assert get_setting(KEY) == 15
    call_command("sync_settings")
    assert "every stored override is valid" in capsys.readouterr().out
    Setting.objects.create(key="users.gone.key", scope_type="platform", value=stored(1))
    with pytest.raises(CommandError, match="nothing changed"):
        call_command("sync_settings")
