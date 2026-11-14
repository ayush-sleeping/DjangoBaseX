"""
The notification engine: the gate chain, the fan-out and the one delivery routine
(NOTIFICATIONS_AND_ALERTING.md §§ 3-8). notify() (core.notifications.api) only schedules; everything
fallible happens here, after the commit, in the worker (or, for a token-bearing purpose, in the
committing process, because a single-use link is never written to a table).

Gate chain, in order. Every stop is logged at DEBUG (purpose, channel, gate, outcome) and, once a
recipient is known, written to the delivery row (status=skipped, skip_reason=<gate>):

  1 platform_off       notifications.delivery.enabled is off
  3 matrix_off         the purpose x channel cell is off (mandatory purposes skip this gate)
  4 channel_unavailable the adapter says it is not configured
  5 no_route           a broadcast purpose has no active route on this channel
  6 no_recipient       the purpose resolves nobody
  7 opted_out          the user's preference is off (mandatory purposes skip this gate)
  8 test_routing       redirected to the tester (email) or held (in_app); never for a token purpose
                       in production
 11 recipient_inactive the user is gone or deactivated since notify() ran
  9 duplicate          the unique (purpose, channel, target, dedupe_key) row already exists; the
                       claim is LAST so a skip never consumes the dedupe key, and it fails closed
 12 provider           the channel's DeliveryResult
Not built (TECH_DEBT): 2 per-module master toggle, 10 budgets.
"""

import hashlib
import importlib
import json
import logging
from dataclasses import replace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import settings_service
from core.env import outbound_guard_active
from core.models import (
    NotificationDelivery,
    NotificationPreference,
    NotificationPurposeState,
    NotificationRoute,
    NotificationSetting,
)
from core.outbox import Delivery, Outcome, enqueue
from core.outbox.service import scrubbed
from core.registry import registry

from . import channels as ch

logger = logging.getLogger("core.notifications")

DISPATCH_TOPIC = "notifications.dispatch"
DELIVER_TOPIC = "notifications.deliver"
Status = NotificationDelivery.Status


def _debug(purpose, channel, gate, outcome):
    logger.debug(
        "core.notify.gate",
        extra={"purpose": purpose, "channel": channel, "gate": gate, "outcome": outcome},
    )


def load(path: str):
    module, _, attr = path.rpartition(".")
    return getattr(importlib.import_module(module), attr)


def adapter(channel_key: str):
    return load(registry.notification_channels.get(channel_key).adapter)


def sample_context(purpose) -> dict:
    return dict(load(purpose.preview)()) if purpose.preview else {}


def is_production() -> bool:
    return not outbound_guard_active(settings.APP_ENV)


# --- Matrix, preferences, test routing -----------------------------------------------------------


def matrix_enabled(purpose, channel: str) -> bool:
    row = NotificationSetting.objects.filter(purpose_code=purpose.code, channel=channel).first()
    return row.enabled if row is not None else channel in purpose.default_channels


def preference_enabled(user_id: int, purpose, channel: str) -> bool:
    """The user's row, then the system default row (user IS NULL), then the code default."""
    rows = {
        row.user_id: row.enabled
        for row in NotificationPreference.objects.filter(
            purpose_code=purpose.code, channel=channel, user_id__in=[user_id]
        )
    }
    if user_id in rows:
        return rows[user_id]
    system = NotificationPreference.objects.filter(
        purpose_code=purpose.code, channel=channel, user__isnull=True
    ).first()
    return system.enabled if system is not None else channel in purpose.default_channels


def test_routing_on(purpose) -> bool:
    """Seeded from `rollout`; flipped off by an admin, not by a deploy. A token-bearing purpose is
    never test-routed in production: that would hand the tester someone else's live link."""
    if purpose.carries_token and is_production():
        return False
    state = NotificationPurposeState.objects.filter(purpose_code=purpose.code).first()
    return state.test_routing if state is not None else purpose.rollout


def sync_matrix() -> dict:
    """Seed cells and test-routing state from code. Existing rows are NEVER overwritten (an
    admin's "off" survives every deploy); rows of a removed purpose or channel are deleted."""
    purposes = {p.code: p for p in registry.notification_purposes.purposes()}
    keys = {c.key for c in registry.notification_channels.channels()}
    added = 0
    for purpose in purposes.values():
        for key in keys:
            _, created = NotificationSetting.objects.get_or_create(
                purpose_code=purpose.code,
                channel=key,
                defaults={"enabled": key in purpose.default_channels},
            )
            added += created
        NotificationPurposeState.objects.get_or_create(
            purpose_code=purpose.code, defaults={"test_routing": purpose.rollout}
        )
    removed = NotificationSetting.objects.exclude(purpose_code__in=purposes).delete()[0]
    removed += NotificationSetting.objects.exclude(channel__in=keys).delete()[0]
    removed += NotificationPurposeState.objects.exclude(purpose_code__in=purposes).delete()[0]
    return {"added": added, "removed": removed}


# --- Planning: gates 1-11 ------------------------------------------------------------------------


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def resolve_recipients(purpose, recipients, object_ref, context) -> list:
    """User ids (int) and, from the purpose's own resolver only, addresses derived from the
    subject (str). The purpose resolves at dispatch time, so a reassignment between the save and
    the send reaches the right person."""
    if recipients is not None:
        return list(recipients)
    if purpose.recipients:
        return list(load(purpose.recipients)(object_ref, context))
    return []


def _targets(purpose, channel: str, recipients: list):
    """(recipient, route, address) triples for this channel, or a gate name when there are none."""
    if "broadcast" in purpose.audience and channel == "email":
        routes = NotificationRoute.objects.filter(
            purpose_code=purpose.code, channel=channel, is_active=True
        )
        out = [
            (None, route, address)
            for route in routes
            for address in route.target.get("addresses", [])
        ]
        if out:
            return out, ""
        if "user" not in purpose.audience:
            return [], "no_route"
    if "user" not in purpose.audience:
        return [], "no_route"
    out = []
    for item in recipients:
        if isinstance(item, int) and not isinstance(item, bool):
            out.append((item, None, ""))
        elif isinstance(item, str) and channel == "email":
            out.append((None, None, item))  # an address the purpose derived from its subject
    return out, "" if out else "no_recipient"


def _record_skip(purpose, channel, recipient_id, route, address, key, reason, object_ref, test):
    _debug(purpose.code, channel, reason, "skipped")
    return NotificationDelivery.objects.create(
        purpose_code=purpose.code,
        channel=channel,
        recipient_id=recipient_id,
        route=route,
        target={"address": address} if address and recipient_id is None else {},
        target_hash=_hash(key),
        object_ref=object_ref,
        status=Status.SKIPPED,
        skip_reason=reason,
        is_test=test,
    )


def plan(
    purpose,
    *,
    recipients=None,
    object_ref="",
    context=None,
    dedupe_key="",
    call_id="",
    is_test=False,
) -> list[NotificationDelivery]:
    """Run the gate chain and return the PENDING delivery rows (skips are written as rows too).
    `call_id` makes a re-run of the same notify() call find its own rows instead of adding more."""
    context = dict(context or {})
    if not settings_service.get_setting("notifications.delivery.enabled"):
        _debug(purpose.code, "*", "platform_off", "stopped")
        return []
    resolved = resolve_recipients(purpose, recipients, object_ref, context)
    pending = []
    candidates = [
        c.key
        for c in registry.notification_channels.channels()
        if (c.key in purpose.default_channels if purpose.mandatory else True)
    ]
    for channel in candidates:
        if not purpose.mandatory and not matrix_enabled(purpose, channel):
            _debug(purpose.code, channel, "matrix_off", "stopped")
            continue
        try:
            available = adapter(channel).available()
        except Exception:  # noqa: BLE001 — an adapter that cannot say is unavailable
            available = False
        if not available:
            _debug(purpose.code, channel, "channel_unavailable", "stopped")
            continue
        targets, gate = _targets(purpose, channel, resolved)
        if not targets:
            _debug(purpose.code, channel, gate, "stopped")
            continue
        intended = _labels(targets)
        for recipient_id, route, address in targets:
            row = _plan_one(
                purpose,
                channel,
                recipient_id,
                route,
                address,
                object_ref=object_ref,
                context=context,
                dedupe_key=dedupe_key,
                call_id=call_id,
                is_test=is_test,
                intended=intended,
            )
            if row is not None and row.status == Status.PENDING:
                pending.append(row)
    return pending


def _labels(targets) -> list[str]:
    """Who a test-routed message would have reached: addresses, never bare ids."""
    ids = [t[0] for t in targets if t[0] is not None]
    emails = dict(get_user_model().objects.filter(pk__in=ids).values_list("pk", "email"))
    return [t[2] or emails.get(t[0], f"user {t[0]}") for t in targets]


def _plan_one(
    purpose, channel, recipient_id, route, address, *, object_ref, context, dedupe_key, call_id,
    is_test, intended,
):  # fmt: skip
    key = f"user:{recipient_id}" if recipient_id else f"addr:{address}"
    skip = lambda reason: _record_skip(  # noqa: E731
        purpose, channel, recipient_id, route, address, key, reason, object_ref, is_test
    )
    user = None
    if recipient_id is not None:
        if not purpose.mandatory and not preference_enabled(recipient_id, purpose, channel):
            return skip("opted_out")
        user = get_user_model().objects.filter(pk=recipient_id, is_active=True).first()
        if user is None:
            return skip("recipient_inactive")
    store_context = {} if purpose.carries_token else {**context, "object_ref": object_ref}
    redirected = False
    if not is_test and test_routing_on(purpose):
        tester = settings_service.get_setting("notifications.delivery.test_recipient").strip()
        if channel != "email":
            return skip("test_routing")
        if not tester:
            return skip("test_routing_no_tester")
        redirected = True
        store_context["test_routing_intended"] = ", ".join(sorted(map(str, intended)))[:500]
        address, route, user = tester, None, user  # the user is kept for the template only
    dedupe = dedupe_key or (f"call:{call_id}" if call_id else "")
    fields = {
        "purpose_code": purpose.code,
        "channel": channel,
        "recipient_id": recipient_id,
        "route": route,
        "target": {"address": address} if address and (recipient_id is None or redirected) else {},
        "target_hash": _hash(key),
        "dedupe_key": dedupe,
        "object_ref": object_ref,
        "context": store_context,
        "is_test": is_test,
    }
    try:
        with transaction.atomic():
            return NotificationDelivery.objects.create(**fields)
    except IntegrityError:
        existing = NotificationDelivery.objects.filter(
            purpose_code=purpose.code, channel=channel, target_hash=fields["target_hash"],
            dedupe_key=dedupe,
        ).first()  # fmt: skip
        if existing is not None and call_id and dedupe == f"call:{call_id}":
            return existing  # this very call, run again: the same row, enqueued idempotently
        return skip("duplicate")
    except Exception:  # noqa: BLE001 — dedupe fails CLOSED: if the claim cannot be made, no send
        logger.exception("core.notify.dedupe_check_failed", extra={"purpose": purpose.code})
        return None


# --- Delivery: gate 12 ---------------------------------------------------------------------------


def _address_of(row, user):
    return (row.target or {}).get("address") or (user.email if user is not None else "")


def _outcome(row: NotificationDelivery, result) -> Outcome:
    """Record the provider's answer on the delivery row and map it to the outbox's outcome."""
    now = timezone.now()
    base = NotificationDelivery.objects.filter(pk=row.pk)
    if result.status == ch.ACCEPTED:
        base.update(status=Status.SENT, sent_at=now, provider_ref=result.ref[:200], error_code="")
        return Outcome.SENT(ref=result.ref)
    code = scrubbed(result.code)[:100]
    if result.status == ch.REJECTED:
        base.update(status=Status.FAILED, error_code=code)
        # The delivery log is the dead letter a human works; an outbox finding per bad address
        # would be noise (same choice as webhook deliveries).
        return Outcome.SKIPPED(code)
    if result.status == ch.RETRY:
        base.update(status=Status.PENDING, error_code=code)
        return Outcome.RETRY(after=result.after, code=code)
    base.update(status=Status.UNKNOWN, error_code=code)  # may have been accepted: never resent
    return Outcome.UNKNOWN(
        evidence={"delivery": row.pk, "purpose": row.purpose_code, "channel": row.channel},
        code=code,
    )


def send_delivery(row: NotificationDelivery, context: dict | None = None) -> Outcome:
    """Hand one PENDING row to its adapter. The row is marked `unknown` BEFORE the send, so a
    process that dies mid-send leaves the honest state (at-most-once, § 7); the answer then
    replaces it. `context` (in memory only) carries a token for a token-bearing purpose."""
    claimed = NotificationDelivery.objects.filter(pk=row.pk, status=Status.PENDING).update(
        status=Status.UNKNOWN, attempts=row.attempts + 1
    )
    if not claimed:
        return Outcome.SKIPPED("already_attempted")
    row.refresh_from_db()
    purpose = registry.notification_purposes.get(row.purpose_code)
    user = None
    if row.recipient_id is not None:
        user = get_user_model().objects.filter(pk=row.recipient_id, is_active=True).first()
        if user is None:
            NotificationDelivery.objects.filter(pk=row.pk).update(
                status=Status.SKIPPED, skip_reason="recipient_inactive"
            )
            return Outcome.SKIPPED("recipient_inactive")
    data = {**row.context, **(context or {}), "object_ref": row.object_ref}
    try:
        channel = adapter(row.channel)
        message = channel.render(
            purpose, data, recipient=user, address=_address_of(row, user), test=row.is_test
        )
    except Exception:  # noqa: BLE001 — an adapter never raises into its caller
        logger.exception("core.notify.render_failed", extra={"purpose": row.purpose_code})
        message = ch.DeliveryResult.rejected("adapter_error")
    if isinstance(message, ch.DeliveryResult):
        return _outcome(row, message)
    if row.context.get("test_routing_intended"):
        note = f"[Test routing] Would have reached: {row.context['test_routing_intended']}"
        message = replace(
            message,
            subject=f"[TEST ROUTED] {message.subject}",
            text=f"{note}\n\n{message.text}",
            html=f"<p>{_escape(note)}</p>{message.html}",
        )
    try:
        result = channel.send(message)
    except Exception:  # noqa: BLE001
        logger.exception("core.notify.send_failed", extra={"purpose": row.purpose_code})
        result = ch.DeliveryResult.unknown("adapter_error")
    return _outcome(row, result)


def _escape(text: str) -> str:
    from django.utils.html import escape

    return escape(text)


# --- Outbox handlers -----------------------------------------------------------------------------


def dispatch(message: Delivery) -> Outcome:
    """notifications.dispatch (at_least_once): resolve, run the gates, write one delivery row per
    recipient x channel and queue each (idempotent: a re-run adds nothing)."""
    payload = message.payload
    recipients = None
    if payload.get("recipients") != "*":
        recipients = [int(p) for p in str(payload.get("recipients", "")).split(",") if p]
    purpose = registry.notification_purposes.get(payload["purpose"])
    rows = plan(
        purpose,
        recipients=recipients,
        object_ref=payload.get("object_ref", ""),
        context=json.loads(payload.get("context") or "{}"),
        dedupe_key=payload.get("dedupe_key", ""),
        call_id=payload["call_id"],
    )
    for row in rows:
        with transaction.atomic():
            enqueue(
                DELIVER_TOPIC, dedupe_key=f"{DELIVER_TOPIC}:{row.pk}", payload={"delivery": row.pk}
            )
    return Outcome.SENT(ref=str(len(rows)))


def deliver(message: Delivery) -> Outcome:
    """notifications.deliver (at_most_once): one delivery row through its adapter."""
    row = NotificationDelivery.objects.filter(pk=message.payload["delivery"]).first()
    if row is None:
        return Outcome.SKIPPED("delivery_missing")
    return send_delivery(row)


# --- Send test (§ 6) -----------------------------------------------------------------------------


def send_test(purpose, *, actor, channel: str | None = None, route=None) -> list[dict]:
    """A synthetic [TEST] message through the REAL adapter (and so the mail guard), bypassing the
    matrix, preferences and test routing: it is a diagnostic, and says what the transport did."""
    context = sample_context(purpose)
    results = []
    if route is not None:
        pairs = [
            (route.channel, None, route, address) for address in route.target.get("addresses", [])
        ]
    else:
        keys = [channel] if channel else list(purpose.default_channels)
        pairs = [(key, actor, None, "") for key in keys]
    for key, recipient, row_route, address in pairs:
        row = NotificationDelivery.objects.create(
            purpose_code=purpose.code,
            channel=key,
            recipient=recipient,
            route=row_route,
            target={"address": address} if address else {},
            target_hash=_hash(f"test:{key}:{address or getattr(recipient, 'pk', '')}"),
            object_ref="",
            context={} if purpose.carries_token else context,
            is_test=True,
        )
        outcome = send_delivery(row, context=context)
        row.refresh_from_db()
        results.append({"channel": key, "status": row.status, "error_code": outcome.code or ""})
    return results
