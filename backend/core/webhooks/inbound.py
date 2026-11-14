"""
Inbound webhooks (JOBS_AND_INTEGRATIONS.md § 17): one framework for third-party callbacks.

Order is the whole point: verify over the RAW bytes first, fail closed on a missing secret,
check the timestamp, THEN claim the dedupe key in the database, persist, commit, answer 200,
process later.
Invalid signature is one exception (InvalidSignature) that the view turns into 400
`invalid_signature`; there is no per-provider except clause to get wrong.

No real provider ships in core. A provider registers a Verifier and a handler:

    registry.inbound_webhooks.register(MyVerifier(), handler="myapp.hooks.handle")
"""

import hmac
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import import_module
from typing import Protocol

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from core import settings_service
from core.api.errors import error_response
from core.api.views import BaseAPIView
from core.http import client_ip
from core.models import InboundWebhookEvent
from core.outbox import Delivery, Outcome, enqueue
from core.registry import registry

from .policy import InboundPolicy

logger = logging.getLogger("core.webhooks")

INBOUND_TOPIC = "webhooks.inbound"
MAX_BODY_BYTES = 1_000_000


class InvalidSignature(Exception):
    """Verification failed for any reason: bad signature, stale timestamp, malformed header."""


@dataclass(frozen=True)
class Verified:
    """What a verifier proved. `payload` is the MINIMISED allowlist of fields to keep, never the
    provider's whole body."""

    delivery_id: str
    event_type: str = ""
    payload: dict = field(default_factory=dict)


class Verifier(Protocol):
    provider: str
    durable_dedupe: (
        bool  # True: a database claim (money, state). False documents a fail-open claim.
    )

    def secret_for(self, ingress_token: str) -> str | None:
        """The secret of the connection this opaque token names, or None when it names none."""

    def verify(self, raw_body: bytes, headers: Mapping[str, str], secret: str) -> Verified:
        """Raise InvalidSignature unless `raw_body` is proven authentic. Never parse before this."""

    def dedupe_key(self, verified: Verified) -> str: ...


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def check_timestamp(timestamp: int | str, *, now: float | None = None) -> None:
    """Helper for verifiers whose provider signs a timestamp: an old signed delivery is a replay."""
    tolerance = settings_service.resolve(InboundPolicy).timestamp_tolerance_seconds
    try:
        value = int(timestamp)
    except (TypeError, ValueError):
        raise InvalidSignature("timestamp is not a number") from None
    if abs((now if now is not None else time.time()) - value) > tolerance:
        raise InvalidSignature("timestamp outside the tolerance")


class InboundWebhookThrottle(SimpleRateThrottle):
    """Per address. The rate is declared here because the shipped REST_FRAMEWORK table is
    protected (TECH_DEBT: move to settings once that file may change)."""

    scope = "inbound_webhook"
    rate = "300/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": client_ip(request) or "unknown"}


def _invalid(message="The signature could not be verified.") -> Response:
    return error_response("invalid_signature", message, status.HTTP_400_BAD_REQUEST)


class InboundWebhookView(BaseAPIView):
    """POST /api/hooks/<provider>/<ingress_token>/ : public by declaration (public_routes), no
    session, no CSRF (it is not cookie-authenticated), throttled, JSON body read raw."""

    public = True
    authentication_classes = []
    throttle_classes = [InboundWebhookThrottle]

    def post(self, request, provider, ingress_token):
        if provider not in registry.inbound_webhooks:
            return error_response("not_found", "Unknown provider.", status.HTTP_404_NOT_FOUND)
        verifier, _handler = registry.inbound_webhooks.get(provider)
        raw = request.body  # before any parser touches it (DRF parses lazily, not before this)
        if len(raw) > MAX_BODY_BYTES:
            return error_response(
                "too_large", "Body too large.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )
        try:
            secret = verifier.secret_for(ingress_token)
            if not secret:  # unknown token or no secret: fail closed, in EVERY environment
                raise InvalidSignature("no secret")
            verified = verifier.verify(raw, request.headers, secret)
        except InvalidSignature:
            return _invalid()
        # Only now, with the signature proven, may the delivery id be claimed.
        key = verifier.dedupe_key(verified)[:255]
        try:
            with transaction.atomic():
                event = InboundWebhookEvent.objects.create(
                    provider=provider,
                    delivery_id=verified.delivery_id[:255],
                    dedupe_key=key,
                    event_type=verified.event_type[:128],
                    payload=verified.payload,
                )
                # The `received` row's obligation lives in the outbox, in the same commit: if the
                # enqueue fails the row rolls back and the provider is told 5xx and retries.
                enqueue(
                    INBOUND_TOPIC,
                    dedupe_key=f"{INBOUND_TOPIC}:{event.pk}",
                    payload={"event": event.pk},
                )
        except IntegrityError:
            return Response({"status": "duplicate"}, status=status.HTTP_200_OK)
        return Response({"status": "received"}, status=status.HTTP_200_OK)


def process(message: Delivery) -> Outcome:
    """Outbox handler: run the provider's handler for one stored event."""
    event = InboundWebhookEvent.objects.filter(pk=message.payload["event"]).first()
    if event is None or event.status != InboundWebhookEvent.Status.RECEIVED:
        return Outcome.SKIPPED("not_received")
    InboundWebhookEvent.objects.filter(pk=event.pk).update(attempts=event.attempts + 1)
    if event.provider not in registry.inbound_webhooks:
        return _finish(event, InboundWebhookEvent.Status.IGNORED, "provider_unregistered")
    _verifier, handler_path = registry.inbound_webhooks.get(event.provider)
    if handler_path is None:
        return _finish(event, InboundWebhookEvent.Status.IGNORED, "no_handler")
    module, _, name = handler_path.rpartition(".")
    try:
        getattr(import_module(module), name)(event.pk)
    except Exception as exc:  # noqa: BLE001 — our processing failure is ours: record, never re-ask the provider
        logger.exception("core.webhooks.inbound_failed", extra={"event_id": event.pk})
        return _finish(event, InboundWebhookEvent.Status.FAILED, type(exc).__name__[:100])
    return _finish(event, InboundWebhookEvent.Status.PROCESSED, "")


def _finish(event, status_value, code) -> Outcome:
    InboundWebhookEvent.objects.filter(pk=event.pk).update(
        status=status_value, error_code=code, processed_at=timezone.now()
    )
    return (
        Outcome.SENT(ref=status_value)
        if status_value == "processed"
        else Outcome.SKIPPED(code or status_value)
    )
