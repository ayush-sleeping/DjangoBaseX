"""Guard modes (CONFIGURATION.md § 13): off records nothing, log_only records and passes, enforce
records and refuses with the declared code, an unreadable mode uses the declared default — and
shipping a guard at its default changes no response."""

import pytest

from core import guards as guards_module
from core import settings_service
from core.guards import GuardDef, GuardRefused, check_guard, guard_mode, register_guard
from core.registry import Registry, RegistryError
from core.settings_service import set_value

pytestmark = pytest.mark.django_db

KEY = "users.probe_refusal"


def guard_def(**overrides):
    base = dict(
        key=KEY,
        default_mode="log_only",
        description="Refuse a probe action.",
        error_code="users.probe_refused",
    )
    base.update(overrides)
    return GuardDef(**base)


@pytest.fixture
def registered(monkeypatch):
    """One guard (and its .mode setting) in a registry of our own, patched in everywhere."""
    reg = Registry()
    for module in (guards_module, settings_service):
        monkeypatch.setattr(module, "registry", reg)
    register_guard(guard_def())
    return reg


def test_register_guard_declares_the_mode_switch_with_it(registered):
    defn = registered.settings.get(f"{KEY}.mode")
    assert defn.type.choices == ("off", "log_only", "enforce")
    assert defn.default == "log_only"
    assert guard_mode(KEY) == "log_only"


def test_a_default_of_enforce_needs_a_written_reason():
    reg = Registry()
    with pytest.raises(RegistryError, match="written reason"):
        reg.guards.register(guard_def(default_mode="enforce"))
    reg.guards.register(
        guard_def(default_mode="enforce", enforce_reason="Closes a known vulnerability.")
    )


def guard_rows(audit_rows):
    return [r for r in audit_rows() if r.action.startswith("guard.")]


def test_not_violated_does_nothing_in_every_mode(registered, audit_rows):
    for mode in ("off", "log_only", "enforce"):
        set_value(f"{KEY}.mode", mode)
        check_guard(KEY, violated=False)
    assert guard_rows(audit_rows) == []


def test_off_records_nothing_and_passes(registered, audit_rows):
    set_value(f"{KEY}.mode", "off")
    check_guard(KEY, violated=True)
    assert guard_rows(audit_rows) == []


def test_log_only_records_would_block_with_context_and_passes(registered, audit_rows):
    check_guard(KEY, violated=True, code="users.probe")  # shipped default: log_only
    (event,) = guard_rows(audit_rows)
    assert event.action == "guard.would_block"
    assert event.meta == {"guard": KEY, "mode": "log_only", "code": "users.probe"}


def test_enforce_records_blocked_and_refuses_with_the_declared_code(registered, audit_rows):
    set_value(f"{KEY}.mode", "enforce")
    with pytest.raises(GuardRefused) as refusal:
        check_guard(KEY, violated=True)
    (event,) = guard_rows(audit_rows)
    assert event.action == "guard.blocked"
    assert refusal.value.detail["error"]["code"] == "users.probe_refused"
    assert refusal.value.status_code == 403


def test_an_unreadable_mode_resolves_to_the_declared_default(registered, monkeypatch):
    set_value(f"{KEY}.mode", "enforce")

    def broken(key, user=None):
        raise RuntimeError("settings are down")

    monkeypatch.setattr(guards_module, "get_setting", broken)
    assert guard_mode(KEY) == "log_only"  # the declaration's default, never enforce-by-accident
    check_guard(KEY, violated=True)  # and log_only passes the request through


def test_an_undeclared_guard_is_a_typo_not_a_mode(registered):
    with pytest.raises(KeyError):
        check_guard("users.typo_guard", violated=True)


# --- § 13's done-when: shipping a guard at its default changes no response ------------------------


def guarded_flow(violated=True):
    """The flow a guard would block: it 'succeeds' unless check_guard raises."""
    check_guard(KEY, violated=violated)
    return "succeeded"


def test_shipping_the_guard_at_its_default_changes_no_response(registered):
    # Installed, never touched by an admin: the flow it would block still succeeds (§ 13).
    assert guarded_flow() == "succeeded"


def test_positive_control_the_same_flow_fails_once_enforced(registered):
    # The test above proves nothing unless THIS one fails the flow: the guard does bite.
    set_value(f"{KEY}.mode", "enforce")
    with pytest.raises(GuardRefused):
        guarded_flow()


def test_no_real_guard_ships_at_enforce_without_a_reason():
    # Over the REAL registry: § 13's rule for every guard a module ever registers. Empty today —
    # the positive control is test_a_default_of_enforce_needs_a_written_reason above.
    from core.registry import registry

    offenders = [
        g.key
        for g in registry.guards.defs()
        if g.default_mode == "enforce" and not g.enforce_reason.strip()
    ]
    assert offenders == []
