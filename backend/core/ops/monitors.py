"""
Scheduled monitors (§ 19): the registered doctors, run on a schedule, reporting through
incidents.sync and the dispatcher. A monitor that finds a problem worked, so the job returns
normally (exit 0); `manage.py doctor --strict` is for humans and CI. A doctor that could not check
(it raised) is its own misconfiguration alert, and its incidents are left alone: syncing nothing
for it would recover everything it knew.
"""

from core import doctors
from core.registry import FAILURE

from . import dispatcher, incidents
from .kinds import AlertKind, Problem

INFRA = {"queue.stalled", "queue.no_consumer"}
MISCONFIG = ("queue.config.", "schedule.conflict", "schedule.not_synced")
QUEUE_SOURCES = {"queue", "outbox"}


def kind_for(code: str) -> AlertKind:
    """Which policy row a finding falls under; anything not named here waits for the digest."""
    if code in INFRA:
        return AlertKind.INFRA_OUTAGE
    if code.startswith(MISCONFIG):
        return AlertKind.MISCONFIGURATION
    return AlertKind.DEGRADED


def run(selected=None) -> int:
    """Run the doctors once; returns the number of current problems found."""
    from core import settings_service

    from .settings import IncidentPolicy

    policy = settings_service.resolve(IncidentPolicy)
    total = 0
    for doctor in selected if selected is not None else doctors.select():
        result = doctors.run_doctor(doctor)
        if result.crashed:
            dispatcher.alert(
                f"monitor:{doctor.key}:crashed",
                source="monitor",
                reason="doctor_crashed",
                title=f"Monitor could not check: {doctor.key}",
                body=result.findings[0].message if result.findings else "",
                kind=AlertKind.MISCONFIGURATION,
            )
            continue
        problems = {
            f"{f.code}:{f.subject}": Problem(
                label=f"{f.code} {f.subject}: {f.message}"[:300],
                kind=kind_for(f.code),
                body=f.remedy,
            )
            for f in result.findings
            if f.severity == FAILURE and not f.code.startswith("doctor.")
        }
        minutes = (
            policy.queue_confirm_after_minutes
            if doctor.key in QUEUE_SOURCES
            else policy.confirm_after_minutes
        )
        incidents.sync(doctor.key, problems, confirm_after_minutes=minutes)
        total += len(problems)
    return total
