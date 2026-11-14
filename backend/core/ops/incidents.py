"""
Incidents (§ 17): announce a problem once when it opens, once when it recovers, nothing in between.

A monitor passes the COMPLETE set of current problems on every successful run:
new keys open, absent keys recover, present keys are touched. A problem that clears inside
`confirm_after_minutes` is never announced (flap suppression); a recovery is announced only if the
opening was, so an unannounced flap leaves no lonely "recovered". A re-opening that the dispatcher
absorbs (cooldown) is retried on later runs until it is announced or clears. A monitor that
crashed must not call sync(): that would recover everything (its failure is the monitor's own
alert, § 19).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import Incident

from . import dispatcher
from .kinds import SKIP_ALREADY_HELD, Problem

Status = Incident.Status
ANNOUNCED = ("sent", "held")


@dataclass(frozen=True)
class SyncResult:
    opened: int = 0
    announced: int = 0
    recovered: int = 0


def subject_key(source: str, key: str) -> str:
    return f"incident:{source}:{key}"


def _announce(incident: Incident, now: datetime) -> bool:
    outcome = dispatcher.alert(
        subject_key(incident.source, incident.key),
        source=incident.source,
        reason=incident.key[:100],
        title=f"Incident: {incident.label}",
        body=incident.details.get("body", ""),
        kind=incident.kind,
    )
    if outcome.decision in ANNOUNCED or outcome.reason == SKIP_ALREADY_HELD:
        Incident.objects.filter(pk=incident.pk).update(announced_at=now)
        return True
    return False


def _open(source: str, key: str, problem: Problem, now: datetime) -> Incident:
    values = {
        "label": problem.label[:300],
        "kind": str(problem.kind),
        "details": {"body": problem.body},
    }
    try:
        with transaction.atomic():
            return Incident.objects.create(
                source=source, key=key, first_seen_at=now, last_seen_at=now, **values
            )
    except IntegrityError:  # another run opened it between our read and our write: touch theirs
        Incident.objects.filter(source=source, key=key).exclude(status=Status.RECOVERED).update(
            last_seen_at=now
        )
        return Incident.objects.exclude(status=Status.RECOVERED).get(source=source, key=key)


def sync(
    source: str,
    problems: Mapping[str, Problem | str],
    *,
    confirm_after_minutes: int = 0,
    now: datetime | None = None,
) -> SyncResult:
    now = now or timezone.now()
    wanted = {k: p if isinstance(p, Problem) else Problem(str(p)) for k, p in problems.items()}
    live = {i.key: i for i in Incident.objects.filter(source=source).exclude(status="recovered")}
    opened = announced = recovered = 0
    for key, problem in wanted.items():
        incident = live.get(key)
        if incident is None:
            incident = _open(source, key, problem, now)
            opened += 1
        else:
            Incident.objects.filter(pk=incident.pk).update(
                last_seen_at=now, label=problem.label[:300]
            )
        if incident.status == Status.PENDING and now - incident.first_seen_at >= timedelta(
            minutes=confirm_after_minutes
        ):
            Incident.objects.filter(pk=incident.pk).update(status=Status.OPEN, confirmed_at=now)
            incident.status = Status.OPEN
        if incident.status == Status.OPEN and incident.announced_at is None:
            announced += _announce(incident, now)
    for key, incident in live.items():
        if key in wanted:
            continue
        if incident.announced_at is not None:
            dispatcher.alert(
                subject_key(source, key),
                source=source,
                reason=key[:100],
                title=f"Recovered: {incident.label}",
                body="The condition has cleared.",
                kind=incident.kind,
                event="recovered",
            )
        Incident.objects.filter(pk=incident.pk).update(status=Status.RECOVERED, recovered_at=now)
        recovered += 1
    return SyncResult(opened=opened, announced=announced, recovered=recovered)
