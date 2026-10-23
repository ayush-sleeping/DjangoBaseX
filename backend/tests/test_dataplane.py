"""Data-plane self-checks (OBSERVABILITY.md § 7; BUILD_ORDER 6.2)."""

import pytest
from django.core.management import call_command

from core import dataplane
from core.registry import DataPlaneCheck, DataPlaneRegistry, RegistryError
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_cache():
    dataplane.clear_cache()
    yield
    dataplane.clear_cache()


def crash():
    raise RuntimeError("boom")


# --- The evaluator ------------------------------------------------------------------------------


def test_evaluator_never_raises():
    result = dataplane.run_check(DataPlaneCheck("x.crash", "Crashes.", crash))
    assert result.status == "warn"
    assert result.detail == "check crashed: RuntimeError"
    assert result.remedy  # a crashed check still tells the operator what to do


def test_a_check_returning_the_wrong_thing_is_a_warn_not_a_crash():
    result = dataplane.run_check(DataPlaneCheck("x.bad", "Bad.", lambda: True))
    assert result.status == "warn" and "not a Result" in result.detail


def test_a_non_ok_result_always_carries_a_remedy():
    result = dataplane.run_check(
        DataPlaneCheck("x.silent", "Silent.", lambda: dataplane.Result("fatal", "gone"))
    )
    assert result.status == "fatal" and result.remedy.startswith("Fix the x.silent check")


def test_results_are_cached_until_fresh_is_asked_for(settings, monkeypatch):
    settings.DATAPLANE_CACHE_SECONDS = 3600
    calls = []
    check = DataPlaneCheck("x.count", "Counts.", lambda: calls.append(1) or dataplane.ok())
    monkeypatch.setattr(dataplane.registry.dataplane, "checks", lambda: (check,))
    dataplane.evaluate()
    dataplane.evaluate()
    assert len(calls) == 1
    dataplane.evaluate(fresh=True)
    assert len(calls) == 2


# --- The registry -------------------------------------------------------------------------------


def test_registry_refuses_a_bad_key_or_description():
    reg = DataPlaneRegistry()
    with pytest.raises(RegistryError):
        reg.register(DataPlaneCheck("Bad Key", "desc", dataplane.ok))
    with pytest.raises(RegistryError):
        reg.register(DataPlaneCheck("x.ok", "", dataplane.ok))
    reg.register(DataPlaneCheck("x.ok", "A check.", dataplane.ok))
    with pytest.raises(RegistryError):
        reg.register(DataPlaneCheck("x.ok", "Again.", dataplane.ok))


# --- Core's checks, against the real registry ---------------------------------------------------


def test_every_registered_check_has_a_description_and_the_core_ones_are_present():
    keys = {c.key for c in dataplane.registry.dataplane.checks()}
    assert {"core.active_superuser", "core.administrator_role"} <= keys
    assert all(c.description.strip() for c in dataplane.registry.dataplane.checks())


def test_an_empty_install_is_fatal_with_remedies():
    results = {r.key: r for r in dataplane.evaluate(fresh=True)}
    assert results["core.active_superuser"].status == "fatal"
    assert "bootstrap_admin" in results["core.active_superuser"].remedy
    assert results["core.administrator_role"].status == "fatal"
    assert dataplane.worst(list(results.values())) == "fatal"


def test_a_bootstrapped_install_is_ok(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "correct horse battery staple 42")
    call_command("bootstrap_admin", "--email", "admin@example.com", "--no-input")
    results = {r.key: r for r in dataplane.evaluate(fresh=True)}
    assert {r.status for r in results.values()} == {"ok"}


def test_fatal_refuses_the_entrypoint_gate(capsys):
    with pytest.raises(SystemExit) as exc:
        call_command("dataplane", "--fatal-only")
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "FATAL core.active_superuser" in out and "fix:" in out


def test_a_warn_passes_fatal_only_but_fails_the_full_gate(monkeypatch):
    UserFactory(is_superuser=True)  # not enough for administrator_role, so...
    monkeypatch.setattr(
        dataplane.registry.dataplane,
        "checks",
        lambda: (
            DataPlaneCheck(
                "x.dormant", "Dormant.", lambda: dataplane.warn("off", remedy="turn it on")
            ),
        ),
    )
    call_command("dataplane", "--fatal-only")  # does not raise
    with pytest.raises(SystemExit):
        call_command("dataplane")
