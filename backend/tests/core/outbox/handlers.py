"""Outbox handlers the tests register. Real functions, so dbx.jobs.E030 can resolve them."""

from core.outbox import Outcome, ProviderNotConfigured

CALLS: list[int] = []


class WorkerKilled(BaseException):
    """Raised mid-send. A BaseException, like the process vanishing: no result is ever written."""


def sends(delivery):
    CALLS.append(delivery.id)
    return Outcome.SENT(ref=f"provider-{delivery.id}")


def dies_mid_send(delivery):
    CALLS.append(delivery.id)
    raise WorkerKilled


def leaks_a_secret(delivery):
    CALLS.append(delivery.id)
    raise ConnectionError(
        "upstream said 502: password=hunter2 for postgres://app:s3cretpw@db/app to jo@example.com"
    )


def permanent_error(delivery):
    CALLS.append(delivery.id)
    raise ValueError("the payload is wrong")


def not_configured(delivery):
    CALLS.append(delivery.id)
    raise ProviderNotConfigured("no SMS provider is configured")


def checks_suppression(delivery):
    """Re-validates at claim time: the suppression list changes between enqueue and send."""
    CALLS.append(delivery.id)
    if delivery.payload.get("suppressed"):
        return Outcome.SKIPPED("recipient_suppressed")
    return Outcome.SENT(ref="ok")


def returns_nonsense(delivery):
    CALLS.append(delivery.id)
    return "sent, honest"
