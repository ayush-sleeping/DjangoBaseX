"""
Field-level diffs for the audit trail (DATA_LIFECYCLE.md § 4.3). Pure functions over plain values
plus the model's field metadata: no database, no writes.

    {field: {"old": …, "new": …, "old_label": …, "new_label": …}}

- A foreign key records the id AND str(related); a choice field the value AND its label.
- Dates and datetimes are ISO-8601 (UTC for instants) and formatted by the VIEWER at read time,
  never baked into the log.
- A JSONField is diffed per key, recursively, with scalar coercion so "16384" → 16384 records
  nothing; one changed key is one entry, not "settings: {…} → {…}".
- Secrets are masked at ANY depth — one scrubber (core.observability.scrub), plus a registered
  *_ciphertext column and the model's AuditMeta.secret_fields. The entry records THAT the field
  changed, both values as MASK.
- Noisy fields (updated_at, version, last_seen_at, …) are skipped; a change set that is only noise
  or preference fields writes no row at all.
- Long values truncate at AUDIT_DIFF_VALUE_MAX with an explicit "truncated" marker, never silently.
"""

import datetime as dt
import decimal
import uuid
from typing import Any

from django.conf import settings

from core.observability.scrub import default_rules, normalise_key

MASK = "*****"
NOISY_FIELDS = frozenset({"updated_at", "created_at", "modified_at", "version", "last_seen_at"})
NOISY_SUFFIXES = ("_last_sync", "_search_vector")
DEFAULT_STATE_FIELDS = ("status", "state", "is_active")
DEFAULT_VALUE_MAX = 1000


def value_max() -> int:
    return int(getattr(settings, "AUDIT_DIFF_VALUE_MAX", DEFAULT_VALUE_MAX))


def is_noisy(name: str) -> bool:
    return name in NOISY_FIELDS or name.endswith(NOISY_SUFFIXES)


def is_secret_key(name: str, secret_fields=()) -> bool:
    if name in secret_fields or name.endswith("_ciphertext"):
        return True
    key = normalise_key(name)
    rules = default_rules()
    compact = key.replace("_", "")
    return (
        key in rules.keys
        or compact in rules._compact
        or key.endswith(("_token", "_secret", "_password", "_key", "_ciphertext"))
    )


def jsonable(value: Any) -> Any:
    """Machine values only: ISO-8601 for dates and instants, strings for UUID and Decimal."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.UTC)
        return value.isoformat()
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, uuid.UUID | decimal.Decimal):
        return str(value)
    if isinstance(value, set | frozenset):
        return sorted(jsonable(v) for v in value)
    if isinstance(value, tuple | list):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    return value


def _coerce(value: Any) -> Any:
    """Scalar coercion for comparison: "16384" equals 16384, and "true" equals True."""
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in {"true", "false"}:
            return text.lower() == "true"
        try:
            return int(text)
        except ValueError:
            try:
                return float(text) if "." in text else value
            except ValueError:
                return value
    return value


def truncate(value: Any) -> tuple[Any, bool]:
    limit = value_max()
    if isinstance(value, str) and len(value) > limit:
        return value[:limit], True
    return value, False


def _entry(old: Any, new: Any, *, labels=None, secret=False) -> dict:
    if secret:
        return {"old": MASK, "new": MASK, "secret": True}
    entry: dict[str, Any] = {}
    truncated = False
    for name, value in (("old", old), ("new", new)):
        entry[name], cut = truncate(value)
        truncated = truncated or cut
    if labels:
        entry["old_label"], entry["new_label"] = labels
    if truncated:
        entry["truncated"] = True
    return entry


def diff_json(old: Any, new: Any, *, prefix: str, secret_fields=(), under_secret=False) -> dict:
    """Per-key, recursive. Keys are dotted paths under the field: "config.retention.days"."""
    out: dict[str, dict] = {}
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted({*old, *new}, key=str):
            path = f"{prefix}.{key}"
            secret = under_secret or is_secret_key(str(key), secret_fields)
            o, n = old.get(key), new.get(key)
            if isinstance(o, dict) and isinstance(n, dict):
                out |= diff_json(
                    o, n, prefix=path, secret_fields=secret_fields, under_secret=secret
                )
            elif key not in old or key not in new or _coerce(o) != _coerce(n):
                out[path] = _entry(jsonable(o), jsonable(n), secret=secret)
        return out
    if _coerce(old) != _coerce(new):
        out[prefix] = _entry(jsonable(old), jsonable(new), secret=under_secret)
    return out


def diff_values(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    describe=None,
    secret_fields=(),
    preference_fields=(),
    state_fields=DEFAULT_STATE_FIELDS,
) -> tuple[dict, str]:
    """
    (changes, event) for two {field: value} snapshots. `describe(field, value)` returns
    (display, label-or-None) for FKs and choices. `changes` is empty when nothing non-noisy
    changed — the caller then writes NO row. `event` is "status_changed" when every changed field
    is a state field, else "updated".
    """
    changes: dict[str, dict] = {}
    for name in sorted(set(before) | set(after)):
        if is_noisy(name) or name in preference_fields:
            continue
        old, new = before.get(name), after.get(name)
        secret = is_secret_key(name, secret_fields)
        if isinstance(old, dict) and isinstance(new, dict):
            changes |= diff_json(
                old, new, prefix=name, secret_fields=secret_fields, under_secret=secret
            )
            continue
        if secret:
            if old != new:
                changes[name] = _entry(None, None, secret=True)
            continue
        if _coerce(old) == _coerce(new):
            continue
        labels = None
        if describe is not None:
            (old, old_label), (new, new_label) = describe(name, old), describe(name, new)
            if old_label is not None or new_label is not None:
                labels = (old_label, new_label)
        changes[name] = _entry(jsonable(old), jsonable(new), labels=labels)
    event = "updated"
    if changes and all(name.split(".", 1)[0] in state_fields for name in changes):
        event = "status_changed"
    return changes, event
