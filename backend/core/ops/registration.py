"""What ops alerting contributes to the registries, made from CoreConfig.ready() (7.8)."""

from django.db.models import Q

from core.registry import (
    FindingKind,
    Interval,
    JobSpec,
    NotificationPurpose,
    Registry,
    RetentionPolicy,
)
from core.retention import register as register_retention

from .dispatcher import NO_DESTINATION_KIND
from .kinds import PURPOSE_ALERT, PURPOSE_DIGEST
from .settings import AlertPolicy, IncidentPolicy

PURPOSES = (
    NotificationPurpose(
        code=PURPOSE_ALERT,
        label="Ops alert",
        owner_module="core",
        description="An operational alert: an incident opening or recovering, an alert storm, or "
        "the quiet-hours summary. Routed by data; sent only through the ops dispatcher.",
        audience=("user", "broadcast"),
        default_channels=("in_app", "email"),
        recipients="core.ops.recipients.ops_recipients",
        preview="core.ops.recipients.alert_preview",
        template="core/email/ops_alert",
        level="warning",
    ),
    NotificationPurpose(
        code=PURPOSE_DIGEST,
        label="Ops digest",
        owner_module="core",
        description="The twice-daily ops digest: held alerts, open incidents, or an all-clear.",
        audience=("user", "broadcast"),
        default_channels=("in_app", "email"),
        recipients="core.ops.recipients.ops_recipients",
        preview="core.ops.recipients.digest_preview",
        template="core/email/ops_digest",
        level="info",
    ),
)

KINDS = (
    FindingKind(
        kind=NO_DESTINATION_KIND,
        label="Ops alerts have no destination",
        severity="warning",
        owner_module="core",
        resolutions=("dismissed",),
        runbook="documentation/system-design/NOTIFICATIONS_AND_ALERTING.md#14-the-ops-alert-dispatcher-and-its-ledger",
    ),
)

JOBS = (
    JobSpec(
        name="ops.monitor",
        func="core.ops.jobs.run_monitor",
        owner_module="ops",
        description="Runs every registered doctor and reports what it finds through the ops "
        "dispatcher as incidents (announced once, recovered once). Always exits 0. If it stops, "
        "problems are noticed only when a human runs `manage.py doctor`.",
        schedule=Interval(300),
        expires=270,
        idempotent=True,  # sync() is a function of the current problem set
        unit="problems",
    ),
    JobSpec(
        name="ops.alert_digest",
        func="core.ops.jobs.run_alert_digest",
        owner_module="ops",
        description="Sends the ops digest when a configured digest time has passed, and settles "
        "the previous one from the delivery log. If it stops, held alerts are never sent and the "
        "all-clear line stops arriving.",
        schedule=Interval(900),
        expires=840,
        idempotent=True,  # one run per digest slot (core_ops_digest_run)
        unit="alerts",
    ),
    JobSpec(
        name="ops.release_held",
        func="core.ops.jobs.run_release_held",
        owner_module="ops",
        description="After quiet hours end, sends the single summary of the alerts held inside "
        "the window. If it stops, alerts held at night are never released.",
        schedule=Interval(900),
        expires=840,
        idempotent=True,  # released rows are not held again
        unit="alerts",
    ),
)

RETENTION = (
    RetentionPolicy(
        key="core.ops_alert",
        model="core.OpsAlert",
        timestamp_field="created_at",
        description="The ops alert ledger (alerts still held for a digest are never pruned).",
        data_class="operational_log",
        max_age_days=90,
        min_age_days=7,
        filter=~Q(decision="held", released_at__isnull=True),
        max_rows=500_000,
    ),
    RetentionPolicy(
        key="core.ops_incident",
        model="core.Incident",
        timestamp_field="recovered_at",
        description="Recovered incidents (open and pending ones are live state).",
        data_class="operational_log",
        max_age_days=180,
        min_age_days=7,
        filter=Q(status="recovered"),
    ),
    RetentionPolicy(
        key="core.ops_digest_run",
        model="core.OpsDigestRun",
        timestamp_field="created_at",
        description="Settled ops digest runs (a pending one is still being delivered).",
        data_class="operational_log",
        max_age_days=90,
        min_age_days=7,
        filter=~Q(status="pending"),
        max_rows=50_000,
    ),
)


def register(registry: Registry) -> None:
    for purpose in PURPOSES:
        registry.notification_purposes.register(purpose)
    for kind in KINDS:
        registry.finding_kinds.register(kind)
    for job in JOBS:
        registry.jobs.register(job)
    registry.settings.register_group(
        AlertPolicy, prefix="operations.alerts", module="operations", group="Ops alerting"
    )
    registry.settings.register_group(
        IncidentPolicy, prefix="operations.incidents", module="operations", group="Ops alerting"
    )
    for policy in RETENTION:
        register_retention(registry, policy)
