"""
The state-machine helper (DOMAIN_PRIMITIVES.md § 3). A registered StateMachine declares the legal
moves of a state field; transition() refuses the rest with a typed error and records every legal
one through core.lifecycle.transitions.change_state(), so there is no move without its history.

    registry.state_fields.register(StateField(key=..., model="users.User", field="is_active"))
    registry.state_machines.register(StateMachine(key=..., model=..., field=..., initial=True,
        transitions={True: {False}, False: {True}}))

Moving to the state a row is already in is a no-op returning False (idempotent, like change_state).
The move is checked against the CURRENT stored value under a row lock, so two concurrent
transitions cannot both succeed from the same state.
"""

from django.db import transaction

from core.lifecycle.transitions import change_state
from core.registry import registry


class StateMachineError(Exception):
    code = "state_machine_error"


class NoStateMachine(StateMachineError):
    code = "no_state_machine"


class IllegalTransition(StateMachineError):
    code = "illegal_transition"


class ReasonRequired(StateMachineError):
    code = "reason_required"


def _machine(obj, field: str):
    machine = registry.state_machines.get(obj._meta.label, field)
    if machine is None:
        raise NoStateMachine(f"{obj._meta.label}.{field} has no registered state machine")
    return machine


def allowed_targets(obj, field: str) -> list:
    """The states `obj` may move to now, in a stable order (an API's legal moves)."""
    machine = _machine(obj, field)
    return sorted(machine.transitions.get(getattr(obj, field), ()), key=repr)


def transition_options(obj, field: str) -> list[dict]:
    """The legal moves from `obj`'s current state, each saying whether it needs a reason: what an
    API returns so a client draws its buttons without repeating the machine's rules."""
    machine = _machine(obj, field)
    current = getattr(obj, field)
    return [
        {"to": to, "needs_reason": (current, to) in machine.reason_required}
        for to in allowed_targets(obj, field)
    ]


def transition(obj, field: str, to, *, actor=None, reason: str = "", also_save=()) -> bool:
    machine = _machine(obj, field)
    with transaction.atomic():
        current = (
            type(obj)
            ._base_manager.select_for_update()
            .filter(pk=obj.pk)
            .values_list(field, flat=True)
            .get()
        )
        if current == to:
            return change_state(obj, field, to, actor=actor, reason=reason, also_save=also_save)
        if to not in machine.transitions.get(current, ()):
            raise IllegalTransition(
                f"{obj._meta.label}.{field}: {current!r} -> {to!r} is not allowed"
            )
        if (current, to) in machine.reason_required and not reason.strip():
            raise ReasonRequired(f"{current!r} -> {to!r} needs a reason")
        setattr(obj, field, current)  # the row, not a stale in-memory value, is the from-state
        return change_state(obj, field, to, actor=actor, reason=reason, also_save=also_save)
