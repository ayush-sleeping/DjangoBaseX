"""
Reading and writing settings (CONFIGURATION.md § 9.5–9.8; BUILD_ORDER 5.3).

    get_setting("security.reauth.window_minutes", user=request.user)   # a typed value
    resolve(ReauthPolicy, user=request.user)                            # a frozen policy object
    set_value(key, value, scope="platform", actor=admin, reason="...")  # the ONE writer
    reset(key, scope="platform", actor=admin)                           # back to the code default

Resolution is user → tenant → platform → code default, restricted to the scopes a setting declares;
a locked platform row stops it. A reader never raises for a database, cache or row failure: it logs
`core.setting.fallback`, skips that scope and carries on, down to the code default. An unregistered
key always raises UnknownSetting (owner decision, CONFIGURATION.md pending decision #8).

Caching is the shared cache only, under a generation that every committed write bumps, plus one
request-local snapshot (SettingsSnapshotMiddleware). Never a per-process cache with a TTL: an admin
saves, and one worker in eight obeys.
"""

import contextvars
import logging
import time
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, transaction

from core.audit import log_activity
from core.models import Setting
from core.registry import registry
from core.settings_registry import SettingDef, SettingInvalid, UnknownSetting, stored, unwrap

logger = logging.getLogger("core.settings")

GENERATION_KEY = "settings:generation"
# Entries under an old generation are never read again; the timeout only gives the memory back.
ENTRY_TIMEOUT = 24 * 60 * 60
_ABSENT = {"found": False}  # absence is cached; a failure never is (§ 9.7)

_snapshot: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "core_settings_snapshot", default=None
)


@dataclass(frozen=True)
class Resolved:
    key: str
    value: Any
    source: str  # "user" · "tenant" · "platform" · "default"
    locked: bool = False


# --- Declarations --------------------------------------------------------------------------------


def definition(key: str) -> SettingDef:
    try:
        return registry.settings.get(key)
    except KeyError:
        raise UnknownSetting(key) from None


# --- The request snapshot ------------------------------------------------------------------------


def begin_snapshot() -> contextvars.Token:
    """One consistent value per key for a unit of work. Reset by the middleware per request; a
    job runner must do the same per task, or the snapshot outlives the work (§ 9.7)."""
    return _snapshot.set({})


def end_snapshot(token: contextvars.Token) -> None:
    _snapshot.reset(token)


# --- The cache -----------------------------------------------------------------------------------


def _fallback(key: str, reason: str, **extra) -> None:
    # The structured stand-in for setting_resolution_fallback_total{key,reason} until metrics land.
    logger.warning("core.setting.fallback", extra={"setting_key": key, "reason": reason, **extra})


def _generation() -> int | None:
    """The current generation, or None when the cache is unavailable (then: no cache, never a
    stale one). A missing generation starts at the clock, so it never reuses an evicted one's
    entries."""
    try:
        generation = cache.get(GENERATION_KEY)
        if generation is None:
            cache.add(GENERATION_KEY, time.time_ns() // 1000, timeout=None)
            generation = cache.get(GENERATION_KEY)
        return generation
    except Exception:  # noqa: BLE001 — any cache failure means "read the database"
        _fallback("*", "cache")
        return None


def _bump_generation() -> None:
    try:
        cache.incr(GENERATION_KEY)
    except ValueError:  # evicted: a fresh start is newer than every entry already cached
        cache.add(GENERATION_KEY, time.time_ns() // 1000, timeout=None)
    except Exception:  # noqa: BLE001
        logger.error("core.setting.generation_not_bumped", extra={"reason": "cache"})


def _entry_key(generation: int, scope_type: str, scope_id: str | None, key: str) -> str:
    return f"settings:{generation}:{scope_type}:{scope_id or '-'}:{key}"


def _lookup(key: str, scope_type: str, scope_id: str | None) -> dict | None:
    """The cached or stored entry for one scope; None when it cannot be read (logged)."""
    generation = _generation()
    if generation is not None:
        try:
            entry = cache.get(_entry_key(generation, scope_type, scope_id, key))
        except Exception:  # noqa: BLE001
            _fallback(key, "cache", scope=scope_type)
            generation, entry = None, None
        if entry is not None:
            return entry
    try:
        row = (
            Setting.objects.for_key(key)
            .at(scope_type, scope_id)
            .values("value", "is_locked")
            .first()
        )
    except DatabaseError:
        _fallback(key, "database", scope=scope_type)
        return None
    entry = (
        _ABSENT if row is None else {"found": True, "v": row["value"], "locked": row["is_locked"]}
    )
    if generation is not None:
        try:
            cache.set(_entry_key(generation, scope_type, scope_id, key), entry, ENTRY_TIMEOUT)
        except Exception:  # noqa: BLE001
            _fallback(key, "cache", scope=scope_type)
    return entry


def _value_of(defn: SettingDef, entry: dict | None, scope_type: str) -> tuple[bool, Any]:
    """(found, value) for a scope's entry; a row that no longer coerces is skipped, logged."""
    if not entry or not entry.get("found"):
        return False, None
    try:
        return True, defn.read(unwrap(entry["v"]))
    except (ValueError, SettingInvalid):
        _fallback(defn.key, "invalid_row", scope=scope_type)
        return False, None


# --- Reading -------------------------------------------------------------------------------------


def _scope_ids(defn: SettingDef, user) -> list[tuple[str, str]]:
    """(scope_type, scope_id) for the user and tenant steps this setting and caller have."""
    steps = []
    if "user" in defn.scopes and user is not None and getattr(user, "is_authenticated", False):
        steps.append(("user", str(user.public_id)))
    if "tenant" in defn.scopes and user is not None:
        resolver = registry.settings.tenant_resolver()
        if resolver is not None:
            try:
                tenant = resolver(user)
            except Exception:  # noqa: BLE001 — a broken resolver degrades, it does not crash
                _fallback(defn.key, "tenant_resolver")
                tenant = None
            if tenant:
                steps.append(("tenant", str(tenant)))
    return steps


def resolve_setting(key: str, user=None) -> Resolved:
    """The effective value of `key` for `user` (None: the platform's), and where it came from."""
    defn = definition(key)
    snapshot = _snapshot.get()
    memo_key = (key, getattr(user, "pk", None))
    if snapshot is not None and memo_key in snapshot:
        return snapshot[memo_key]

    resolved, platform_found, platform_value = None, False, None
    if "platform" in defn.scopes:
        platform = _lookup(key, "platform", None)
        platform_found, platform_value = _value_of(defn, platform, "platform")
        if platform_found and platform.get("locked"):
            resolved = Resolved(key, platform_value, "platform", locked=True)
    if resolved is None:
        for scope_type, scope_id in _scope_ids(defn, user):
            found, value = _value_of(defn, _lookup(key, scope_type, scope_id), scope_type)
            if found:
                resolved = Resolved(key, value, scope_type)
                break
    if resolved is None and platform_found:
        resolved = Resolved(key, platform_value, "platform")
    if resolved is None:
        resolved = Resolved(key, defn.read(defn.to_json(defn.default)), "default")

    if snapshot is not None:
        snapshot[memo_key] = resolved
    return resolved


def get_setting(key: str, user=None) -> Any:
    return resolve_setting(key, user).value


def resolve(policy: type, user=None):
    """A registered policy dataclass, filled with effective values. Immutable; never raises for
    storage failures (UnknownSetting for a class that was never registered)."""
    try:
        keys = registry.settings.keys_of(policy)
    except KeyError:
        raise UnknownSetting(getattr(policy, "__name__", str(policy))) from None
    return policy(**{name: get_setting(key, user) for name, key in keys.items()})


# --- Writing -------------------------------------------------------------------------------------


def _check_scope(defn: SettingDef, scope: str, scope_id: str | None) -> str | None:
    if scope not in defn.scopes:
        allowed = ", ".join(defn.scopes)
        raise SettingInvalid(defn.key, f"cannot be set at {scope} scope (allowed: {allowed})")
    if scope == "platform":
        return None
    if scope == "tenant" and registry.settings.tenant_resolver() is None:
        raise SettingInvalid(defn.key, "cannot be set per tenant: no tenancy module is installed")
    if not isinstance(scope_id, str) or not scope_id.strip():
        raise SettingInvalid(defn.key, f"needs the {scope}'s public id at {scope} scope")
    return scope_id.strip()


def _changed(verb: str, actor, **meta) -> None:
    """
    After a write, inside its transaction. The generation is bumped twice: now, so this transaction
    (a request, a data migration, a test) reads its own write rather than a cached old value; and on
    commit, so an old value another process cached in between is never served again. The audit
    entry is written on commit only: a rolled-back change did not happen.
    """
    _bump_generation()
    snapshot = _snapshot.get()
    if snapshot is not None:  # the writer's own request sees its write
        for memo_key in [k for k in snapshot if k[0] == meta["key"]]:
            del snapshot[memo_key]

    def committed():
        _bump_generation()
        log_activity(verb, actor, **meta)

    transaction.on_commit(committed)


def set_value(
    key: str,
    value: Any,
    *,
    scope: str = "platform",
    scope_id: str | None = None,
    actor=None,
    reason: str = "",
    locked: bool | None = None,
) -> Resolved:
    """
    Validate `value` (a JSON value) and store it as the override at `scope`. The one writer: the
    API, the CLI and data migrations all call it. Audited old → new once the transaction commits;
    a write that changes nothing is not a change and is not audited.
    """
    defn = definition(key)
    scope_id = _check_scope(defn, scope, scope_id)
    if locked and scope != "platform":
        raise SettingInvalid(key, "can only be locked at platform scope")
    new = defn.to_json(defn.coerce(value))

    with transaction.atomic():
        row = Setting.objects.select_for_update().for_key(key).at(scope, scope_id).first()
        if row is None:
            try:
                with transaction.atomic():
                    row = Setting.objects.create(
                        key=key,
                        scope_type=scope,
                        scope_id=scope_id,
                        value=stored(new),
                        is_locked=bool(locked),
                        updated_by=actor,
                    )
            except IntegrityError:  # a concurrent first write won the race: update theirs
                row = Setting.objects.select_for_update().for_key(key).at(scope, scope_id).get()
            else:
                _changed(
                    "core.setting.changed",
                    actor,
                    key=key,
                    scope=scope,
                    scope_id=scope_id,
                    old=defn.to_json(defn.default),
                    old_source="default",
                    new=new,
                    locked=row.is_locked,
                    reason=reason,
                )
                return Resolved(key, defn.read(new), scope, row.is_locked)

        try:
            old = unwrap(row.value)
        except ValueError:
            old = row.value  # a row not written by this service: audit what was there
        is_locked = row.is_locked if locked is None else bool(locked)
        if old == new and is_locked == row.is_locked:
            return Resolved(key, defn.read(new), scope, row.is_locked)
        row.value, row.is_locked, row.updated_by = stored(new), is_locked, actor
        row.save(update_fields=["value", "is_locked", "updated_by", "updated_at"])
        _changed(
            "core.setting.changed",
            actor,
            key=key,
            scope=scope,
            scope_id=scope_id,
            old=old,
            old_source=scope,
            new=new,
            locked=is_locked,
            reason=reason,
        )
    return Resolved(key, defn.read(new), scope, is_locked)


def reset(
    key: str, *, scope: str = "platform", scope_id: str | None = None, actor=None, reason: str = ""
) -> bool:
    """Remove the override at `scope`, so the next scope down (or the code default) applies.
    Its own audited action. False when there was nothing to remove."""
    defn = definition(key)
    scope_id = _check_scope(defn, scope, scope_id)
    with transaction.atomic():
        row = Setting.objects.select_for_update().for_key(key).at(scope, scope_id).first()
        if row is None:
            return False
        try:
            old = unwrap(row.value)
        except ValueError:
            old = row.value
        row.delete()
        _changed(
            "core.setting.reset",
            actor,
            key=key,
            scope=scope,
            scope_id=scope_id,
            old=old,
            new=defn.to_json(defn.default),
            reason=reason,
        )
    return True


# --- The settings screen's view ------------------------------------------------------------------


@dataclass(frozen=True)
class Described:
    """A declaration, its platform-level effective value, and the platform row's last change."""

    definition: SettingDef
    resolved: Resolved
    row: Setting | None


def describe(*, module: str | None = None, group: str | None = None) -> list[Described]:
    defs = [
        d
        for d in registry.settings.defs()
        if (module is None or d.module == module) and (group is None or d.group == group)
    ]
    rows = {
        row.key: row
        for row in Setting.objects.filter(
            key__in=[d.key for d in defs], scope_type=Setting.Scope.PLATFORM
        ).select_related("updated_by")
    }
    return [Described(d, resolve_setting(d.key), rows.get(d.key)) for d in defs]


def describe_one(key: str) -> Described:
    defn = definition(key)
    row = (
        Setting.objects.for_key(key)
        .at(Setting.Scope.PLATFORM, None)
        .select_related("updated_by")
        .first()
    )
    return Described(defn, resolve_setting(key), row)


# --- The report (sync_settings) ------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    key: str
    scope: str
    problem: str


def report() -> list[Finding]:
    """
    What is wrong with the stored overrides. Reads only: there is no write path, so running it any
    number of times cannot reset a value (§ 9.2). Orphan rows are kept, never deleted.
    """
    findings = []
    for row in Setting.objects.order_by("key", "scope_type", "scope_id"):
        where = row.scope_type if row.scope_id is None else f"{row.scope_type}:{row.scope_id}"
        try:
            defn = definition(row.key)
        except UnknownSetting:
            findings.append(Finding(row.key, where, "no longer registered (kept, ignored)"))
            continue
        if row.scope_type not in defn.scopes:
            findings.append(Finding(row.key, where, "stored at a scope the setting does not allow"))
        try:
            defn.coerce(unwrap(row.value))
        except ValueError as exc:
            findings.append(Finding(row.key, where, f"value {exc}"))
        except SettingInvalid as exc:
            findings.append(Finding(row.key, where, f"no longer valid: {exc.rule}"))
    return findings
