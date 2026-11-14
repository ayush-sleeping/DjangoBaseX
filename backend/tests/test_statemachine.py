"""The state-machine helper (DOMAIN_PRIMITIVES.md § 3, BUILD_ORDER 9.4): illegal moves are refused,
legal ones are recorded through change_state(), and every declaration is checked at boot."""

import pytest

from core import statemachine
from core.lifecycle.transitions import history
from core.registry import Registry, RegistryError, StateMachine, registry
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def machine(**over):
    base = dict(
        key="users.user.is_active",
        model="users.User",
        field="is_active",
        initial=True,
        transitions={True: {False}, False: set()},
    )
    base.update(over)
    return StateMachine(**base)


@pytest.fixture
def one_way(monkeypatch):
    reg = Registry()
    reg.state_machines.register(machine(reason_required=frozenset({(True, False)})))
    monkeypatch.setattr(statemachine, "registry", reg)


def test_a_declared_move_is_recorded_through_change_state():
    user = UserFactory()
    assert statemachine.transition(user, "is_active", False, reason="left") is True
    row = history(user, "is_active").get()
    assert (row.from_state, row.to_state, row.reason) == ("True", "False", "left")
    assert statemachine.allowed_targets(user, "is_active") == [True]


def test_moving_to_the_state_a_row_is_already_in_is_a_no_op():
    user = UserFactory()
    assert statemachine.transition(user, "is_active", True) is False
    assert not history(user).exists()


def test_an_undeclared_move_is_refused_with_a_typed_error_and_writes_nothing(one_way):
    user = UserFactory(is_active=False)
    with pytest.raises(statemachine.IllegalTransition):
        statemachine.transition(user, "is_active", True, reason="x")
    user.refresh_from_db()
    assert not user.is_active
    assert not history(user).exists()


def test_a_correction_pair_needs_a_reason(one_way):
    user = UserFactory()
    with pytest.raises(statemachine.ReasonRequired):
        statemachine.transition(user, "is_active", False, reason="  ")
    assert statemachine.transition(user, "is_active", False, reason="why") is True


def test_the_check_uses_the_stored_state_not_a_stale_object(one_way):
    stale = UserFactory()
    type(stale).objects.filter(pk=stale.pk).update(is_active=False)  # another request won
    with pytest.raises(statemachine.IllegalTransition):
        statemachine.transition(stale, "is_active", True, reason="x")


def test_a_field_without_a_machine_is_refused():
    user = UserFactory()
    with pytest.raises(statemachine.NoStateMachine):
        statemachine.transition(user, "full_name", "x")


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"transitions": {"a": {"b"}}, "initial": "a"}, "not a declared state"),
        ({"transitions": {"a": set(), "b": set()}, "initial": "a"}, "unreachable"),
        ({"transitions": {"a": set()}, "initial": "z"}, "initial is not"),
        (
            {
                "transitions": {"a": {"b"}, "b": set()},
                "initial": "a",
                "reason_required": frozenset({("b", "a")}),
            },
            "undeclared move",
        ),
    ],
)
def test_a_bad_declaration_is_refused_at_registration(kwargs, why):
    with pytest.raises(RegistryError, match=why):
        Registry().state_machines.register(machine(**kwargs))


def test_every_registered_machine_is_a_registered_state_field_and_sound():
    machines = registry.state_machines.all()
    assert machines, "users registers the is_active machine"
    for sm in machines:
        assert registry.state_fields.get(sm.model, sm.field) is not None, sm.key
        assert not registry.state_machines.problems(sm), sm.key
