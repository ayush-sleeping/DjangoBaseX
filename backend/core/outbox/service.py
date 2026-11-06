"""
The outbox's moving parts (JOBS_AND_INTEGRATIONS.md § 12).

enqueue()  in the caller's transaction: a rollback leaves no row, a duplicate dedupe_key no
           second row (ON CONFLICT DO NOTHING).
claim()    one due row: SELECT … FOR UPDATE SKIP LOCKED, stamp the lease (status, leased_until,
           locked_by = a fresh token, attempts += 1), COMMIT. Two drainers never claim one row.
deliver()  call the topic's handler OUTSIDE any transaction; never raises.
settle()   write the result by compare-and-set on (id, locked_by, status=leased). If the lease
           was lost meanwhile (recovery moved the row on), the result is not written over it:
           only a late SENT for a row recovery marked unknown/retry under the same token is
           accepted, because it settles exactly the question the human was asked.

A worker killed between claim and settle leaves the row `leased`. Nothing here ever touches an
expired lease: core.outbox_recover (core.outbox.recovery) does, as its own job, so a wedged
drainer cannot also stop recovery.
"""

import logging
import os
import secrets
import socket
import time
from dataclasses import dataclass, replace
from datetime import timedelta
from types import MappingProxyType

from celery.exceptions import SoftTimeLimitExceeded
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.models import F
from django.utils import timezone

from core import findings
from core.jobs.retry import OUTBOX_DEFAULT_RETRY
from core.jobs.runner import resolve_path
from core.observability.scrub import default_rules
from core.registry import AT_LEAST_ONCE, registry

from .outcome import FAILED, RETRY, SENT, SKIPPED, UNKNOWN, Delivery, Outcome, ProviderNotConfigured

logger = logging.getLogger("core.outbox")

DRAIN_JOB = "core.outbox_drain"
UNKNOWN_KIND, FAILED_KIND = "outbox.unknown", "outbox.failed"
OBJECT_TYPE = "core.outboxmessage"
MAX_ERROR_LENGTH = 1000
# A drain run stops CLAIMING after this long; the job's time limit stays well above it.
DRAIN_BUDGET_SECONDS = 120
PRIMITIVES = (int, str, bool, type(None))


def _rows():
    from core.models import OutboxMessage

    return OutboxMessage.objects


def _topics(topics=None):
    return registry.outbox_topics if topics is None else topics


def policy_of(spec):
    return spec.retry or OUTBOX_DEFAULT_RETRY


def next_delay(spec, attempt: int, max_attempts: int, retry_after=None) -> float | None:
    """The topic's backoff, bounded by the ROW's max_attempts (a resend narrows it to one more
    attempt). None: no attempt remains, the message is dead-lettered."""
    policy = replace(policy_of(spec), max_attempts=max(1, max_attempts))
    return policy.next_delay(max(1, attempt), retry_after)


def scrubbed(text: str) -> str:
    """Provider errors can carry recipients, URLs and tokens: never stored raw (§ 12)."""
    return default_rules().scrub_text(str(text))[:MAX_ERROR_LENGTH]


def scrubbed_evidence(evidence: dict) -> dict:
    """Evidence goes into a finding a human reads: its strings are scrubbed like error messages.
    Its shape (str keys, primitive values) was checked when the Outcome was built."""
    return {
        key: scrubbed(value) if isinstance(value, str) else value for key, value in evidence.items()
    }


# --- Enqueue ------------------------------------------------------------------------------------


def enqueue(
    topic: str,
    *,
    dedupe_key: str,
    payload: dict | None = None,
    delay_seconds: float = 0,
    using: str = DEFAULT_DB_ALIAS,
    topics=None,
) -> None:
    """
    Owe the world a message, in the same transaction as the change that decided it. Outside
    transaction.atomic() this raises: a row written after the commit is only a slower .delay().
    `dedupe_key` names the logical message (f"{topic}:{aggregate}:{version}"); enqueueing it
    twice is a no-op. The payload is ids and scalars: the handler re-reads current state.
    """
    if not connections[using].in_atomic_block:
        raise RuntimeError(
            "outbox.enqueue() must run inside the business change's transaction.atomic() "
            "(JOBS_AND_INTEGRATIONS.md § 12)"
        )
    spec = _topics(topics).get(topic)  # unregistered → KeyError, a programming error
    if not isinstance(dedupe_key, str) or not dedupe_key or len(dedupe_key) > 255:
        raise ValueError("dedupe_key is a non-empty string of at most 255 characters")
    payload = dict(payload or {})
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, PRIMITIVES):
            raise TypeError(
                f"outbox payload {key!r} is a {type(value).__name__}: pass the id, not the object"
            )
    from core.models import OutboxMessage

    _rows().using(using).bulk_create(
        [
            OutboxMessage(
                topic=topic,
                dedupe_key=dedupe_key,
                payload=payload,
                max_attempts=policy_of(spec).max_attempts,
                next_attempt_at=timezone.now() + timedelta(seconds=delay_seconds),
            )
        ],
        ignore_conflicts=True,  # ON CONFLICT DO NOTHING on the unique dedupe_key
    )
    if not delay_seconds:
        _kick_after_commit(topic, using)


def _kick_after_commit(topic: str, using: str) -> None:
    """For latency only: one drain kick per topic per transaction. The 30 s drainer is the
    guarantee, so a broker that is down costs a delay, never a message."""
    for _savepoints, callback, _robust in connections[using].run_on_commit:
        if getattr(callback, "outbox_topic", None) == topic:
            return

    def kick_outbox_drain() -> None:
        from core.jobs import enqueue as enqueue_job

        enqueue_job(DRAIN_JOB, topic=topic)

    kick_outbox_drain.outbox_topic = topic
    transaction.on_commit(kick_outbox_drain, using=using, robust=True)


# --- Claim, deliver, settle ---------------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    id: int
    token: str
    topic: str
    dedupe_key: str
    payload: dict
    attempt: int
    max_attempts: int  # the ROW's cap: a deliberate resend narrows it to one more attempt


def lease_token() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(6)}"[:100]


# A claimer that loses a stamp race moves on to the next row; this bounds how often in one call.
CLAIM_RACE_RETRIES = 10


def _candidate(topic_names, now, exclude):
    """The next due row. FOR UPDATE SKIP LOCKED on PostgreSQL; on SQLite the lock is ignored,
    which is why the stamp below is a compare-and-set either way."""
    return (
        _rows()
        .due(now)
        .filter(topic__in=list(topic_names))
        .exclude(pk__in=exclude)
        .order_by("next_attempt_at", "id")
        .select_for_update(skip_locked=True)
        .first()
    )


def claim(topic_names, *, now=None, topics=None) -> Claim | None:
    """Lease one due message of `topic_names` and COMMIT the lease before anything is sent."""
    topics = _topics(topics)
    now = now or timezone.now()
    lost: list[int] = []
    for _ in range(CLAIM_RACE_RETRIES):
        with transaction.atomic():
            row = _candidate(topic_names, now, lost)
            if row is None:
                return None
            token = lease_token()
            lease = timedelta(seconds=topics.get(row.topic).lease_seconds)
            # Compare-and-set: only a row that is still due is stamped. Another claimer that read
            # the same row (SQLite, or any engine without the row lock) gets 0 and moves on.
            stamped = (
                _rows()
                .filter(pk=row.pk, status__in=("pending", "retry"))
                .update(
                    status="leased",
                    leased_until=now + lease,
                    locked_by=token,
                    attempts=F("attempts") + 1,
                )
            )
            if not stamped:
                lost.append(row.pk)
                continue
            attempt, max_attempts = (
                _rows().filter(pk=row.pk).values_list("attempts", "max_attempts").get()
            )
        return Claim(
            row.pk, token, row.topic, row.dedupe_key, dict(row.payload), attempt, max_attempts
        )
    return None


def deliver(claimed: Claim, *, topics=None) -> Outcome:
    """Run the topic's handler. Never raises an Exception: it becomes an Outcome (§ 12)."""
    spec = _topics(topics).get(claimed.topic)
    delivery = Delivery(
        id=claimed.id,
        topic=claimed.topic,
        dedupe_key=claimed.dedupe_key,
        payload=MappingProxyType(dict(claimed.payload)),
        attempt=claimed.attempt,
    )
    try:
        outcome = resolve_path(spec.handler)(delivery)
    except ProviderNotConfigured:
        return Outcome.SKIPPED("not_configured")
    except Exception as exc:  # noqa: BLE001 — the handler contract: an escape is an Outcome
        code, message = type(exc).__name__[:100], scrubbed(exc)
        if spec.semantics == AT_LEAST_ONCE:
            # The worker's soft time limit interrupted the send: that is transient by definition.
            if isinstance(exc, SoftTimeLimitExceeded) or policy_of(spec).is_transient(exc):
                return Outcome.RETRY(code=code, message=message)
            return Outcome.FAILED(code, message)
        # at_most_once: the provider may have accepted it before the failure. A human decides.
        return Outcome.UNKNOWN({"exception": code}, code=code, message=message)
    if not isinstance(outcome, Outcome):
        code = "handler_returned_" + type(outcome).__name__
        if spec.semantics == AT_LEAST_ONCE:
            return Outcome.RETRY(code=code[:100])
        return Outcome.UNKNOWN({"returned": type(outcome).__name__}, code=code[:100])
    return outcome


def _open(kind: str, msg_id: int, details: dict) -> None:
    findings.raise_or_touch(kind, object_type=OBJECT_TYPE, object_id=msg_id, details=details)


def settle(claimed: Claim, outcome: Outcome, *, now=None, topics=None) -> str:
    """Write the result if the lease still holds. Returns the status the row ended in, or
    "lease_lost" when the result was not written."""
    spec = _topics(topics).get(claimed.topic)
    now = now or timezone.now()
    status = outcome.status
    values = {"leased_until": None}
    error = {"last_error_code": outcome.code[:100], "last_error_message": scrubbed(outcome.message)}
    if status == SENT:
        values |= {"sent_at": now, "result_ref": outcome.ref[:255], **dict.fromkeys(error, "")}
    elif status == SKIPPED:
        values |= error
    elif status == RETRY:
        delay = next_delay(spec, claimed.attempt, claimed.max_attempts, outcome.after)
        if delay is None:  # attempts exhausted: the dead letter, which a human can see
            status = FAILED
        else:
            values["next_attempt_at"] = now + timedelta(seconds=delay)
        values |= error
    elif status in (FAILED, UNKNOWN):
        values |= error
    else:
        raise ValueError(f"unknown outcome status {status!r}")
    with transaction.atomic():
        written = (
            _rows()
            .filter(pk=claimed.id, locked_by=claimed.token, status="leased")
            .update(status=status, **values)
        )
        if written and status == FAILED:
            _open(
                FAILED_KIND,
                claimed.id,
                {"code": error["last_error_code"], "attempts": claimed.attempt},
            )
        elif written and status == UNKNOWN:
            _open(
                UNKNOWN_KIND,
                claimed.id,
                {
                    "code": error["last_error_code"],
                    "attempt": claimed.attempt,
                    "evidence": scrubbed_evidence(outcome.evidence),
                },
            )
    if not written:
        return _late(claimed, outcome, now)
    logger.info(
        "core.outbox.settled",
        extra={"message_id": claimed.id, "topic": claimed.topic, "status": status},
    )
    return status


def _late(claimed: Claim, outcome: Outcome, now) -> str:
    """
    The lease was lost: recovery moved the row on. Accept only a SENT for a row recovery parked
    under OUR token (unknown, retry, or failed when its attempts were spent): it answers exactly the
    question the parked state asks, and its findings close with it. Anything else is dropped.
    """
    if outcome.status == SENT:
        with transaction.atomic():
            accepted = (
                _rows()
                .filter(pk=claimed.id, locked_by=claimed.token, status__in=(UNKNOWN, RETRY, FAILED))
                .update(
                    status=SENT,
                    sent_at=now,
                    result_ref=outcome.ref[:255],
                    leased_until=None,
                    last_error_code="",
                    last_error_message="",
                )
            )
            if accepted:
                for kind in (UNKNOWN_KIND, FAILED_KIND):
                    findings.clear(kind, object_type=OBJECT_TYPE, object_id=claimed.id)
        if accepted:
            logger.warning(
                "core.outbox.late_sent_accepted",
                extra={"message_id": claimed.id, "topic": claimed.topic},
            )
            return SENT
    logger.warning(
        "core.outbox.late_result_dropped",
        extra={"message_id": claimed.id, "topic": claimed.topic, "outcome": outcome.status},
    )
    return "lease_lost"


# --- The drain job ------------------------------------------------------------------------------


def drain(ctx=None, *, topic: str | None = None, topics=None, clock=time.monotonic) -> int:
    """Claim, send, settle, one message at a time, until nothing is due, the batch is done or
    the budget is spent. Returns how many messages it settled."""
    topics = _topics(topics)
    if topic is not None:
        if topic not in topics:
            logger.warning("core.outbox.unregistered_topic", extra={"topic": topic})
            return 0
        selected = (topics.get(topic),)
    else:
        selected = topics.topics()
    if not selected:
        return 0
    names = [spec.topic for spec in selected]
    limit = sum(spec.batch_size for spec in selected)
    deadline = clock() + DRAIN_BUDGET_SECONDS
    done = 0
    while done < limit and clock() < deadline:
        if ctx is not None and ctx.stop_requested():
            break
        claimed = claim(names, topics=topics)
        if claimed is None:
            break
        outcome = deliver(claimed, topics=topics)
        settle(claimed, outcome, topics=topics)
        done += 1
        if outcome.code == "SoftTimeLimitExceeded":
            break  # the worker asked us to stop; this message is settled, the rest wait
    return done


def drain_job(ctx) -> int:
    """core.outbox_drain: every 30 s, and kicked after each enqueueing commit."""
    topic = ctx.params.get("topic")
    return drain(ctx, topic=topic if isinstance(topic, str) and topic else None)


# --- A human's resolution of an `unknown` message -----------------------------------------------


def resolve_unknown(message_id: int, action: str, *, actor=None, note: str = "") -> bool:
    """
    The two decisions § 12 leaves to a human. "mark_sent": the provider did accept it.
    "resend": send it again, deliberately, with exactly one more attempt. Either resolves the open
    outbox.unknown finding. False when the message is not `unknown` any more.
    """
    from core.models import Finding

    if action not in ("mark_sent", "resend"):
        raise ValueError('action is "mark_sent" or "resend"')
    now = timezone.now()
    with transaction.atomic():
        rows = _rows().filter(pk=message_id, status=UNKNOWN)
        if action == "mark_sent":
            changed = rows.update(status=SENT, sent_at=now, leased_until=None)
            resolution = "marked_sent"
        else:
            changed = rows.update(
                status=RETRY,
                next_attempt_at=now,
                leased_until=None,
                max_attempts=F("attempts") + 1,
            )
            resolution = "resent"
        if not changed:
            return False
        for finding in Finding.objects.open().of(UNKNOWN_KIND, OBJECT_TYPE, str(message_id)):
            findings.resolve(finding, resolution, note, actor)
    return True
