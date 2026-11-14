"""
The outbox handlers for webhooks (JOBS_AND_INTEGRATIONS.md § 16).

fan_out(event message)   one message per emitted event; creates one WebhookDelivery and one
                         outbox row per SUBSCRIBED, active endpoint (an indexed join).
deliver(delivery message) signs and sends one delivery through core.http, maps the answer to an
                         Outcome and records it on the WebhookDelivery row (the delivery log).

A delivery that fails for good ends the outbox row as `skipped` with the reason, not `failed`: the
dead letter a human works is the WebhookDelivery (with its Redeliver button), and an outbox finding
per dead third-party receiver would be noise nobody on our side can fix.
"""

import json
import logging
import random
import time
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core import http as core_http
from core.jobs.retry import is_retryable_status
from core.models import WebhookDelivery, WebhookEndpoint
from core.notifications import notify
from core.observability.scrub import default_rules
from core.outbox import Delivery, Outcome
from core.providers.errors import ProviderError, from_exception, parse_retry_after

from . import service, signing

logger = logging.getLogger("core.webhooks")

HTTP_PURPOSE = "webhooks.deliver"
LADDER_SECONDS = (30, 120, 600, 1800, 7200)  # after attempt 1, 2, 3, 4, 5+
JITTER = 0.2
RESPONSE_BODY_LIMIT = 2000
USER_AGENT_VERSION = "1"


def fan_out(message: Delivery) -> Outcome:
    payload = message.payload
    event = payload["event"]
    created = 0
    endpoints = WebhookEndpoint.objects.filter(
        is_active=True, disabled_at__isnull=True, subscriptions__event=event
    )
    for endpoint in endpoints:
        with transaction.atomic():
            row, was_new = WebhookDelivery.objects.get_or_create(
                endpoint=endpoint,
                delivery_id=service.delivery_id_for(payload["event_id"], endpoint),
                defaults={
                    "event": event,
                    "event_id": payload["event_id"],
                    "payload": service.build_payload(
                        event,
                        payload["event_id"],
                        payload["occurred_at"],
                        payload["object_type"],
                        payload["object_id"],
                    ),
                    "next_attempt_at": timezone.now(),
                },
            )
            service.queue_delivery(row)  # ON CONFLICT DO NOTHING: a re-run adds nothing
            created += was_new
    return Outcome.SENT(ref=str(created))


def ladder_delay(attempt: int, retry_after: float | None, rand=random.random) -> float:
    """Seconds before the next attempt: Retry-After as given (capped at the ladder's top), else the
    ladder step for the attempt that just failed, +/- 20 % jitter."""
    top = LADDER_SECONDS[-1]
    if retry_after is not None:
        return min(max(retry_after, 0.0), top)
    step = LADDER_SECONDS[min(max(attempt, 1), len(LADDER_SECONDS)) - 1]
    return step * (1 + JITTER * (2 * rand() - 1))


def _body(row: WebhookDelivery) -> bytes:
    return json.dumps(row.payload, separators=(",", ":"), sort_keys=True).encode()


def _request_headers(row, endpoint, raw: bytes, now) -> dict[str, str]:
    names = signing.header_names()
    timestamp = int(now.timestamp())
    headers = dict(endpoint.custom_headers or {})
    headers.update(
        {
            "Content-Type": "application/json",
            "User-Agent": f"{_product_name()}-Webhooks/{USER_AGENT_VERSION}",
            names["timestamp"]: str(timestamp),
            names["event"]: row.event,
            names["delivery"]: row.delivery_id,
            # Computed, sent, and never stored: the signature is not part of the logged snapshot.
            names["signature"]: signing.signature_header(
                service.live_secrets(endpoint, now), timestamp, raw
            ),
        }
    )
    return headers


def _product_name() -> str:
    from django.conf import settings

    return "".join(ch for ch in settings.PRODUCT_NAME.title() if ch.isalnum()) or "Webhooks"


def _record(row_id: int, **fields) -> None:
    WebhookDelivery.objects.filter(pk=row_id).update(**fields)


def _give_up(
    row: WebhookDelivery, code: str, now, *, status_code=None, body="", ms=None
) -> Outcome:
    """The delivery failed for good: log it, count it against the breaker (not for a test ping)."""
    _record(
        row.pk,
        status=WebhookDelivery.Status.FAILED,
        failed_at=now,
        next_attempt_at=None,
        error_code=code[:100],
        response_status=status_code,
        response_body=body,
        duration_ms=ms,
    )
    if not row.is_test:
        _count_failure(row.endpoint_id, now)
    return Outcome.SKIPPED(code)


def _count_failure(endpoint_id: int, now) -> None:
    threshold = service.policy().breaker_threshold
    WebhookEndpoint.objects.filter(pk=endpoint_id).update(
        consecutive_failures=F("consecutive_failures") + 1
    )
    tripped = WebhookEndpoint.objects.filter(
        pk=endpoint_id, consecutive_failures__gte=threshold, disabled_at__isnull=True
    ).update(disabled_at=now)
    if tripped:
        endpoint = WebhookEndpoint.objects.get(pk=endpoint_id)
        notify(
            "core.webhook_endpoint_disabled",
            obj=endpoint,
            context={
                "title": f"Webhook endpoint disabled: {endpoint.name}"[:200],
                "body": f"{endpoint.consecutive_failures} deliveries failed in a row.",
                "endpoint_name": endpoint.name,
                "failures": endpoint.consecutive_failures,
            },
        )


def deliver(message: Delivery) -> Outcome:
    now = timezone.now()
    row = (
        WebhookDelivery.objects.select_related("endpoint")
        .filter(pk=message.payload["delivery"])
        .first()
    )
    if row is None:
        return Outcome.SKIPPED("delivery_missing")
    if row.status == WebhookDelivery.Status.DELIVERED:
        return Outcome.SKIPPED("already_delivered")
    endpoint = row.endpoint
    if not row.is_test and (not endpoint.is_active or endpoint.disabled_at):
        # Re-validated at send, not only at queue time: the endpoint may have tripped since.
        _record(
            row.pk,
            status=WebhookDelivery.Status.FAILED,
            failed_at=now,
            next_attempt_at=None,
            error_code="endpoint_disabled",
        )
        return Outcome.SKIPPED("endpoint_disabled")
    WebhookDelivery.objects.filter(pk=row.pk).update(attempts=F("attempts") + 1)

    raw = _body(row)
    started = time.perf_counter()
    response, error = None, None
    try:
        if not service.scheme_allowed(endpoint.url):  # the https-only rule holds at send too
            raise ProviderError(HTTP_PURPOSE, code="scheme_not_allowed")
        response = core_http.client(HTTP_PURPOSE).post(
            endpoint.url,
            content=raw,
            headers=_request_headers(row, endpoint, raw, now),
            timeout=min(endpoint.timeout_seconds, service.MAX_TIMEOUT_SECONDS),
        )
    except Exception as exc:  # noqa: BLE001 — every failure becomes a classified outcome below
        error = from_exception(exc, HTTP_PURPOSE)
    ms = round((time.perf_counter() - started) * 1000)

    if error is not None:
        if error.transient:
            return _retry(row, message, now, error.code, None, "", ms, error.retry_after)
        return _give_up(row, error.code, now, ms=ms)

    code = response.status_code
    body = default_rules().scrub_text(response.text[:RESPONSE_BODY_LIMIT])[:RESPONSE_BODY_LIMIT]
    if 200 <= code < 300:
        _record(
            row.pk,
            status=WebhookDelivery.Status.DELIVERED,
            delivered_at=now,
            next_attempt_at=None,
            error_code="",
            response_status=code,
            response_body=body,
            duration_ms=ms,
        )
        if not row.is_test:
            WebhookEndpoint.objects.filter(pk=endpoint.pk).update(
                consecutive_failures=0, last_delivery_at=now
            )
        return Outcome.SENT(ref=str(code))
    if code == 410:  # Gone: the receiver said so. Permanent, and the endpoint stops being tried.
        outcome = _give_up(row, "http_410", now, status_code=code, body=body, ms=ms)
        WebhookEndpoint.objects.filter(pk=endpoint.pk, disabled_at__isnull=True).update(
            disabled_at=now
        )
        return outcome
    if is_retryable_status(code):
        after = parse_retry_after(response.headers.get("Retry-After"))
        return _retry(row, message, now, f"http_{code}", code, body, ms, after)
    reason = "redirect_not_followed" if 300 <= code < 400 else f"http_{code}"
    return _give_up(row, reason, now, status_code=code, body=body, ms=ms)


def _retry(row, message, now, code, status_code, body, ms, retry_after) -> Outcome:
    if message.attempt >= service.policy().max_attempts:
        return _give_up(row, code, now, status_code=status_code, body=body, ms=ms)
    delay = ladder_delay(message.attempt, retry_after)
    _record(
        row.pk,
        next_attempt_at=now + timedelta(seconds=delay),
        error_code=code[:100],
        response_status=status_code,
        response_body=body,
        duration_ms=ms,
    )
    return Outcome.RETRY(after=delay, code=code)
