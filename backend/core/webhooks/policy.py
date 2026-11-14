"""Runtime settings for webhooks (JOBS_AND_INTEGRATIONS.md § 16, § 17), registered by core."""

from dataclasses import dataclass, field

from core.settings_registry import Bool, Int, meta

MAX_TIMEOUT_SECONDS = 30  # the hard cap on one endpoint's timeout; the setting's default is lower


@dataclass(frozen=True)
class WebhookPolicy:
    """webhooks.* (CONFIGURATION.md § 9)."""

    breaker_threshold: int = field(
        default=10,
        metadata=meta(
            Int(min=1, max=1000),
            label="Failed deliveries before an endpoint is disabled",
            description=(
                "After this many consecutive failed deliveries (not attempts) an endpoint is "
                "disabled by the circuit breaker and skipped until someone re-enables it. Lower "
                "stops hammering a dead receiver sooner; higher tolerates a longer outage."
            ),
            changed_by_event="A receiver that is down for days, or one disabled too eagerly",
            used_by=("Webhook delivery",),
        ),
    )
    max_attempts: int = field(
        default=5,
        metadata=meta(
            Int(min=1, max=10),
            label="Attempts per webhook delivery",
            description=(
                "How many times one delivery is tried (the first included) before it is marked "
                "failed. The wait between attempts is 30 s, 2 min, 10 min, 30 min, 2 h."
            ),
            changed_by_event="Receivers that need longer to recover, or less retry noise",
            used_by=("Webhook delivery",),
        ),
    )
    default_timeout_seconds: int = field(
        default=10,
        metadata=meta(
            Int(min=1, max=MAX_TIMEOUT_SECONDS),
            label="Default webhook timeout (seconds)",
            description=(
                "The time a receiver has to answer, for endpoints that do not set their own. "
                f"No endpoint may exceed {MAX_TIMEOUT_SECONDS} seconds."
            ),
            changed_by_event="Slow receivers timing out, or workers held too long by slow ones",
            used_by=("Webhook endpoints", "Webhook delivery"),
        ),
    )
    allow_http: bool = field(
        default=False,
        metadata=meta(
            Bool(),
            label="Allow plain http:// webhook URLs in production",
            description=(
                "Off: production endpoints must be https://. On: http:// is accepted too, and "
                "payloads travel unencrypted. Outside production http:// is always accepted."
            ),
            changed_by_event="A receiver inside a private network with no TLS",
            used_by=("Webhook endpoints", "Webhook delivery"),
        ),
    )
    rotation_overlap_hours: int = field(
        default=24,
        metadata=meta(
            Int(min=1, max=720),
            label="Hours the old webhook secret keeps signing after a rotation",
            description=(
                "During the overlap every delivery carries a signature for the new and the old "
                "secret, so a receiver can deploy the new secret without dropping deliveries."
            ),
            changed_by_event="Receivers that deploy slowly, or a leaked secret that must stop now",
            used_by=("Webhook secret rotation", "Webhook delivery"),
        ),
    )


@dataclass(frozen=True)
class InboundPolicy:
    """webhooks.inbound.* (CONFIGURATION.md § 9)."""

    timestamp_tolerance_seconds: int = field(
        default=300,
        metadata=meta(
            Int(min=30, max=3600),
            label="Inbound webhook timestamp tolerance (seconds)",
            description=(
                "A validly signed delivery whose timestamp is older (or further in the future) "
                "than this is a replay and is rejected. Lower is stricter but needs accurate "
                "clocks."
            ),
            changed_by_event="Clock skew with a provider, or a provider that retries late",
            used_by=("Inbound webhooks",),
        ),
    )
