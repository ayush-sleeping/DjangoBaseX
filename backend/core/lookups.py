"""
Admin-editable vocabularies (CONFIGURATION.md § 14; BUILD 5.5).

A vocabulary's SET and seed keys are declared in code (registry.lookups); its values live in
core_lookup_value, where an admin can add one with no deploy. Records store the stable key, never
the label — a rename is a label edit, not a data migration. Membership is validated from the table
at request time; a deactivated value is refused for new or changed data and grandfathered where a
record already holds it.

    sync_lookups()                 # post_migrate: inserts MISSING seed keys only, never relabels
    LookupField(set_key="…")       # the serializer field every record uses
    set_lookup_value(...)          # the one writer (create and edit), audited
"""

import logging

from django.db import transaction
from rest_framework import serializers

from core.audit import log_activity
from core.models import LookupValue
from core.registry import LOOKUP_KEY_PATTERN, registry

logger = logging.getLogger("core.lookups")


class LookupError_(Exception):
    code = "invalid_lookup"


class UnknownLookupSet(LookupError_):
    code = "unknown_lookup_set"

    def __init__(self, set_key: str):
        super().__init__(f"{set_key!r} is not a declared lookup set.")


class LookupRefused(LookupError_):
    code = "invalid_lookup_value"


# --- Seeding: inserts missing keys only (§ 14) ----------------------------------------------------


def sync_lookups() -> list[str]:
    """Insert seed keys that do not exist yet. Never relabels, never reactivates, never deletes —
    the admin's edits always survive a reseed. Returns what it created, for the migrate log."""
    created = []
    for definition in registry.lookups.defs():
        existing = set(LookupValue.objects.in_set(definition.set_key).values_list("key", flat=True))
        for order, entry in enumerate(definition.seed):
            key, label, *system = entry
            if key in existing:
                continue  # theirs now, whatever its label or state
            LookupValue.objects.create(
                set_key=definition.set_key,
                key=key,
                label=label,
                sort_order=order * 10,
                is_system=bool(system and system[0]),
            )
            created.append(f"{definition.set_key}:{key}")
    return created


# --- The one writer -------------------------------------------------------------------------------


def set_lookup_value(
    set_key: str,
    key: str,
    *,
    actor=None,
    create: bool = False,
    **changes,
) -> LookupValue:
    """
    Edit a value's label, order, active state or meta — or create one (create=True, only for sets
    declaring admin_can_add). The key itself is never editable; a system value never deactivates.
    """
    if set_key not in registry.lookups:
        raise UnknownLookupSet(set_key)
    definition = registry.lookups.get(set_key)
    unknown = set(changes) - {"label", "sort_order", "is_active", "meta"}
    if unknown:
        raise LookupRefused(f"not editable: {sorted(unknown)} (the key is stable by design)")
    if "meta" in changes and definition.meta_schema is not None:
        try:
            definition.meta_schema(changes["meta"])
        except ValueError as exc:
            raise LookupRefused(f"meta {exc}") from None

    with transaction.atomic():
        row = LookupValue.objects.select_for_update().in_set(set_key).filter(key=key).first()
        if row is None:
            if not create:
                raise LookupRefused(f"{set_key} has no value {key!r}")
            if not definition.admin_can_add:
                raise LookupRefused(f"{set_key} does not accept admin-added values")
            if not LOOKUP_KEY_PATTERN.match(key or ""):
                raise LookupRefused("the key must be a slug (lowercase letters, digits, - and _)")
            if not str(changes.get("label", "")).strip():
                raise LookupRefused("a new value needs a label")
            row = LookupValue.objects.create(set_key=set_key, key=key, updated_by=actor, **changes)
            _audit("core.lookup.created", actor, row, old=None)
            return row
        if create:
            raise LookupRefused(f"{set_key}:{key} already exists")
        if changes.get("is_active") is False and row.is_system:
            raise LookupRefused(
                f"{key!r} is a system value code refers to; it cannot be turned off"
            )
        old = _state(row)
        for name, value in changes.items():
            setattr(row, name, value)
        if _state(row) == old:
            return row
        row.updated_by = actor
        row.save(update_fields=[*changes, "updated_by", "updated_at"])
        _audit("core.lookup.changed", actor, row, old=old)
    return row


def _state(row: LookupValue) -> dict:
    return {
        "label": row.label,
        "sort_order": row.sort_order,
        "is_active": row.is_active,
        "meta": row.meta,
    }


def _audit(verb: str, actor, row: LookupValue, old) -> None:
    transaction.on_commit(
        lambda: log_activity(
            verb, actor, set_key=row.set_key, key=row.key, old=old, new=_state(row)
        )
    )


# --- The serializer field every record uses (§ 14) ------------------------------------------------


class LookupField(serializers.SlugRelatedField):
    """
    Validates membership from the TABLE at request time — never a literal list, never choices=.
    A deactivated value is refused for new data and for changes, but accepted unchanged on a record
    that already holds it (grandfathered).
    """

    def __init__(self, set_key: str, **kwargs):
        self.set_key = set_key
        kwargs.setdefault("queryset", LookupValue.objects.in_set(set_key))
        super().__init__(slug_field="key", **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)  # membership, from the table, now
        current = getattr(getattr(self.parent, "instance", None), self.source, None)
        if not value.is_active and value != current:
            self.fail("does_not_exist", slug_name="key", value=data)
        return value
