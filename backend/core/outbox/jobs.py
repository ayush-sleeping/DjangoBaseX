"""The outbox's own registrations (BUILD_ORDER 7.3), made from core's ready()."""

from core.registry import (
    Doctor,
    FindingKind,
    Interval,
    JobSpec,
    ReconcilerSpec,
)

from .service import DRAIN_JOB, FAILED_KIND, UNKNOWN_KIND

QUEUE = "outbox"

DRAIN = JobSpec(
    name=DRAIN_JOB,
    func="core.outbox.service.drain_job",
    owner_module="core",
    description=(
        "Claims due outbox messages (SKIP LOCKED), sends each through its topic's handler and "
        "records the result. If it stops, nothing the outbox owes is sent: email, webhooks and "
        "every other side effect queue up silently (doctor --only outbox)."
    ),
    queue=QUEUE,
    schedule=Interval(30),
    expires=25,
    # Row claims are the concurrency control: several drainers at once is the point.
    single_flight=False,
    idempotent=True,  # a redelivered run claims only what is still due
    time_limit=300,
    soft_time_limit=270,
    unit="messages",
)

RECOVER = ReconcilerSpec(
    name="core.outbox_recover",
    reconciler="core.outbox.recovery.LeaseRecovery",
    model="core.OutboxMessage",
    states=("leased",),
    owner_module="core",
    description=(
        "Moves outbox messages whose lease expired (a drainer died mid-send) to unknown or retry, "
        "per topic semantics. If it stops, those messages stay leased forever: never sent, never "
        "reported."
    ),
    schedule=Interval(120),
    queue=QUEUE,
)

KINDS = (
    FindingKind(
        kind=UNKNOWN_KIND,
        label="Outbox message may or may not have been sent",
        severity="critical",
        owner_module="core",
        resolutions=("marked_sent", "resent", "dismissed"),
        runbook="documentation/system-design/JOBS_AND_INTEGRATIONS.md#12-the-transactional-outbox",
    ),
    FindingKind(
        kind=FAILED_KIND,
        label="Outbox message failed permanently",
        severity="warning",
        owner_module="core",
        resolutions=("resent", "dismissed"),
        runbook="documentation/system-design/JOBS_AND_INTEGRATIONS.md#12-the-transactional-outbox",
    ),
)


def register(registry) -> None:
    from .doctor import outbox_doctor

    for kind in KINDS:
        registry.finding_kinds.register(kind)
    registry.jobs.register(DRAIN)
    registry.reconcilers.register(RECOVER)
    registry.doctors.register(
        Doctor(
            key="outbox",
            fn=outbox_doctor,
            owner="core",
            description="Outbox handlers import; no message stuck, unsendable or left leased; "
            "unknown and failed messages awaiting a human (JOBS_AND_INTEGRATIONS.md § 12).",
        )
    )
