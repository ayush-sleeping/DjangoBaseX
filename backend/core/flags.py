"""
Feature flags: resolution, the one writer, and the route gate (CONFIGURATION.md § 11; BUILD 5.4).

The resolution order is the contract, kill-switch first:
  1. an unregistered key is off, always — no default parameter exists anywhere
  2. no row yet is off — release flags start dark
  3. enabled=False is off for everyone, targets included — the kill switch beats every target
  4. enabled with no targeting is on for everyone
  5. enabled with targeting is on only for a matching user, role or tenant; anonymous never matches
  6. NULL and [] targeting are identical

Rows are cached in the shared cache under a generation every committed write bumps, exactly like
settings (§ 9.7): an admin's kill switch takes effect at once on every worker. A cache or database
failure resolves the flag OFF — dark is the safe answer a flag was built around.
"""

import logging
import time

from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, transaction
from django.http import Http404
from rest_framework.permissions import BasePermission

from core.audit import log_activity
from core.models import FeatureFlag
from core.registry import registry

logger = logging.getLogger("core.flags")

GENERATION_KEY = "flags:generation"
ENTRY_TIMEOUT = 24 * 60 * 60
_ABSENT = {"found": False}

TARGET_FIELDS = ("user_ids", "role_slugs", "tenant_ids")


class UnknownFlag(Exception):
    """A WRITE to an undeclared key. Reads never raise: an unknown key simply resolves off."""

    code = "unknown_flag"

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"{key!r} is not a registered feature flag.")


# --- The cache (the § 9.7 pattern) ----------------------------------------------------------------


def _generation() -> int | None:
    try:
        generation = cache.get(GENERATION_KEY)
        if generation is None:
            cache.add(GENERATION_KEY, time.time_ns() // 1000, timeout=None)
            generation = cache.get(GENERATION_KEY)
        return generation
    except Exception:  # noqa: BLE001 — no cache means read the database
        return None


def _bump_generation() -> None:
    try:
        cache.incr(GENERATION_KEY)
    except ValueError:
        cache.add(GENERATION_KEY, time.time_ns() // 1000, timeout=None)
    except Exception:  # noqa: BLE001
        logger.error("core.flag.generation_not_bumped", extra={"reason": "cache"})


def _row(key: str) -> dict | None:
    """The flag's state and targeting, cached; None when the database cannot answer (⇒ off)."""
    generation = _generation()
    cache_key = f"flags:{generation}:{key}"
    if generation is not None:
        try:
            entry = cache.get(cache_key)
        except Exception:  # noqa: BLE001
            generation, entry = None, None
        if entry is not None:
            return entry
    try:
        values = (
            FeatureFlag.objects.filter(key=key)
            .values("enabled", "user_ids", "role_slugs", "tenant_ids")
            .first()
        )
    except DatabaseError:
        logger.warning("core.flag.fallback", extra={"flag_key": key, "reason": "database"})
        return _ABSENT
    entry = _ABSENT if values is None else {"found": True, **values}
    if generation is not None:
        try:
            cache.set(cache_key, entry, ENTRY_TIMEOUT)
        except Exception:  # noqa: BLE001
            pass
    return entry


# --- Resolution -----------------------------------------------------------------------------------


def _role_slugs(user) -> set[str]:
    try:
        return set(user.user_roles.values_list("role__slug", flat=True))
    except DatabaseError:
        logger.warning("core.flag.fallback", extra={"reason": "database"})
        return set()


def flag_enabled(key: str, *, user=None, tenant=None) -> bool:
    if key not in registry.flags:
        return False  # rule 1: unknown is off, and a deleted flag never re-enables a feature
    row = _row(key)
    if not row.get("found") or not row.get("enabled"):
        return False  # rules 2 and 3: dark until written; the kill switch beats every target
    targets = {name: row.get(name) or [] for name in TARGET_FIELDS}
    if not any(targets.values()):
        return True  # rule 4 (and 6: NULL and [] are the same)
    if user is None or not getattr(user, "is_authenticated", False):
        return False  # rule 5: anonymous matches nothing
    if str(user.public_id) in targets["user_ids"]:
        return True
    if targets["role_slugs"] and _role_slugs(user) & set(targets["role_slugs"]):
        return True
    tenant_id = getattr(tenant, "public_id", None)
    return tenant_id is not None and str(tenant_id) in targets["tenant_ids"]


def flags_for(user) -> list[str]:
    """The keys on for this caller — the /me bootstrap list. Never the whole catalogue: an off
    flag's name is an unreleased feature's name (§ 11)."""
    return [d.key for d in registry.flags.defs() if flag_enabled(d.key, user=user)]


# --- The one writer -------------------------------------------------------------------------------


def set_flag(key: str, *, actor=None, reason: str = "", **changes) -> FeatureFlag:
    """
    Write state or targeting (enabled, user_ids, role_slugs, tenant_ids). Only registered keys get
    rows, every write is audited old → new, and the generation bump makes it land at once.
    """
    if key not in registry.flags:
        raise UnknownFlag(key)
    unknown = set(changes) - {"enabled", *TARGET_FIELDS}
    if unknown:
        raise ValueError(f"not flag fields: {sorted(unknown)}")
    if "enabled" in changes and not isinstance(changes["enabled"], bool):
        raise ValueError("enabled must be true or false")
    for name in TARGET_FIELDS:
        if name in changes:
            values = changes[name] or []
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ValueError(f"{name} must be a list of ids (strings)")
            changes[name] = sorted(set(values))

    with transaction.atomic():
        row = FeatureFlag.objects.select_for_update().filter(key=key).first()
        created = row is None
        if created:
            try:
                with transaction.atomic():
                    row = FeatureFlag.objects.create(key=key, updated_by=actor, **changes)
            except IntegrityError:  # a concurrent first write won: update theirs
                created = False
                row = FeatureFlag.objects.select_for_update().get(key=key)
        if created:
            old, new = None, _state(row)
        else:
            old = _state(row)
            for name, value in changes.items():
                setattr(row, name, value)
            new = _state(row)
            if old == new:
                return row
            row.updated_by = actor
            row.save(update_fields=[*changes, "updated_by", "updated_at"])

        def committed():
            _bump_generation()
            log_activity("core.flag.changed", actor, key=key, old=old, new=new, reason=reason)

        _bump_generation()  # this transaction reads its own write
        transaction.on_commit(committed)
    return row


def _state(row: FeatureFlag) -> dict:
    return {
        "enabled": row.enabled,
        **{name: list(getattr(row, name) or []) for name in TARGET_FIELDS},
    }


# --- The route gate -------------------------------------------------------------------------------


def requires_flag(key: str) -> type[BasePermission]:
    """
    A permission class gating a route on `key`. Off answers 404, never 403: an unreleased feature
    is undiscoverable (§ 11). The key is checked at declaration, so a typo'd view fails at import.
    """
    if key not in registry.flags:
        raise UnknownFlag(key)

    def has_permission(self, request, view):
        if flag_enabled(key, user=getattr(request, "user", None)):
            return True
        raise Http404

    return type(f"RequiresFlag[{key}]", (BasePermission,), {"has_permission": has_permission})
