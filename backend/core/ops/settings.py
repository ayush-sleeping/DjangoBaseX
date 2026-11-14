"""operations.alerts.* and operations.incidents.* (§§ 14-18). Registered by registration.py."""

import re
from dataclasses import dataclass, field
from zoneinfo import available_timezones

from core.settings_registry import Bool, Int, String, StrList, meta

CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class ClockTime(String):
    """ "HH:MM" (24 h), or empty where the setting says empty means off."""

    max_length: int = 5
    name = "clock_time"

    def parse(self, value):
        value = super().parse(value)
        if value and not CLOCK.match(value):
            raise ValueError('must be "HH:MM" (24 hour) or empty')
        return value


@dataclass(frozen=True)
class ClockTimes(StrList):
    name = "clock_times"

    def parse(self, value):
        items = super().parse(value)
        if not items:
            raise ValueError("needs at least one time, or held alerts would never be sent")
        bad = [v for v in items if not CLOCK.match(v)]
        if bad:
            raise ValueError(f'must be "HH:MM" (24 hour), not {", ".join(bad)}')
        return items


@dataclass(frozen=True)
class ZoneOrEmpty(String):
    """An IANA timezone name, or empty to follow the platform timezone."""

    max_length: int = 64
    name = "timezone_or_empty"

    def parse(self, value):
        value = super().parse(value)
        if value and value not in available_timezones():
            raise ValueError("must be an IANA timezone name, or empty for the platform timezone")
        return value


def _meta(type_, label, description, event, used_by=("core.ops dispatcher",)):
    return meta(
        type_, label=label, description=description, changed_by_event=event, used_by=used_by
    )


def _cooldown(kind: str, default: int):
    return field(
        default=default,
        metadata=_meta(
            Int(min=1, max=10080),
            f"Cooldown for {kind.replace('_', ' ')} alerts (minutes)",
            f"A {kind.replace('_', ' ')} alert for the same problem is not sent again inside this "
            "window. Read from the ledger, so a deploy or cache clear cannot re-announce it.",
            "A problem that is announced too often, or a recurrence that is missed",
        ),
    )


@dataclass(frozen=True)
class AlertPolicy:
    enabled: bool = field(
        default=True,
        metadata=_meta(
            Bool(),
            "Send ops alerts",
            "Off: every alert is recorded as skipped (disabled) and nothing reaches operators.",
            "Silencing a known incident, or maintenance",
        ),
    )
    max_instant_per_hour: int = field(
        default=6,
        metadata=_meta(
            Int(min=1, max=1000),
            "Instant alerts per hour (storm cap)",
            "Beyond this many instant sends in an hour the rest are held for the digest, and one "
            '"alert storm" message is sent.',
            "An outage that fans out into many alerts",
        ),
    )
    cooldown_minutes_regression: int = _cooldown("regression", 360)
    cooldown_minutes_infra_outage: int = _cooldown("infra_outage", 30)
    cooldown_minutes_misconfiguration: int = _cooldown("misconfiguration", 360)
    cooldown_minutes_deploy_breakage: int = _cooldown("deploy_breakage", 1440)
    cooldown_minutes_first_sighting: int = _cooldown("first_sighting", 1440)
    digest_times: tuple = field(
        default=("09:00", "17:00"),
        metadata=_meta(
            ClockTimes(),
            "Ops digest times",
            'When the ops digest is sent, "HH:MM" in the alert timezone. One message per time; '
            "it says all clear when nothing is held.",
            "Moving the digest to when operators are at their desks",
            used_by=("ops.alert_digest",),
        ),
    )
    quiet_start: str = field(
        default="",
        metadata=_meta(
            ClockTime(),
            "Quiet hours start",
            'Nothing is sent to operators from this time ("HH:MM") until quiet hours end; held '
            "alerts are released as one summary afterwards. Empty start or end: quiet hours off.",
            "On-call hours change, or alerts arrive at night with nobody to read them",
            used_by=("core.ops quiet hours", "ops.release_held"),
        ),
    )
    quiet_end: str = field(
        default="",
        metadata=_meta(
            ClockTime(),
            "Quiet hours end",
            'The time ("HH:MM") quiet hours end. A window may cross midnight (22:00 to 07:00).',
            "On-call hours change",
            used_by=("core.ops quiet hours", "ops.release_held"),
        ),
    )
    timezone: str = field(
        default="",
        metadata=_meta(
            ZoneOrEmpty(),
            "Alert timezone",
            "The zone quiet hours and digest times are read in. Empty: the platform timezone.",
            "Operators in a different zone from the platform's",
            used_by=("core.ops quiet hours", "ops.alert_digest"),
        ),
    )


@dataclass(frozen=True)
class IncidentPolicy:
    confirm_after_minutes: int = field(
        default=0,
        metadata=_meta(
            Int(min=0, max=1440),
            "Minutes a problem must persist before it is announced",
            "A problem that clears inside this window is never announced. 0 announces at once.",
            "A flapping check that announces and recovers repeatedly",
            used_by=("incidents.sync",),
        ),
    )
    queue_confirm_after_minutes: int = field(
        default=10,
        metadata=_meta(
            Int(min=0, max=1440),
            "Minutes a queue problem must persist before it is announced",
            "As above, for the queue and outbox doctors, whose findings flicker with load.",
            "Queue depth that spikes and recovers on its own",
            used_by=("ops.monitor",),
        ),
    )
