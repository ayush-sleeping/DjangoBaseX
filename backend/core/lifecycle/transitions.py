"""
State-transition history (DATA_LIFECYCLE.md § 5). A state field is declared with
registry.state_fields; every change goes through change_state(), which saves the field and writes
the core_state_transition row in ONE transaction, so there is no state without its history.
"""

from django.db import transaction

from core import audit
from core.registry import registry

from .models import StateTransition


class UnregisteredStateField(Exception):
    """change_state() on a (model, field) nobody declared in registry.state_fields."""


def _raw(value) -> str:
    return "" if value is None else str(value)[:64]


def change_state(obj, field: str, to_state, *, actor=None, reason: str = "", also_save=()) -> bool:
    """
    Move `obj.<field>` to `to_state`, recording (object, field, from, to, actor, source, reason).
    Returns False (and writes nothing) when it is already there. `also_save` names sibling columns
    the caller set on `obj` that belong in the same UPDATE. A system write passes actor=None and
    is recorded as actor "system", never "whoever is resolvable".
    """
    label = obj._meta.label
    if registry.state_fields.get(label, field) is None:
        raise UnregisteredStateField(f"{label}.{field} is not in registry.state_fields")
    old = getattr(obj, field)
    if old == to_state:
        if also_save:  # no transition to record, but the caller's sibling columns still persist
            obj.save(update_fields=list(also_save))
        return False
    snapshot = audit.actor_snapshot(actor)
    with transaction.atomic():
        setattr(obj, field, to_state)
        obj.save(update_fields=[field, *also_save])
        StateTransition.objects.create(
            object_type=obj._meta.label_lower,
            object_id=str(getattr(obj, "public_id", None) or obj.pk),
            field=field,
            from_state=_raw(old),
            to_state=_raw(to_state),
            actor_id=snapshot.get("actor_id"),
            actor_label=snapshot.get("actor_label", "system"),
            source=audit.provenance_source(),
            reason=reason[:255],
        )
    return True


def history(obj, field: str | None = None):
    """The recorded transitions of one object, oldest first."""
    rows = StateTransition.objects.filter(
        object_type=obj._meta.label_lower, object_id=str(getattr(obj, "public_id", None) or obj.pk)
    )
    return (rows.filter(field=field) if field else rows).order_by("occurred_at", "id")
