"""
notify(): the single entry point (NOTIFICATIONS_AND_ALERTING.md § 3).

    notify("orders.assigned", obj=order, recipients=[order.assignee_id], context={...})

It does no fallible work inline: it checks the purpose exists, then registers a
transaction.on_commit that writes ONE outbox row (ids and scalars). Resolution, rendering
and delivery happen in the worker. Nothing it does can raise into the caller's save.
Callers pass subjects (an object, user ids), never an address, channel or URL:
routing is data (core_notification_route).

Exceptions: `durable=True` writes the outbox row inside the caller's transaction (still renders
nothing inline). A token-bearing purpose is delivered in the committing process, in memory: its
single-use link is never written to the outbox or the delivery log.
"""

import json
import logging
import uuid

from django.db import transaction

from core.env import outbound_guard_active
from core.outbox import enqueue
from core.registry import registry

from . import engine

logger = logging.getLogger("core.notifications")
SCALARS = (str, int, float, bool, type(None))


class NotifyError(Exception):
    """A programming error: an unknown purpose, or a context that is not scalars."""


def object_ref_of(obj) -> str:
    return f"{obj._meta.label_lower}:{obj.pk}" if obj is not None else ""


def _validated(purpose: str, recipients, context):
    if purpose not in registry.notification_purposes:
        raise NotifyError(f"unknown notification purpose {purpose!r}")
    context = dict(context or {})
    for key, value in context.items():
        if not isinstance(key, str) or not isinstance(value, SCALARS):
            raise NotifyError(f"context {key!r} is a {type(value).__name__}: pass scalars")
    ids = None
    if recipients is not None:
        ids = [getattr(r, "pk", r) for r in recipients]
        if any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
            raise NotifyError("recipients are users or user ids, never addresses")
    return context, ids


def notify(
    purpose: str,
    *,
    obj=None,
    recipients=None,
    context: dict | None = None,
    dedupe_key: str = "",
    durable: bool = False,
) -> None:
    try:
        context, ids = _validated(purpose, recipients, context)
        spec = registry.notification_purposes.get(purpose)
        ref = object_ref_of(obj)
        call_id = uuid.uuid4().hex
    except NotifyError:
        if outbound_guard_active(_app_env()):
            raise  # tests and development learn at once; production logs and carries on
        logger.exception("core.notify.rejected", extra={"purpose": purpose})
        return
    if spec.carries_token:

        def run() -> None:
            try:
                for row in engine.plan(
                    spec,
                    recipients=ids,
                    object_ref=ref,
                    context=context,
                    dedupe_key=dedupe_key,
                    call_id=call_id,
                ):
                    engine.send_delivery(row, context=context)
            except Exception:  # noqa: BLE001 — a notification never fails the save
                logger.exception("core.notify.failed", extra={"purpose": purpose})

        transaction.on_commit(run, robust=True)
        return
    payload = {
        "purpose": purpose,
        "recipients": "*" if ids is None else ",".join(map(str, ids)),
        "object_ref": ref,
        "context": json.dumps(context, separators=(",", ":")),
        "dedupe_key": dedupe_key,
        "call_id": call_id,
    }

    def queue() -> None:
        try:
            with transaction.atomic():
                enqueue(
                    engine.DISPATCH_TOPIC,
                    dedupe_key=f"{engine.DISPATCH_TOPIC}:{call_id}",
                    payload=payload,
                )
        except Exception:  # noqa: BLE001 — a notification never fails the save
            logger.exception("core.notify.enqueue_failed", extra={"purpose": purpose})

    if durable:
        queue()
    else:
        transaction.on_commit(queue, robust=True)


def _app_env() -> str:
    from django.conf import settings

    return settings.APP_ENV
