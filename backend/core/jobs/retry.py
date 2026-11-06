"""
One retry policy (JOBS_AND_INTEGRATIONS.md § 10), for tasks, the outbox, webhooks and the HTTP
client alike: classify, then retry; exponential with full jitter, capped; Retry-After honoured;
always bounded.

`max_attempts` counts EVERY attempt, the first included. A policy that counted only the retries
would make one more call than declared, or (the off-by-one seen in production) never reach its
last backoff step.
"""

import random
from dataclasses import dataclass

# Retryable HTTP answers: the server's fault (5xx) and the three "try again later" 4xx. Every other
# 4xx is permanent: retrying a 400 or a 403 five times only repeats the refusal.
RETRYABLE_4XX = frozenset({408, 425, 429})


def is_retryable_status(status: int) -> bool:
    return status in RETRYABLE_4XX or 500 <= status <= 599


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_seconds: float = 30
    factor: float = 4
    cap_seconds: float = 3600

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts counts the first attempt: it is at least 1")
        if self.base_seconds < 0 or self.factor < 1 or self.cap_seconds < 0:
            raise ValueError("base_seconds and cap_seconds are >= 0 and factor is >= 1")

    def next_delay(
        self, attempt: int, retry_after: float | None = None, *, rand=random.random
    ) -> float | None:
        """
        Seconds to wait after attempt number `attempt` (1 = the first) failed, or None when no
        attempt remains. Full jitter: uniform in [0, min(cap, base * factor^(attempt-1))], so
        clients that failed together do not retry together. A Retry-After from upstream is
        honoured as given, capped at `cap_seconds`.
        """
        if attempt < 1:
            raise ValueError("attempt numbers start at 1")
        if attempt >= self.max_attempts:
            return None
        if retry_after is not None:
            return min(max(float(retry_after), 0.0), self.cap_seconds)
        ceiling = min(self.cap_seconds, self.base_seconds * self.factor ** (attempt - 1))
        return rand() * ceiling

    def is_transient(self, exc: BaseException) -> bool:
        """
        Worth another attempt? Database operational errors, connection resets and timeouts, an
        exception that says so (`transient = True`, the provider errors of § 20 set it), or one
        carrying a retryable HTTP `status_code`. Everything else is permanent and fails now.
        """
        from django.db import OperationalError

        explicit = getattr(exc, "transient", None)
        if isinstance(explicit, bool):
            return explicit
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            return is_retryable_status(status)
        return isinstance(exc, (OperationalError, ConnectionError, TimeoutError))


DEFAULT_RETRY = RetryPolicy()
OUTBOX_DEFAULT_RETRY = RetryPolicy(max_attempts=5, base_seconds=60, factor=5, cap_seconds=3600)
