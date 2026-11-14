"""
The one ops alert dispatcher and its ledger (§ 14). The ONLY module here that imports notify():
monitors, incidents, the digest and the quiet-hours release all talk to operators through it
(tests/architecture/test_monitors_use_the_dispatcher.py).

Every call writes one core_ops_alert row with its decision. `sent` means handed to notify(); the
delivery log (core_notification_delivery) holds what the provider said. Nothing here reads the
cache. The dispatcher never raises into its caller: its own failure is logged at ERROR and written
to the ledger as skipped:dispatch_error (§ 21), so a broken alert path is visible, not silent.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from core import findings
from core.models import OpsAlert
from core.notifications import notify

from . import policy
from .kinds import (
    NOTICE_STORM,
    PURPOSE_ALERT,
    PURPOSE_DIGEST,
    SKIP_DISPATCH_ERROR,
    SKIP_NO_DESTINATION,
    AlertKind,
)

logger = logging.getLogger("core.ops")
Decision = OpsAlert.Decision
NO_DESTINATION_KIND = "ops.no_destination"


def _context(title: str, body: str) -> dict:
    return {"title": title[:200], "body": body}


def _record(**fields) -> OpsAlert:
    fields["title"] = fields["title"][:200]
    fields["subject_key"] = fields["subject_key"][:255]
    return OpsAlert.objects.create(**fields)


def _send(row: OpsAlert, purpose: str = PURPOSE_ALERT) -> None:
    notify(purpose, context=_context(row.title, row.body), dedupe_key=f"ops-alert:{row.pk}")


def alert(
    subject_key: str,
    *,
    source: str,
    reason: str,
    title: str,
    body: str = "",
    kind: str = AlertKind.DEGRADED,
    event: str = "problem",
) -> policy.Outcome:
    """Report one problem (event="problem") or its recovery (event="recovered"). `subject_key`
    names the problem, not the check run (`queue:billing:stalled`), so repeats dedupe."""
    kind = str(kind)
    try:
        outcome = policy.decide(kind, subject_key, event)
        row = _record(
            source=source,
            reason=reason,
            kind=kind,
            event=event,
            subject_key=subject_key,
            title=title,
            body=body,
            decision=outcome.decision,
            decision_reason=outcome.reason,
        )
        if outcome.reason == SKIP_NO_DESTINATION:
            _report_no_destination()
        else:
            findings.clear(NO_DESTINATION_KIND, object_type="ops", object_id="alert_route")
        if outcome.decision == Decision.SENT:
            try:
                _send(row)
            except Exception:  # noqa: BLE001 — an alert path that fails must say so, not vanish
                logger.exception("core.ops.dispatch_failed", extra={"subject_key": subject_key})
                OpsAlert.objects.filter(pk=row.pk).update(
                    decision=Decision.SKIPPED, decision_reason=SKIP_DISPATCH_ERROR
                )
                return policy.Outcome(Decision.SKIPPED, SKIP_DISPATCH_ERROR)
        elif outcome.reason == "storm_cap":
            _storm_notice()
        return outcome
    except Exception:  # noqa: BLE001 — never raise into a monitor; surface at ERROR (§ 21)
        logger.exception("core.ops.alert_failed", extra={"subject_key": subject_key})
        return policy.Outcome(Decision.SKIPPED, SKIP_DISPATCH_ERROR)


def _report_no_destination() -> None:
    logger.error("core.ops.no_destination", extra={"purpose": PURPOSE_ALERT})
    findings.raise_or_touch(
        NO_DESTINATION_KIND,
        object_type="ops",
        object_id="alert_route",
        title="Ops alerts have no destination",
        details={"purpose": PURPOSE_ALERT},
    )


def notice(subject_key: str, *, reason: str, title: str, body: str) -> OpsAlert:
    """A message the dispatcher itself composes (storm notice, quiet-hours summary): always sent,
    ledgered, and not counted against the storm cap (its kind is not on the allow-list)."""
    row = _record(
        source="ops",
        reason=reason,
        kind=AlertKind.DEGRADED,
        subject_key=subject_key,
        title=title,
        body=body,
        decision=Decision.SENT,
    )
    _send(row)
    return row


def send_digest(run, title: str, body: str) -> None:
    """Hand one digest to notify(); the run's id is the dedupe key (a re-run adds nothing)."""
    notify(PURPOSE_DIGEST, context=_context(title, body), dedupe_key=f"ops-digest:{run.pk}")


def _storm_notice() -> None:
    since = timezone.now() - timedelta(hours=1)
    if OpsAlert.objects.filter(reason=NOTICE_STORM, created_at__gte=since).exists():
        return
    held = OpsAlert.objects.filter(decision_reason="storm_cap", created_at__gte=since).count()
    notice(
        "ops:storm",
        reason=NOTICE_STORM,
        title=f"Alert storm: {held} held",
        body=f"{held} alert(s) were held for the digest because the instant cap was reached.",
    )
