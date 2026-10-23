"""
The audit trail (DATA_LIFECYCLE.md § 4; AUTH_BLUEPRINT § 3.12; BUILD 6.4).

ONE writer — record() — and nothing else inserts into core_activity_log (a source scan proves it):

    record("rbac.role.updated", target=role, changes=changes, meta={...})

- It NEVER raises: an audit failure must not break the action it observes. It writes inside its own
  savepoint (a bare try/except around an insert would leave the outer transaction unusable), logs a
  scrubbed `core.audit.write_failed` and counts the failure.
- Transactional by default: a rolled-back change leaves no row claiming it happened.
  independent=True asks for a separate connection (DATABASES["audit"]) so security rows survive a
  rollback; with no such alias — SQLite development, by default — it DEGRADES to transactional
  with a logged warning.
- meta and changes are masked at any depth by the one shared scrubber (core.observability.scrub).

log_activity(verb, actor, target, **meta) is the call shape every caller already uses, and it stays
byte-compatible: it is a thin wrapper over record().

Provenance is INFERRED today, not bound — the § 2 ActorContext binder does not exist yet:
  * a request id in core.observability.request_id ⇒ source "web", via "api" (the API is the only
    web surface), with method/path/ip from the request middleware's contextvars when present;
  * no request id and `manage.py` in argv ⇒ source "command", with the OS user, host and SCRUBBED
    argv — a change made from a shell is attributable to a person on a machine;
  * otherwise ⇒ source "system".
When ActorContext lands (7.x), replace _provenance() with a read of it; callers need not change.
"""

import contextvars
import getpass
import logging
import socket
import sys
import uuid
from collections import Counter
from contextlib import contextmanager
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connections, router, transaction

from core.audit_diff import MASK, diff_values, is_secret_key, jsonable
from core.models import ActivityLog
from core.observability import request_id
from core.observability.scrub import default_rules, scrub
from core.registry import registry

logger = logging.getLogger("core.audit")

AUDIT_ALIAS = "audit"

# The verb's channel when it is unregistered: its first segment, which is the module that owns it.
_BATCH: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "core_audit_batch", default=None
)
_COUNTS: contextvars.ContextVar[Counter | None] = contextvars.ContextVar(
    "core_audit_counts", default=None
)

write_failures = 0  # audit_write_failures_total until a metrics facility exists (TECH_DEBT)


# --- Provenance ---------------------------------------------------------------------------------


def _scrub_argv(argv: list[str]) -> str:
    """argv as one line with secrets removed: `--password hunter2` must never land in the log."""
    rules = default_rules()
    out, hide_next = [], False
    for arg in argv:
        if hide_next:
            out.append(MASK)
            hide_next = False
            continue
        if arg.startswith("--") and "=" in arg:
            name, _, value = arg.partition("=")
            out.append(
                f"{name}={MASK}" if is_secret_key(name.lstrip("-").replace("-", "_")) else arg
            )
            continue
        if arg.startswith("--") and is_secret_key(arg.lstrip("-").replace("-", "_")):
            out.append(arg)
            hide_next = True
            continue
        out.append(rules.scrub_text(arg))
    return " ".join(out)[:500]


def _provenance() -> dict[str, Any]:
    rid = request_id.current()
    if rid and rid != "-":
        return {"source": "web", "via": "api", "request_id": rid}
    argv = sys.argv
    if argv and argv[0].endswith("manage.py"):
        try:
            user = getpass.getuser()
        except Exception:  # noqa: BLE001 — no passwd entry (a bare container) is not an audit failure
            user = ""
        return {
            "source": "command",
            "origin_os_user": user[:64],
            "origin_host": socket.gethostname()[:255],
            "origin_command": _scrub_argv(argv),
        }
    return {"source": "system"}


# --- The one writer -----------------------------------------------------------------------------


def _label(action: str) -> tuple[str, str]:
    """(description fallback, channel) from the registry, else derived from the key."""
    entry = registry.audit_actions.get(action)
    if entry is not None:
        return entry.label, entry.channel
    logger.debug("core.audit.unregistered_action", extra={"audit_action": action})
    return action.replace(".", " ").replace("_", " ").capitalize(), action.split(".", 1)[0]


def _safe_changes(changes: dict) -> dict:
    """
    Mask `changes` at any depth. The shared scrubber redacts a whole value under a sensitive KEY,
    which would flatten a {"old","new","secret"} entry to "[Filtered]" and lose the fact that the
    field changed — so a secret-named field is masked here in the diff's own shape, and the
    scrubber runs over each entry's VALUES (old/new/labels) for secrets hiding inside ordinary ones.
    """
    out = {}
    for field, entry in jsonable(changes).items():
        if is_secret_key(field.rsplit(".", 1)[-1]) or (
            isinstance(entry, dict) and entry.get("secret")
        ):
            out[field] = {"old": MASK, "new": MASK, "secret": True}
        elif isinstance(entry, dict):
            out[field] = {k: scrub(v) if k in {"old", "new"} else v for k, v in entry.items()}
        else:
            out[field] = scrub(entry)
    return out


def _actor_fields(actor) -> dict[str, Any]:
    if actor is None:
        return {}
    public_id = getattr(actor, "public_id", None)
    return {
        "actor_id": str(public_id) if public_id is not None else str(getattr(actor, "pk", "")),
        "actor_kind": "user",
        "actor_label": str(getattr(actor, "email", "") or actor)[:255],
    }


def _target_fields(target) -> dict[str, Any]:
    if target is None:
        return {}
    meta = getattr(target, "_meta", None)
    ident = getattr(target, "public_id", None) or getattr(target, "pk", "")
    return {
        "target_type": meta.label_lower if meta is not None else type(target).__name__.lower(),
        "target_id": str(ident),
        "target_repr": str(target)[:255],
    }


def record(
    action: str,
    target=None,
    *,
    actor=None,
    changes: dict | None = None,
    meta: dict | None = None,
    description: str | None = None,
    event: str = "custom",
    batch_id: uuid.UUID | None = None,
    independent: bool = False,
) -> ActivityLog | None:
    """Write one evidence row. Never raises; returns the row, or None if it could not be written."""
    global write_failures  # noqa: PLW0603
    try:
        label, channel = _label(action)
        fields: dict[str, Any] = {
            "action": action[:64],
            "channel": channel[:32],
            "event": event,
            "description": (description or label)[:255],
            "changes": _safe_changes(changes or {}),
            "meta": scrub(jsonable(meta or {})),
            "batch_id": batch_id or _BATCH.get(),
            **_provenance(),
            **_actor_fields(actor),
            **_target_fields(target),
        }
        alias = _alias_for(independent)
        with transaction.atomic(using=alias):  # its own savepoint: a failed insert stays local
            row = ActivityLog(**fields)
            row.save(using=alias)
        counts = _COUNTS.get()
        if counts is not None:
            counts[event] += 1
        return row
    except Exception:  # noqa: BLE001 — an audit failure must not break the action it observes
        write_failures += 1
        logger.warning(
            "core.audit.write_failed", extra={"audit_action": action, "failures": write_failures}
        )
        return None


def _alias_for(independent: bool) -> str:
    if not independent:
        return router.db_for_write(ActivityLog)
    if AUDIT_ALIAS in connections.databases:
        return AUDIT_ALIAS
    logger.warning("core.audit.independent_degraded", extra={"reason": "no DATABASES['audit']"})
    return router.db_for_write(ActivityLog)


@contextmanager
def batch(batch_id: uuid.UUID | None = None):
    """One bulk action, one import, one command run: every row inside shares a batch id."""
    token = _BATCH.set(batch_id or uuid.uuid4())
    try:
        yield _BATCH.get()
    finally:
        _BATCH.reset(token)


# --- The call shape every existing caller uses ---------------------------------------------------


def log_activity(verb: str, actor=None, target=None, **meta) -> None:
    """
    The one call-site shape (AUTH_BLUEPRINT § 3.12), byte-compatible with the logger-only version
    it replaced: ~40 call sites pass (verb, actor, target, **meta) and now produce rows. Old/new
    pairs that callers put in meta stay in meta.
    """
    record(verb, target, actor=actor, meta=meta)


# --- Automatic capture (opt-in by inheriting AuditedModel) ---------------------------------------


class AuditedModelMixin:
    """
    Opt-in model-change capture (§ 4.3): `class Contact(AuditedModelMixin, models.Model)`. Snapshot
    on load, diff on save, no extra query; deferred fields are skipped. Refine with an inner
    AuditMeta: fields · exclude · secret_fields · preference_fields · state_fields · title_field.
    """

    class AuditMeta:
        fields: tuple[str, ...] | None = None
        exclude: tuple[str, ...] = ()
        secret_fields: tuple[str, ...] = ()
        preference_fields: tuple[str, ...] = ()
        state_fields: tuple[str, ...] = ("status", "state", "is_active")
        title_field: str | None = None

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._audit_snapshot = instance._audit_values()
        return instance

    def _audit_meta(self):
        """The model's AuditMeta overlaid on the defaults, so an AuditMeta may set only what it
        refines (a plain inner class does not inherit AuditedModelMixin.AuditMeta)."""
        defaults = {
            name: getattr(AuditedModelMixin.AuditMeta, name)
            for name in vars(AuditedModelMixin.AuditMeta)
            if not name.startswith("_")
        }
        overrides = {n: v for n, v in vars(self.AuditMeta).items() if not n.startswith("_")}
        return type("AuditMeta", (), {**defaults, **overrides})

    def _audit_values(self) -> dict[str, Any]:
        meta, out = self._audit_meta(), {}
        deferred = self.get_deferred_fields()
        for field in self._meta.concrete_fields:
            name = field.name
            if field.attname in deferred or name in meta.exclude:
                continue
            if meta.fields is not None and name not in meta.fields:
                continue
            out[name] = getattr(self, field.attname)  # the raw value: FK id, never a query
        return out

    def _audit_describe(self, name: str, value):
        field = self._meta.get_field(name)
        if field.choices:
            labels = dict(field.flatchoices)
            return value, str(labels.get(value, value))
        if field.is_relation and value is not None:
            related = field.related_model._default_manager.filter(pk=value).first()
            return value, str(related) if related is not None else None
        return value, None

    def save(self, *args, **kwargs):
        adding = self._state.adding
        before = getattr(self, "_audit_snapshot", None)
        super().save(*args, **kwargs)
        meta = self._audit_meta()
        after = self._audit_values()
        if adding:
            record(
                f"{self._meta.app_label}.{self._meta.model_name}.created",
                self,
                event="created",
                description=f"{self._audit_title()} — created",
            )
        elif before is not None:
            changes, event = diff_values(
                before,
                after,
                describe=self._audit_describe,
                secret_fields=meta.secret_fields,
                preference_fields=meta.preference_fields,
                state_fields=meta.state_fields,
            )
            if changes:  # nothing non-noisy changed ⇒ no row at all (§ 4.3, § 4.8)
                record(
                    f"{self._meta.app_label}.{self._meta.model_name}.updated",
                    self,
                    changes=changes,
                    event=event,
                    description=f"{self._audit_title()} — {event.replace('_', ' ')}",
                )
        self._audit_snapshot = after

    def delete(self, *args, **kwargs):
        title = self._audit_title()
        label = self._meta.label_lower
        result = super().delete(*args, **kwargs)
        record(f"{label}.deleted", event="deleted", description=f"{title} — deleted")
        return result

    def _audit_title(self) -> str:
        field = self._audit_meta().title_field
        return str(getattr(self, field)) if field else str(self)


# --- Commands: one run → one feed row, only if something happened --------------------------------


class AuditedCommand(BaseCommand):
    """
    Wraps handle() (§ 4.8): rows written during the run share a batch id, and ONE run_summary row
    is added afterwards — only if something was recorded. "Nothing happened → nothing recorded."
    Subclass and implement handle() as normal.
    """

    audit_action = "core.command.ran"

    def execute(self, *args, **options):
        counts = Counter()
        counts_token = _COUNTS.set(counts)
        with batch() as batch_id:
            try:
                return super().execute(*args, **options)
            finally:
                _COUNTS.reset(counts_token)
                if counts:
                    summary = ", ".join(f"{n} {event}" for event, n in sorted(counts.items()))
                    record(
                        self.audit_action,
                        event="run_summary",
                        description=f"{type(self).__module__.rsplit('.', 1)[-1]} ran: {summary}",
                        meta={"counts": dict(counts)},
                        batch_id=batch_id,
                    )


__all__ = [
    "ActivityLog",
    "AuditedCommand",
    "AuditedModelMixin",
    "batch",
    "log_activity",
    "record",
]
