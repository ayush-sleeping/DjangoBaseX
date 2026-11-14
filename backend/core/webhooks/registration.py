"""What webhooks contribute to the registries, made from CoreConfig.ready() (BUILD_ORDER 7.6)."""

from django.db.models import Q

from core.jobs.retry import RetryPolicy
from core.registry import (
    AT_LEAST_ONCE,
    EncryptedField,
    HttpPurpose,
    OutboxTopic,
    Registry,
    RetentionPolicy,
)
from core.retention import register as register_retention

from .policy import MAX_TIMEOUT_SECONDS, InboundPolicy, WebhookPolicy

# The ladder lives in core.webhooks.delivery (it hands the outbox an explicit delay); this policy
# only bounds the row: the runtime setting webhooks.max_attempts is what actually ends a delivery.
DELIVER_RETRY = RetryPolicy(max_attempts=10, base_seconds=30, factor=4, cap_seconds=7200)

PURPOSE = HttpPurpose(
    name="webhooks.deliver",
    owner_module="core",
    description=(
        "Signed webhook deliveries to URLs that API consumers typed in. Every connection's "
        "address is vetted; redirects are never followed. If it is blocked, no event reaches "
        "any receiver."
    ),
    connect_timeout=5,
    read_timeout=MAX_TIMEOUT_SECONDS,  # the ceiling; each endpoint sets its own, at most this
    user_controlled_urls=True,
    allow_http=True,  # the https-only rule is runtime (a setting), enforced in service.py
    follow_redirects=False,
    max_response_bytes=256_000,
)

TOPICS = (
    OutboxTopic(
        topic="webhooks.event",
        handler="core.webhooks.delivery.fan_out",
        semantics=AT_LEAST_ONCE,
        owner_module="core",
        description=(
            "One emitted event, fanned out to every active subscribed endpoint. If it stops, no "
            "event is delivered anywhere."
        ),
    ),
    OutboxTopic(
        topic="webhooks.deliver",
        handler="core.webhooks.delivery.deliver",
        semantics=AT_LEAST_ONCE,  # receivers dedupe on the delivery id header
        owner_module="core",
        description=(
            "One signed delivery of one event to one endpoint. If it stops, receivers miss events "
            "(the delivery log shows them pending)."
        ),
        retry=DELIVER_RETRY,
        lease_seconds=60,
        http_purpose="webhooks.deliver",
    ),
    OutboxTopic(
        topic="webhooks.inbound",
        handler="core.webhooks.inbound.process",
        semantics=AT_LEAST_ONCE,
        owner_module="core",
        description=(
            "Processes one stored inbound webhook event. If it stops, verified provider callbacks "
            "stay `received` and nothing acts on them."
        ),
    ),
)

RETENTION = (
    RetentionPolicy(
        key="core.webhook_delivery",
        model="core.WebhookDelivery",
        timestamp_field="created_at",
        description="The webhook delivery log (settled deliveries only).",
        data_class="operational_log",
        max_age_days=30,
        min_age_days=1,
        filter=~Q(status="pending"),  # a delivery still being attempted is never pruned
        max_rows=500_000,
    ),
    RetentionPolicy(
        key="core.inbound_webhook_event",
        model="core.InboundWebhookEvent",
        timestamp_field="received_at",
        description="Stored inbound provider callbacks that were processed, ignored or failed.",
        data_class="operational_log",
        max_age_days=90,
        min_age_days=7,
        filter=~Q(status="received"),  # unprocessed events are the obligation; never pruned
        # No row cap: after the age cut these are the idempotency record. A cap could delete a
        # dedupe key a provider can still replay.
    ),
)


def register(registry: Registry) -> None:
    registry.http_purposes.register(PURPOSE)
    for topic in TOPICS:
        registry.outbox_topics.register(topic)
    registry.encrypted_fields.register(
        EncryptedField(
            model="core.WebhookEndpoint", field="secret_ciphertext", purpose="webhook_secret"
        )
    )
    registry.encrypted_fields.register(
        EncryptedField(
            model="core.WebhookEndpoint",
            field="previous_secret_ciphertext",
            purpose="webhook_secret",
        )
    )
    registry.settings.register_group(
        WebhookPolicy, prefix="webhooks.delivery", module="webhooks", group="Webhooks"
    )
    registry.settings.register_group(
        InboundPolicy, prefix="webhooks.inbound", module="webhooks", group="Inbound webhooks"
    )
    for policy in RETENTION:
        register_retention(registry, policy)
