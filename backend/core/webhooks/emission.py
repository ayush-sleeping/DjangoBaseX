"""
webhooks.emit(event, obj) (JOBS_AND_INTEGRATIONS.md § 16): one outbox row in the caller's
transaction, never an exception into the business action. Fan-out to endpoints happens in the
worker (core.webhooks.delivery.fan_out), through the subscription table.
"""

import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.outbox import enqueue
from core.registry import registry

logger = logging.getLogger("core.webhooks")

EVENT_TOPIC = "webhooks.event"


def object_id_of(obj) -> str:
    """The id a receiver sees: the public id when the model has one, never the internal key."""
    public = getattr(obj, "public_id", None)
    return str(public if public is not None else obj.pk)


def emit(event: str, obj) -> None:
    """
    Announce `event` about `obj`. Unknown event: a programming error, so it raises in tests and
    DEBUG and logs at ERROR otherwise, queuing nothing. An internal (non-external) event queues
    nothing: nobody can subscribe to it. Any other failure is logged and swallowed, inside a
    savepoint so it cannot poison the caller's transaction.
    """
    if event not in registry.events:
        if settings.DEBUG or settings.APP_ENV == "test":
            raise KeyError(f"webhooks.emit() of an unregistered event {event!r}")
        logger.error("core.webhooks.unknown_event", extra={"event": event})
        return
    spec = registry.events.get(event)
    if not spec.external:
        return
    try:
        event_id = "evt_" + uuid.uuid4().hex
        with transaction.atomic():  # a savepoint: a failure here stays here
            enqueue(
                EVENT_TOPIC,
                dedupe_key=f"{EVENT_TOPIC}:{event_id}",
                payload={
                    "event": event,
                    "event_id": event_id,
                    "object_type": spec.object_type,
                    "object_id": object_id_of(obj),
                    "occurred_at": timezone.now().isoformat(),
                },
            )
    except Exception:  # noqa: BLE001 — emitting must never fail the business action
        logger.exception("core.webhooks.emit_failed", extra={"event": event})
