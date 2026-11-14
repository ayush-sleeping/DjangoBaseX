"""
Webhook endpoint management: the one writer (JOBS_AND_INTEGRATIONS.md § 16). Views stay thin; this
validates, encrypts, audits and queues. The plaintext secret exists only in the return value of
create_endpoint() and rotate_secret(), which is how a view shows it once.
"""

import re
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from core import audit, crypto, settings_service
from core.env import outbound_guard_active
from core.http import vetting
from core.models import WebhookDelivery, WebhookEndpoint, WebhookSubscription
from core.outbox import enqueue
from core.providers.errors import UnsafeDestination
from core.registry import registry

from . import signing
from .policy import MAX_TIMEOUT_SECONDS, WebhookPolicy

PURPOSE = "webhook_secret"
DELIVER_TOPIC = "webhooks.deliver"
PING_EVENT = "core.webhook.ping"
MAX_CUSTOM_HEADERS = 8
MAX_HEADER_VALUE = 512
_HEADER_NAME = re.compile(r"^X-[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")
# Allowlist: only X-* names, minus the families the platform owns.
_FORBIDDEN_PREFIXES = ("x-forwarded-", "x-real-ip", "x-original-")

# Tests replace this to simulate DNS; production resolves through core.http.vetting.
resolver = None


class WebhookError(Exception):
    code = "webhook_error"


class InvalidEndpoint(WebhookError):
    """A field failed validation; `field` and the message are safe to show."""

    code = "invalid"

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


class NotRedeliverable(WebhookError):
    code = "not_redeliverable"


def allowed_schemes() -> tuple[str, ...]:
    """https always; http outside production, or in production when webhooks.allow_http is on."""
    production = not outbound_guard_active(_app_env())
    allow_http = settings_service.get_setting("webhooks.delivery.allow_http")
    return ("https", "http") if (allow_http or not production) else ("https",)


def scheme_allowed(url: str) -> bool:
    return urlsplit(url or "").scheme in allowed_schemes()


def validate_url(url: str) -> str:
    """https only in production unless webhooks.allow_http; no credentials in the URL; and the host
    must resolve only to public addresses RIGHT NOW. core.http repeats the vetting at every send,
    against the address it actually dials (DNS can change in between)."""
    parts = urlsplit(url or "")
    allowed = allowed_schemes()
    if parts.scheme not in allowed:
        raise InvalidEndpoint(
            "url", f"The URL must start with {' or '.join(a + '://' for a in allowed)}."
        )
    if not parts.hostname:
        raise InvalidEndpoint("url", "The URL needs a host name.")
    if parts.username or parts.password:
        raise InvalidEndpoint("url", "The URL must not contain a user name or password.")
    try:
        vetting.vet(
            parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), resolver
        )
    except UnsafeDestination:
        raise InvalidEndpoint("url", "That address cannot be reached from this service.") from None
    return url


def _app_env() -> str:
    from django.conf import settings

    return settings.APP_ENV


def validate_headers(headers) -> dict[str, str]:
    if headers in (None, ""):
        return {}
    if not isinstance(headers, dict) or len(headers) > MAX_CUSTOM_HEADERS:
        raise InvalidEndpoint(
            "custom_headers", f"Send an object with at most {MAX_CUSTOM_HEADERS} headers."
        )
    own = signing.header_prefix().lower()
    clean = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not _HEADER_NAME.match(name):
            raise InvalidEndpoint(
                "custom_headers", f"{name!r}: custom headers are X-* names (letters, digits, -)."
            )
        lowered = name.lower()
        if lowered.startswith(_FORBIDDEN_PREFIXES) or lowered.startswith(own):
            raise InvalidEndpoint("custom_headers", f"{name}: this header is set by the platform.")
        if (
            not isinstance(value, str)
            or len(value) > MAX_HEADER_VALUE
            or re.search(r"[\r\n\0]", value)
        ):
            raise InvalidEndpoint(
                "custom_headers", f"{name}: the value must be a single line of text."
            )
        clean[name] = value
    return clean


def validate_events(events) -> list[str]:
    """Against the catalogue (events flagged external). Empty, unknown and wildcard are refused."""
    if not isinstance(events, (list, tuple)) or not events:
        raise InvalidEndpoint("events", "Subscribe to at least one event.")
    catalogue = {e.name for e in registry.events.external()}
    unique = list(dict.fromkeys(events))
    bad = [e for e in unique if not isinstance(e, str) or e not in catalogue]
    if bad:
        raise InvalidEndpoint(
            "events", f"Not in the event catalogue (no wildcards): {', '.join(map(str, bad))}."
        )
    return unique


def clamp_timeout(value) -> int:
    default = settings_service.get_setting("webhooks.delivery.default_timeout_seconds")
    if value in (None, ""):
        return default
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= MAX_TIMEOUT_SECONDS
    ):
        raise InvalidEndpoint("timeout_seconds", f"Between 1 and {MAX_TIMEOUT_SECONDS} seconds.")
    return value


def new_secret() -> str:
    return signing.secret_prefix() + secrets.token_urlsafe(32)


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


@transaction.atomic
def create_endpoint(
    *, actor, name, url, events, timeout_seconds=None, custom_headers=None, is_active=True
):
    """Returns (endpoint, plaintext_secret): the secret is never available again."""
    events = validate_events(events)
    validate_url(url)
    secret = new_secret()
    endpoint = WebhookEndpoint.objects.create(
        name=name,
        url=url,
        secret_ciphertext=crypto.encrypt(secret, purpose=PURPOSE),
        timeout_seconds=clamp_timeout(timeout_seconds),
        custom_headers=validate_headers(custom_headers),
        is_active=is_active,
        created_by=actor,
        updated_by=actor,
    )
    WebhookSubscription.objects.bulk_create(
        [WebhookSubscription(endpoint=endpoint, event=e) for e in events]
    )
    audit.record(
        "core.webhook.created", endpoint, actor=actor, meta={"host": _host(url), "events": events}
    )
    return endpoint, secret


@transaction.atomic
def update_endpoint(*, actor, endpoint, **fields):
    """Re-pointing the URL redirects data, so it is audited on its own. Re-enabling clears the
    breaker's state (`disabled_at`, the failure counter)."""
    old_url = endpoint.url
    if "events" in fields:
        events = validate_events(fields.pop("events"))
        endpoint.subscriptions.exclude(event__in=events).delete()
        have = set(endpoint.subscriptions.values_list("event", flat=True))
        WebhookSubscription.objects.bulk_create(
            [WebhookSubscription(endpoint=endpoint, event=e) for e in events if e not in have]
        )
    if "url" in fields and fields["url"] != old_url:
        endpoint.url = validate_url(fields.pop("url"))
    else:
        fields.pop("url", None)
    if "name" in fields:
        endpoint.name = fields["name"]
    if "timeout_seconds" in fields:
        endpoint.timeout_seconds = clamp_timeout(fields["timeout_seconds"])
    if "custom_headers" in fields:
        endpoint.custom_headers = validate_headers(fields["custom_headers"])
    if fields.get("is_active") is True and (not endpoint.is_active or endpoint.disabled_at):
        endpoint.disabled_at = None
        endpoint.consecutive_failures = 0
    if "is_active" in fields:
        endpoint.is_active = fields["is_active"]
    endpoint.updated_by = actor
    endpoint.save()
    if endpoint.url != old_url:
        audit.record(
            "core.webhook.repointed",
            endpoint,
            actor=actor,
            meta={"from_host": _host(old_url), "to_host": _host(endpoint.url)},
        )
    return endpoint


@transaction.atomic
def rotate_secret(*, actor, endpoint) -> tuple[WebhookEndpoint, str]:
    """The old secret keeps signing for the overlap setting. Returns the new secret once."""
    hours = settings_service.get_setting("webhooks.delivery.rotation_overlap_hours")
    secret = new_secret()
    endpoint.previous_secret_ciphertext = endpoint.secret_ciphertext
    endpoint.previous_secret_expires_at = timezone.now() + timedelta(hours=hours)
    endpoint.secret_ciphertext = crypto.encrypt(secret, purpose=PURPOSE)
    endpoint.updated_by = actor
    endpoint.save()
    audit.record(
        "core.webhook.secret_rotated",
        endpoint,
        actor=actor,
        meta={"overlap_hours": hours},
    )
    return endpoint, secret


@transaction.atomic
def delete_endpoint(*, actor, endpoint) -> None:
    audit.record("core.webhook.deleted", endpoint, actor=actor, meta={"host": _host(endpoint.url)})
    endpoint.delete()


def live_secrets(endpoint, now=None) -> list[str]:
    """The secrets a delivery is signed with: the current one, plus the previous during overlap."""
    now = now or timezone.now()
    found = [crypto.decrypt(endpoint.secret_ciphertext, purpose=PURPOSE)]
    if (
        endpoint.previous_secret_ciphertext
        and endpoint.previous_secret_expires_at
        and endpoint.previous_secret_expires_at > now
    ):
        found.append(crypto.decrypt(endpoint.previous_secret_ciphertext, purpose=PURPOSE))
    return found


def delivery_id_for(event_id: str, endpoint) -> str:
    """Stable per event x endpoint, so a receiver can deduplicate retries and redeliveries."""
    return "whd_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{event_id}:{endpoint.public_id}").hex


def queue_delivery(delivery: WebhookDelivery) -> None:
    """One outbox row for one attempt series; a redelivery gets a new key (attempts so far)."""
    enqueue(
        DELIVER_TOPIC,
        dedupe_key=f"{DELIVER_TOPIC}:{delivery.pk}:r{delivery.attempts}",
        payload={"delivery": delivery.pk},
    )


def build_payload(event: str, event_id: str, occurred_at: str, object_type: str, object_id: str):
    return {
        "id": event_id,
        "event": event,
        "occurred_at": occurred_at,
        "api_version": API_VERSION,
        "data": {"object": object_type, "id": object_id},
    }


API_VERSION = "v1"


@transaction.atomic
def send_test(*, actor, endpoint) -> WebhookDelivery:
    """A synthetic `ping` through the real signing, vetting and delivery path, bypassing
    subscriptions. Logged with is_test=True."""
    event_id = "evt_" + uuid.uuid4().hex
    delivery = WebhookDelivery.objects.create(
        endpoint=endpoint,
        event=PING_EVENT,
        event_id=event_id,
        delivery_id=delivery_id_for(event_id, endpoint),
        payload=build_payload(
            PING_EVENT, event_id, timezone.now().isoformat(), "ping", str(endpoint.public_id)
        ),
        next_attempt_at=timezone.now(),
        is_test=True,
    )
    queue_delivery(delivery)
    return delivery


@transaction.atomic
def redeliver(*, actor, delivery: WebhookDelivery) -> WebhookDelivery:
    """A new attempt for an existing delivery: same row, same delivery id."""
    delivery = WebhookDelivery.objects.select_for_update().get(pk=delivery.pk)
    if delivery.status == WebhookDelivery.Status.PENDING:
        raise NotRedeliverable("This delivery is still being attempted.")
    endpoint = delivery.endpoint
    if not delivery.is_test and (not endpoint.is_active or endpoint.disabled_at):
        raise NotRedeliverable("The endpoint is disabled: enable it first.")
    delivery.status = WebhookDelivery.Status.PENDING
    delivery.error_code = ""
    delivery.failed_at = None
    delivery.next_attempt_at = timezone.now()
    delivery.save(update_fields=["status", "error_code", "failed_at", "next_attempt_at"])
    queue_delivery(delivery)
    return delivery


def policy() -> WebhookPolicy:
    return settings_service.resolve(WebhookPolicy)
