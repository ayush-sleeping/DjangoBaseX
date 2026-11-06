"""
The open-findings queue (DOMAIN_PRIMITIVES.md § 8): where anything a machine noticed and a HUMAN
must decide lands. Reconciler give-ups, ambiguous (`unknown`) outbox sends, dead letters.

- One OPEN row per (kind, object), enforced by the partial unique index core_finding_open_uq. A
  re-detection touches it (last_seen_at, occurrences, details) instead of inserting.
- Resolved rows are history. A recurrence after resolution opens a new row.
- The detector calls clear() when the condition is gone (resolution "auto_cleared").
- Kinds are registered (registry.finding_kinds). An unregistered kind is refused at write.

Writes run in the caller's transaction on purpose: a finding about a row is committed with the
state change that produced it, or not at all.
"""

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from core.registry import AUTO_CLEARED, registry


class UnknownFindingKind(LookupError):
    """A finding of a kind nobody registered. A programming error, refused at write."""


def _kind(kind: str, kinds=None):
    kinds = registry.finding_kinds if kinds is None else kinds
    if kind not in kinds:
        raise UnknownFindingKind(
            f"finding kind {kind!r} is not registered (registry.finding_kinds)"
        )
    return kinds.get(kind)


def subject(obj=None, *, object_type: str | None = None, object_id=None) -> tuple[str, str]:
    """(object_type, object_id) for a model instance, or as given."""
    if obj is not None:
        return obj._meta.label_lower, str(obj.pk)
    if not object_type or object_id in (None, ""):
        raise ValueError("a finding is about something: pass obj, or object_type and object_id")
    return object_type, str(object_id)


def _model():
    from core.models import Finding

    return Finding


def raise_or_touch(
    kind: str,
    obj=None,
    *,
    object_type: str | None = None,
    object_id=None,
    title: str = "",
    details: dict | None = None,
    kinds=None,
):
    """Open a finding, or touch the open one for the same (kind, object). Returns the row."""
    spec = _kind(kind, kinds)
    object_type, object_id = subject(obj, object_type=object_type, object_id=object_id)
    Finding, now = _model(), timezone.now()
    open_rows = Finding.objects.open().of(kind, object_type, object_id)
    values = {"last_seen_at": now, "occurrences": F("occurrences") + 1}
    if details is not None:
        values["details"] = details
    if title:
        values["title"] = title[:255]
    if open_rows.update(**values):
        return open_rows.get()
    try:
        with transaction.atomic():
            return Finding.objects.create(
                kind=kind,
                object_type=object_type,
                object_id=object_id,
                title=(title or spec.label)[:255],
                details=details or {},
                severity=spec.severity,
                first_seen_at=now,
                last_seen_at=now,
            )
    except IntegrityError:
        # Another detector opened it between our update and our insert: touch theirs.
        open_rows.update(**values)
        return open_rows.get()


def clear(kind: str, obj=None, *, object_type=None, object_id=None, kinds=None) -> int:
    """The condition is gone: auto-resolve the open finding, if any. Returns how many closed."""
    _kind(kind, kinds)
    object_type, object_id = subject(obj, object_type=object_type, object_id=object_id)
    return (
        _model()
        .objects.open()
        .of(kind, object_type, object_id)
        .update(resolved_at=timezone.now(), resolution=AUTO_CLEARED, resolved_by=None)
    )


def resolve(finding, resolution: str, note: str = "", actor=None, *, kinds=None) -> bool:
    """A human's decision. `resolution` must be one the kind allows. False if already resolved."""
    spec = _kind(finding.kind, kinds)
    if resolution not in spec.resolutions:
        raise ValueError(
            f"{resolution!r} is not a resolution of {finding.kind!r}: one of {spec.resolutions}"
        )
    now = timezone.now()
    done = (
        _model()
        .objects.open()
        .filter(pk=finding.pk)
        .update(resolved_at=now, resolution=resolution, resolution_note=note, resolved_by=actor)
    )
    if done:
        finding.refresh_from_db()
    return bool(done)
