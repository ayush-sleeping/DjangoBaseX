"""What notifications contribute to the registries, made from CoreConfig.ready() (7.7)."""

from dataclasses import dataclass, field

from django.db.models import Q

from core.jobs.retry import RetryPolicy
from core.registry import (
    AT_LEAST_ONCE,
    AT_MOST_ONCE,
    NotificationChannel,
    NotificationPurpose,
    OutboxTopic,
    Registry,
    RetentionPolicy,
)
from core.retention import register as register_retention
from core.settings_registry import Bool, String, meta

# Transient adapter failures retry; an ambiguous send never does (it is `unknown`, § 7).
DELIVER_RETRY = RetryPolicy(max_attempts=3, base_seconds=30, factor=4, cap_seconds=600)


@dataclass(frozen=True)
class NotificationsPolicy:
    """notifications.delivery.* (NOTIFICATIONS_AND_ALERTING.md § 3, § 6)."""

    enabled: bool = field(
        default=True,
        metadata=meta(
            Bool(),
            label="Send notifications",
            description=(
                "The platform switch (gate 1). Off: no purpose reaches any channel, security "
                "notices included, and nothing is queued. Use it to silence a noisy incident, "
                "then turn it back on: password resets stop while it is off."
            ),
            changed_by_event="A notification storm, or a provider outage you cannot absorb",
            used_by=("notify()",),
        ),
    )
    test_recipient: str = field(
        default="",
        metadata=meta(
            String(max_length=254),
            label="Test-routing recipient (email)",
            description=(
                "Purposes in test routing send every email here, with the intended recipients "
                "named in the body. Empty: test-routed email is held, not sent. Token-bearing "
                "mail (password reset, invitation) is never redirected in production."
            ),
            changed_by_event="Rolling out a new notification flow",
            used_by=("notify() test routing",),
        ),
    )


CHANNELS = (
    NotificationChannel(
        key="email",
        label="Email",
        adapter="core.notifications.channels.EMAIL",
    ),
    NotificationChannel(
        key="in_app",
        label="In-app (the bell)",
        adapter="core.notifications.channels.IN_APP",
    ),
)

PURPOSES = (
    NotificationPurpose(
        code="core.webhook_endpoint_disabled",
        label="Webhook endpoint disabled",
        owner_module="core",
        description="A webhook endpoint failed too many times in a row and was switched off.",
        audience=("user", "broadcast"),
        default_channels=("in_app", "email"),
        recipients="core.notifications.recipients.webhook_managers",
        preview="core.notifications.recipients.webhook_disabled_preview",
        template="core/email/webhook_endpoint_disabled",
        level="warning",
    ),
)

TOPICS = (
    OutboxTopic(
        topic="notifications.dispatch",
        handler="core.notifications.engine.dispatch",
        semantics=AT_LEAST_ONCE,  # it only writes idempotent delivery rows; nothing is sent here
        owner_module="core",
        description=(
            "One notify() call: resolves recipients, runs the gate chain and queues one delivery "
            "per recipient x channel. If it stops, no notification is ever delivered."
        ),
    ),
    OutboxTopic(
        topic="notifications.deliver",
        handler="core.notifications.engine.deliver",
        semantics=AT_MOST_ONCE,  # human-facing: an ambiguous send is `unknown`, never resent
        owner_module="core",
        description=(
            "One notification handed to its channel (email, in-app). If it stops, people are not "
            "told (the delivery log shows them pending)."
        ),
        retry=DELIVER_RETRY,
        lease_seconds=120,
        http_purpose="smtp",
    ),
)

RETENTION = (
    RetentionPolicy(
        key="core.notification_inapp",
        model="core.Notification",
        timestamp_field="updated_at",
        description="In-app notifications that were read or resolved.",
        data_class="operational_log",
        max_age_days=90,
        min_age_days=7,
        filter=Q(read_at__isnull=False) | Q(resolved_at__isnull=False),
        max_rows=2_000_000,
    ),
    RetentionPolicy(
        key="core.notification_delivery",
        model="core.NotificationDelivery",
        timestamp_field="created_at",
        description="The notification delivery log (settled deliveries only).",
        data_class="operational_log",
        max_age_days=90,
        min_age_days=7,
        filter=~Q(status="pending"),  # still being attempted: never pruned
        max_rows=2_000_000,
    ),
)


def register(registry: Registry) -> None:
    for channel in CHANNELS:
        registry.notification_channels.register(channel)
    for purpose in PURPOSES:
        registry.notification_purposes.register(purpose)
    for topic in TOPICS:
        registry.outbox_topics.register(topic)
    registry.settings.register_group(
        NotificationsPolicy,
        prefix="notifications.delivery",
        module="notifications",
        group="Notifications",
    )
    for policy in RETENTION:
        register_retention(registry, policy)
