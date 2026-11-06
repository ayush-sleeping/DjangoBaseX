"""One retry policy (JOBS_AND_INTEGRATIONS.md § 10)."""

import pytest
from django.db import OperationalError

from core.jobs.retry import RetryPolicy, is_retryable_status

POLICY = RetryPolicy(max_attempts=5, base_seconds=10, factor=3, cap_seconds=100)


def test_delays_grow_and_respect_the_cap():
    top = [POLICY.next_delay(n, rand=lambda: 1.0) for n in range(1, 5)]
    assert top == [10, 30, 90, 100]


def test_delays_are_fully_jittered():
    assert POLICY.next_delay(3, rand=lambda: 0.0) == 0
    assert POLICY.next_delay(3, rand=lambda: 0.5) == 45
    assert len({POLICY.next_delay(3) for _ in range(50)}) > 1


def test_max_attempts_counts_the_first_attempt():
    # Five attempts in all: a delay after each of the first four, none after the fifth.
    assert [POLICY.next_delay(n) is None for n in range(1, 7)] == [False] * 4 + [True] * 2
    assert RetryPolicy(max_attempts=1).next_delay(1) is None


def test_retry_after_is_honoured_and_capped():
    assert POLICY.next_delay(1, retry_after=42) == 42
    assert POLICY.next_delay(1, retry_after=10_000) == 100
    assert POLICY.next_delay(1, retry_after=-3) == 0
    assert POLICY.next_delay(5, retry_after=1) is None  # still bounded


def test_attempt_numbers_start_at_one():
    with pytest.raises(ValueError):
        POLICY.next_delay(0)
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)


class Http(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (OperationalError("server closed the connection"), True),
        (ConnectionResetError(), True),
        (TimeoutError(), True),
        (Http(503), True),
        (Http(429), True),
        (Http(408), True),
        (Http(425), True),
        (Http(400), False),
        (Http(403), False),
        (Http(404), False),
        (ValueError("bad input"), False),
        (type("Declared", (Exception,), {"transient": True})(), True),
        (type("Declared", (ConnectionError,), {"transient": False})(), False),
    ],
)
def test_only_transient_failures_are_retried(exc, transient):
    assert POLICY.is_transient(exc) is transient


def test_retryable_statuses():
    assert [s for s in (200, 400, 408, 409, 425, 429, 500, 599, 600) if is_retryable_status(s)] == [
        408,
        425,
        429,
        500,
        599,
    ]
