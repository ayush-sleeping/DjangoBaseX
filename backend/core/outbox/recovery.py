"""
core.outbox_recover: the stale-lease sweep (JOBS_AND_INTEGRATIONS.md § 12), a Reconciler.

A `leased` row whose lease expired belongs to a drainer that died or hung mid-send. Whether the
provider got the message is unknowable from here, so the topic's declared semantics decide:
at_most_once → `unknown` plus an outbox.unknown finding (a duplicate is worse than a gap; a human
marks it sent or resends it); at_least_once → `retry` with backoff (the receiver dedupes), or
`failed` when its attempts are spent. A row of a topic no longer registered is treated as
at_most_once: fail closed. The row keeps `locked_by`, so the dead drainer's late SENT, if it ever
arrives, can still settle it (core.outbox.service.settle).
"""

from datetime import timedelta

from django.utils import timezone

from core import findings
from core.jobs.reconciler import Reconciler, Result
from core.registry import AT_LEAST_ONCE, registry

from .service import FAILED_KIND, OBJECT_TYPE, UNKNOWN_KIND, next_delay

LEASE_EXPIRED = "lease_expired"


class LeaseRecovery(Reconciler):
    name = "core.outbox_recover"
    batch_size = 500

    def __init__(self, topics=None) -> None:
        self.topics = registry.outbox_topics if topics is None else topics

    def queryset(self):
        from core.models import OutboxMessage

        return OutboxMessage.objects.stale_leases(timezone.now())

    def reconcile(self, row) -> Result:
        now = timezone.now()
        spec = self.topics.get(row.topic) if row.topic in self.topics else None
        evidence = {
            "attempt": row.attempts,
            "locked_by": row.locked_by,
            "leased_until": row.leased_until.isoformat() if row.leased_until else None,
        }
        row.last_error_code, row.last_error_message = LEASE_EXPIRED, ""
        row.leased_until = None
        if spec is not None and spec.semantics == AT_LEAST_ONCE:
            delay = next_delay(spec, row.attempts, row.max_attempts)
            if delay is None:
                row.status = "failed"
                findings.raise_or_touch(
                    FAILED_KIND, object_type=OBJECT_TYPE, object_id=row.pk, details=evidence
                )
            else:
                row.status = "retry"
                row.next_attempt_at = now + timedelta(seconds=delay)
        else:
            row.status = "unknown"
            findings.raise_or_touch(
                UNKNOWN_KIND, object_type=OBJECT_TYPE, object_id=row.pk, details=evidence
            )
        row.save(
            update_fields=[
                "status",
                "next_attempt_at",
                "leased_until",
                "last_error_code",
                "last_error_message",
            ]
        )
        return Result.fixed()
