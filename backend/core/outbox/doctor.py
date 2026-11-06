"""
The outbox doctor (`manage.py doctor --only outbox`): is the outbox actually moving?

It reads the real rows and the real registry: handlers that do not import (the dbx.jobs.E030
check itself), rows nobody can send (an unregistered topic), due rows waiting too long (no worker
on the "outbox" queue), expired leases recovery has not picked up, and the open unknown/failed
findings a human still owes a decision.
"""

from datetime import timedelta

from django.db.models import Count, Min
from django.utils import timezone

from core.registry import ADVISORY, FAILURE, Finding, registry

from .service import FAILED_KIND, UNKNOWN_KIND

STUCK_AFTER = timedelta(minutes=15)  # 30 drainer cycles
RECOVERY_LATE_AFTER = timedelta(minutes=10)  # 5 recovery cycles


def outbox_doctor() -> list[Finding]:
    from core.checks import check_outbox_topics
    from core.models import Finding as OpenFinding
    from core.models import OutboxMessage

    out = [
        Finding(FAILURE, f"outbox.config.{error.id}", "outbox", error.msg, remedy=error.hint or "")
        for error in check_outbox_topics(None)
    ]
    now = timezone.now()
    registered = {spec.topic for spec in registry.outbox_topics.topics()}
    live = OutboxMessage.objects.filter(status__in=("pending", "retry", "leased"))
    for row in live.exclude(topic__in=registered).values("topic").annotate(n=Count("id")):
        out.append(
            Finding(
                FAILURE,
                "outbox.unregistered_topic",
                row["topic"],
                f"{row['n']} messages wait for a topic no module registers",
                remedy="deploy the module that registers it, or resolve the rows by hand",
            )
        )
    due = OutboxMessage.objects.due(now).values("topic").annotate(oldest=Min("next_attempt_at"))
    for row in due:
        if now - row["oldest"] > STUCK_AFTER:
            out.append(
                Finding(
                    FAILURE,
                    "outbox.stuck",
                    row["topic"],
                    f"a message has been due since {row['oldest']:%Y-%m-%d %H:%M} UTC",
                    remedy="start a worker consuming 'outbox' and check core.outbox_drain runs",
                )
            )
    late = OutboxMessage.objects.stale_leases(now - RECOVERY_LATE_AFTER).count()
    if late:
        out.append(
            Finding(
                FAILURE,
                "outbox.recovery_stalled",
                "core.outbox_recover",
                f"{late} expired leases have not been recovered",
                remedy="check that core.outbox_recover is scheduled and its worker is running",
            )
        )
    for kind in (UNKNOWN_KIND, FAILED_KIND):
        count = OpenFinding.objects.open().filter(kind=kind).count()
        if count:
            out.append(
                Finding(
                    ADVISORY,
                    kind,
                    "outbox",
                    f"{count} open {kind} findings await a human decision",
                    remedy="mark each sent or resend it (core.outbox.service.resolve_unknown)"
                    if kind == UNKNOWN_KIND
                    else "fix the cause, then resend or dismiss each",
                )
            )
    return out
