"""
The ops digest (§ 16) and the quiet-hours release (§ 18).

One message per run: a header count, every held alert, every open incident, the next digest time,
and an explicit all-clear line when there is nothing. "Since the last sent digest" is the ledger:
held alerts stay unreleased until a digest that carried them is SETTLED as sent or unknown, so a
digest that did not arrive rolls its contents into the next. notify() is asynchronous, so a run
is `pending` until the delivery log answers; settle() reads that answer at the start of every run.
"""

import logging
from datetime import datetime, timedelta

from django.utils import timezone

from core.models import Incident, NotificationDelivery, OpsAlert, OpsDigestRun

from . import dispatcher, quiet_hours
from .kinds import HELD_DIGEST, HELD_QUIET, HELD_STORM, NOTICE_QUIET, PURPOSE_DIGEST

logger = logging.getLogger("core.ops")
Run = OpsDigestRun.Status
# A pending digest the outbox never delivered is given up on after this long, so its alerts roll
# into the next digest instead of waiting forever.
PENDING_GIVE_UP = timedelta(hours=1)


def _local(value: datetime, p) -> str:
    return value.astimezone(quiet_hours.zone(p)).strftime("%H:%M")


def _age(since: datetime, now: datetime) -> str:
    minutes = int((now - since).total_seconds() // 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def settle(now: datetime | None = None) -> int:
    """Settle every pending digest from the delivery log. Returns how many were settled."""
    now = now or timezone.now()
    settled = 0
    for run in OpsDigestRun.objects.filter(status=Run.PENDING):
        statuses = set(
            NotificationDelivery.objects.filter(
                purpose_code=PURPOSE_DIGEST, dedupe_key=f"ops-digest:{run.pk}"
            ).values_list("status", flat=True)
        )
        if "pending" in statuses:
            continue
        if "sent" in statuses:
            outcome = Run.SENT
        elif "unknown" in statuses:
            outcome = Run.UNKNOWN  # may have arrived: never resent (at-most-once, § 7)
        elif statuses or now - run.created_at >= PENDING_GIVE_UP:
            outcome = Run.FAILED
        else:
            continue  # the outbox has not dispatched it yet
        OpsDigestRun.objects.filter(pk=run.pk).update(status=outcome, settled_at=now)
        carried = OpsAlert.objects.filter(digest_run=run)
        if outcome == Run.FAILED:
            carried.update(digest_run=None)  # back to held: they roll into the next digest
            logger.error("core.ops.digest_failed", extra={"run": run.pk})
        else:
            carried.update(released_at=now, released_via="digest")
        settled += 1
    return settled


def _compose(held, incidents, now: datetime, p) -> tuple[str, str]:
    last = OpsDigestRun.objects.filter(status__in=(Run.SENT, Run.UNKNOWN)).order_by("-id").first()
    nxt = f"Next digest {_local(quiet_hours.next_slot(now, p), p)}."
    if not held and not incidents:
        since = f" since {_local(last.slot_at, p)}" if last else ""
        return f"Ops digest: all clear{since}", f"All clear{since}. {nxt}"
    lines = []
    if incidents:
        lines.append("Open incidents:")
        lines += [f"- {i.label} (open {_age(i.first_seen_at, now)})" for i in incidents]
        lines.append("")
    if held:
        lines.append("Held since the last digest:")
        lines += [
            f"- {a.title}"
            + (" (recovered)" if a.event == "recovered" else "")
            + (f": {a.body}" if a.body else "")
            for a in held
        ]
        lines.append("")
    lines.append(nxt)
    title = f"Ops digest: {len(held)} held alert(s), {len(incidents)} open incident(s)"
    return title, "\n".join(lines)


def run_digest(now: datetime | None = None) -> int:
    """Send the digest if one is due. Returns the number of held alerts it carried."""
    now = now or timezone.now()
    settle(now)
    p = quiet_hours.policy()
    if quiet_hours.in_quiet_hours(now, p):
        return 0
    slot = quiet_hours.latest_slot(now, p)
    if OpsDigestRun.objects.filter(
        slot_at=slot, status__in=(Run.PENDING, Run.SENT, Run.UNKNOWN)
    ).exists():
        return 0
    held = list(
        OpsAlert.objects.filter(
            decision=OpsAlert.Decision.HELD,
            decision_reason__in=(HELD_DIGEST, HELD_STORM),
            released_at__isnull=True,
            digest_run__isnull=True,
        ).order_by("id")
    )
    incidents = list(Incident.objects.filter(status=Incident.Status.OPEN).order_by("first_seen_at"))
    # An open incident is listed under "Open incidents"; its own opening alert is not listed twice.
    open_keys = {f"incident:{i.source}:{i.key}"[:255] for i in incidents}
    shown = [a for a in held if not (a.event == "problem" and a.subject_key in open_keys)]
    title, body = _compose(shown, incidents, now, p)
    run = OpsDigestRun.objects.create(
        slot_at=slot, held_count=len(shown), incident_count=len(incidents)
    )
    OpsAlert.objects.filter(pk__in=[a.pk for a in held]).update(digest_run=run)
    try:
        dispatcher.send_digest(run, title, body)
    except Exception:  # noqa: BLE001 — a failed hand-off gives the alerts back, loudly
        logger.exception("core.ops.digest_failed", extra={"run": run.pk})
        OpsDigestRun.objects.filter(pk=run.pk).update(status=Run.FAILED, settled_at=now)
        OpsAlert.objects.filter(digest_run=run).update(digest_run=None)
        return 0
    return len(held)


def release_quiet(now: datetime | None = None) -> int:
    """After quiet hours end: ONE summary of what was held inside the window. Returns the count."""
    now = now or timezone.now()
    p = quiet_hours.policy()
    if quiet_hours.in_quiet_hours(now, p):
        return 0
    held = list(
        OpsAlert.objects.filter(
            decision=OpsAlert.Decision.HELD, decision_reason=HELD_QUIET, released_at__isnull=True
        ).order_by("id")
    )
    if not held:
        return 0
    opened = {a.subject_key for a in held if a.event == "problem"}
    recovered = {a.subject_key for a in held if a.event == "recovered"}
    lines = []
    for alert in held:
        if alert.event == "recovered" and alert.subject_key in opened:
            continue  # shown on its problem's line
        note = ""
        if alert.subject_key in opened & recovered:
            note = " (opened and recovered while it was quiet)"
        elif alert.event == "recovered":
            note = " (recovered)"
        lines.append(f"- {alert.title}{note}" + (f": {alert.body}" if alert.body else ""))
    dispatcher.notice(
        "ops:quiet_summary",
        reason=NOTICE_QUIET,
        title=f"While it was quiet ({quiet_hours.window_label(p)}): {len(held)} alert(s) held",
        body="\n".join(lines),
    )
    OpsAlert.objects.filter(pk__in=[a.pk for a in held]).update(
        released_at=now, released_via="quiet_summary"
    )
    return len(held)
