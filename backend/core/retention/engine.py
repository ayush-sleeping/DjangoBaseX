"""
The retention engine (DATA_LIFECYCLE.md § 6.2): one place that deletes by registered policy.

Every caller (the daily job, `manage.py retention`, `users.auth_cleanup`) goes through run() and
status(). Both resolve the window through cutoff_for(), the ONE cutoff helper, so what --dry-run and
--status report is exactly what the real run then deletes.

Deletes are plain QuerySet deletes by primary key, batched, each batch its own transaction. A plain
QuerySet on purpose: ActivityLog's manager refuses delete(), and the engine is the one caller
allowed past that (on PostgreSQL by the session flag the table's trigger checks). The fast path
holds only while no model has delete receivers; tests/core/test_retention.py asserts none do.
"""

import logging
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.apps import apps
from django.db import connection, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from core import audit
from core.registry import RetentionPolicy, registry
from core.settings_service import get_setting

logger = logging.getLogger("core.retention")

AUDIT_ACTION = "core.retention.purged"

# Result states.
RAN, DRY_RUN, DISABLED, OPT_IN, MISSING = "ran", "dry_run", "disabled", "opt_in", "missing"


class UnknownPolicy(KeyError):
    """A policy key nobody registered."""


@dataclass(frozen=True)
class PolicyResult:
    key: str
    state: str
    cutoff: datetime | None = None
    eligible: int = 0  # what a run would delete now (counted, never deleted)
    deleted: int = 0
    truncated: bool = False  # max_batches ran out with rows still eligible


@dataclass(frozen=True)
class PolicyStatus:
    key: str
    state: str  # "active" | DISABLED | OPT_IN | MISSING
    cutoff: datetime | None = None
    rows: int = 0
    oldest: datetime | None = None
    eligible: int = 0
    max_rows: int | None = None
    would_truncate: bool = False  # eligible exceeds one run's batch_size * max_batches
    window_days: int | None = None


def cutoff_for(policy: RetentionPolicy, now: datetime) -> datetime | None:
    """
    The age boundary for `policy` at `now`, or None when the window is empty (keep forever). The
    stored value is clamped to the floor with a warning: the settings service already clamps what
    it reads, and this stays correct if a raw value ever gets past it. 0 can never mean "delete
    everything".
    """
    days = get_setting(policy.days_setting)
    if days is None:
        return None
    if not isinstance(days, int) or isinstance(days, bool) or days < policy.min_age_days:
        logger.warning(
            "core.retention.window_clamped",
            extra={"policy": policy.key, "value": str(days), "floor": policy.min_age_days},
        )
        days = policy.min_age_days
    return now - timedelta(days=days)


def _model(policy: RetentionPolicy, tables: set[str]):
    """The model, or None when its app is not installed or its table is not migrated yet."""
    try:
        model = apps.get_model(policy.model)
    except (LookupError, ValueError):
        return None
    return model if model._meta.db_table in tables else None


def _population(policy: RetentionPolicy, model, now: datetime) -> QuerySet:
    queryset = QuerySet(model=model)
    narrowing = policy.filter(now) if callable(policy.filter) else policy.filter
    return queryset if narrowing is None else queryset.filter(narrowing)


def _age_q(policy: RetentionPolicy, cutoff: datetime, now: datetime) -> Q:
    if policy.age_q is not None:
        return policy.age_q(cutoff, now)
    return Q(**{f"{policy.timestamp_field}__lt": cutoff})


def _surviving(policy: RetentionPolicy, model, cutoff: datetime, now: datetime) -> QuerySet:
    """What the age cut leaves: the population the row cap applies to."""
    return _population(policy, model, now).exclude(_age_q(policy, cutoff, now))


def _age_pks(policy, model, cutoff, now) -> QuerySet:
    return _population(policy, model, now).filter(_age_q(policy, cutoff, now))


def _cap_pks(policy: RetentionPolicy, model, cutoff, now) -> QuerySet:
    """Beyond the newest `max_rows`, ordered (timestamp DESC, pk DESC): the pk tiebreak is what
    stops a row of equal timestamp flipping in and out of the keep-window between batches."""
    ordered = _surviving(policy, model, cutoff, now).order_by(f"-{policy.timestamp_field}", "-pk")
    return ordered.values_list("pk", flat=True)


def _measure(policy: RetentionPolicy, model, cutoff: datetime, now: datetime) -> tuple[int, int]:
    """(age-eligible rows, rows over the cap): the one count --dry-run and --status share."""
    aged = _age_pks(policy, model, cutoff, now).count()
    if policy.max_rows is None:
        return aged, 0
    return aged, max(0, _surviving(policy, model, cutoff, now).count() - policy.max_rows)


def _delete_batch(model, pks: list) -> int:
    with transaction.atomic():
        if connection.vendor == "postgresql":
            # The audit table's trigger refuses DELETE outside this flag (migration 0004).
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL core.retention_purge = 'on'")
        _, per_model = QuerySet(model=model).filter(pk__in=pks).delete()
    return per_model.get(model._meta.label, 0)


def _sweep(policy: RetentionPolicy, model, next_pks, budget: int) -> tuple[int, int, bool]:
    """Delete in batches until `next_pks()` is empty or `budget` batches are used.
    Returns (deleted, batches used, finished)."""
    deleted = used = 0
    while used < budget:
        pks = list(next_pks()[: policy.batch_size])
        if not pks:
            return deleted, used, True
        removed = _delete_batch(model, pks)
        used += 1
        deleted += removed
        if removed == 0:  # someone else deleted them first; never spin
            return deleted, used, True
    return deleted, used, not next_pks().exists()


def _policies(only: Collection[str] | None, owner: str | None) -> list[RetentionPolicy]:
    chosen = list(registry.retention.policies())
    if only is not None:
        unknown = sorted(set(only) - {p.key for p in chosen})
        if unknown:
            raise UnknownPolicy(", ".join(unknown))
        chosen = [p for p in chosen if p.key in only]
    if owner is not None:
        chosen = [p for p in chosen if p.owner_module == owner]
    return chosen


def _opt_in_allowed(policy: RetentionPolicy, *, scheduled: bool, include_opt_in: bool) -> bool:
    if not policy.requires_opt_in or include_opt_in:
        return True
    return scheduled and get_setting(policy.enabled_setting) is True


def run(
    *,
    only: Collection[str] | None = None,
    owner: str | None = None,
    dry_run: bool = False,
    include_opt_in: bool = False,
    scheduled: bool = False,
    now: datetime | None = None,
) -> list[PolicyResult]:
    """
    Apply the policies. `scheduled=True` (the jobs) honours each opt-in policy's `.enabled`
    setting; otherwise an opt-in policy runs only with `include_opt_in`. `dry_run` counts and
    deletes nothing. One summary audit row per policy, only if rows were removed.
    """
    now = now or timezone.now()
    tables = set(connection.introspection.table_names())
    results = []
    for policy in _policies(only, owner):
        model = _model(policy, tables)
        if model is None:
            results.append(PolicyResult(policy.key, MISSING))
        elif not _opt_in_allowed(policy, scheduled=scheduled, include_opt_in=include_opt_in):
            results.append(PolicyResult(policy.key, OPT_IN))
        elif (cutoff := cutoff_for(policy, now)) is None:
            results.append(PolicyResult(policy.key, DISABLED))
        elif dry_run:
            aged, over = _measure(policy, model, cutoff, now)
            results.append(PolicyResult(policy.key, DRY_RUN, cutoff, eligible=aged + over))
        else:
            results.append(_apply(policy, model, cutoff, now))
    return results


def _apply(policy: RetentionPolicy, model, cutoff: datetime, now: datetime) -> PolicyResult:
    deleted, used, finished = _sweep(
        policy,
        model,
        lambda: _age_pks(policy, model, cutoff, now).order_by("pk").values_list("pk", flat=True),
        policy.max_batches,
    )
    if finished and policy.max_rows is not None:
        # The cap's keep-window never moves while rows beyond it are deleted, so a fresh slice
        # past `max_rows` each batch is exactly "everything beyond the newest max_rows".
        more, _, finished = _sweep(
            policy,
            model,
            lambda: _cap_pks(policy, model, cutoff, now)[policy.max_rows :],
            policy.max_batches - used,
        )
        deleted += more
    if deleted:
        audit.record(
            AUDIT_ACTION,
            description=f"Retention removed {deleted} rows from {policy.key}",
            meta={
                "policy": policy.key,
                "model": policy.model,
                "data_class": policy.data_class,
                "deleted": deleted,
                "cutoff": cutoff.isoformat(),
                "truncated": not finished,
            },
        )
    return PolicyResult(policy.key, RAN, cutoff, deleted=deleted, truncated=not finished)


def status(
    *, only: Collection[str] | None = None, now: datetime | None = None
) -> list[PolicyStatus]:
    """Read-only: per policy, rows, oldest, cutoff and what the next run would delete."""
    now = now or timezone.now()
    tables = set(connection.introspection.table_names())
    out = []
    for policy in _policies(only, None):
        model = _model(policy, tables)
        if model is None:
            out.append(PolicyStatus(policy.key, MISSING, max_rows=policy.max_rows))
            continue
        population = _population(policy, model, now)
        rows = population.count()
        oldest = (
            population.order_by(policy.timestamp_field)
            .values_list(policy.timestamp_field, flat=True)
            .first()
        )
        cutoff = cutoff_for(policy, now)
        state = "active"
        eligible = 0
        if cutoff is None:
            state = DISABLED
        else:
            aged, over = _measure(policy, model, cutoff, now)
            eligible = aged + over
        if state == "active" and policy.requires_opt_in:
            state = OPT_IN if get_setting(policy.enabled_setting) is not True else "active"
        out.append(
            PolicyStatus(
                key=policy.key,
                state=state,
                cutoff=cutoff,
                rows=rows,
                oldest=oldest,
                eligible=eligible,
                max_rows=policy.max_rows,
                would_truncate=eligible > policy.batch_size * policy.max_batches,
                window_days=None if cutoff is None else (now - cutoff).days,
            )
        )
    return out
