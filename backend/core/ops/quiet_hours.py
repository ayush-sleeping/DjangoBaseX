"""Quiet hours and digest slots, in the configured timezone (§ 16, § 18). Evaluated per call, on
the local wall clock, so a window across midnight and a DST change need no special case."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from core import settings_service

from .settings import AlertPolicy


def policy() -> AlertPolicy:
    return settings_service.resolve(AlertPolicy)


def zone(p: AlertPolicy | None = None) -> ZoneInfo:
    p = p or policy()
    return ZoneInfo(p.timezone or settings_service.get_setting("platform.timezone"))


def _clock(text: str) -> time:
    hour, minute = text.split(":")
    return time(int(hour), int(minute))


def in_quiet_hours(now: datetime | None = None, p: AlertPolicy | None = None) -> bool:
    p = p or policy()
    if not p.quiet_start or not p.quiet_end:
        return False  # opt-in: empty means off
    start, end = _clock(p.quiet_start), _clock(p.quiet_end)
    if start == end:
        return False  # a zero-length window is never open
    local = (now or timezone.now()).astimezone(zone(p)).time().replace(second=0, microsecond=0)
    return start <= local < end if start < end else (local >= start or local < end)


def window_label(p: AlertPolicy | None = None) -> str:
    p = p or policy()
    return f"{p.quiet_start}–{p.quiet_end}"


def _slots(now: datetime, p: AlertPolicy) -> list[datetime]:
    """Every digest time on yesterday, today and tomorrow (local), as aware datetimes, sorted."""
    tz = zone(p)
    today = now.astimezone(tz).date()
    return sorted(
        datetime.combine(today + timedelta(days=offset), _clock(text), tzinfo=tz)
        for offset in (-1, 0, 1)
        for text in p.digest_times
    )


def latest_slot(now: datetime, p: AlertPolicy | None = None) -> datetime:
    """The most recent digest time at or before `now` (UTC)."""
    p = p or policy()
    return max(s for s in _slots(now, p) if s <= now).astimezone(ZoneInfo("UTC"))


def next_slot(now: datetime, p: AlertPolicy | None = None) -> datetime:
    p = p or policy()
    return min(s for s in _slots(now, p) if s > now).astimezone(ZoneInfo("UTC"))
