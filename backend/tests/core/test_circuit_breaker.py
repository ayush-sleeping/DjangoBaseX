"""Per-target circuit breaking (JOBS_AND_INTEGRATIONS.md § 19). The mixin is abstract, so its
methods run on a plain stand-in: no table, no migration."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from core.breaker import DEFAULT_BREAKER, BreakerPolicy, CircuitBreakerMixin

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def target(**values):
    fields = dict(failure_count=0, next_attempt_at=None, last_failure_at=None, last_error_code="")
    stub = SimpleNamespace(
        **(fields | values),
        breaker_policy=DEFAULT_BREAKER,
        BREAKER_FIELDS=CircuitBreakerMixin.BREAKER_FIELDS,
    )
    for name in ("record_failure", "record_success", "backoff_text"):
        setattr(stub, name, getattr(CircuitBreakerMixin, name).__get__(stub))
    return stub


def test_threshold_then_doubling_then_cap():
    policy = BreakerPolicy()
    assert [policy.backoff(n) for n in (1, 2)] == [None, None]  # a blip benches nothing
    assert [policy.backoff(n) for n in (3, 4, 5, 6)] == [timedelta(hours=h) for h in (1, 2, 4, 8)]
    assert policy.backoff(9) == timedelta(hours=24) and policy.backoff(500) == timedelta(hours=24)


def test_failures_back_the_target_off():
    t = target()
    for _ in range(3):
        t.record_failure("timeout", now=NOW, save=False)
    assert (t.failure_count, t.next_attempt_at, t.last_error_code) == (
        3,
        NOW + timedelta(hours=1),
        "timeout",
    )
    assert t.backoff_text(NOW) == "backed off until 2026-11-06 13:00 UTC after 3 failures (timeout)"


def test_success_resets():
    t = target(failure_count=7, next_attempt_at=NOW + timedelta(hours=8), last_error_code="dns")
    t.record_success(save=False)
    assert (t.failure_count, t.next_attempt_at, t.last_error_code) == (0, None, "")
    assert t.backoff_text(NOW) == ""


def test_manual_refresh_ignores_backoff():
    """A scheduled sweep asks due_for_sweep(); a human-triggered refresh never does, so a
    backed-off target is still callable on demand, and a success clears the backoff."""
    from core.breaker import BreakerQuerySet

    assert "due_for_sweep" in dir(BreakerQuerySet)
    t = target(failure_count=5, next_attempt_at=NOW + timedelta(hours=4))
    t.record_success(save=False)  # the manual refresh worked
    assert t.next_attempt_at is None


def test_a_save_writes_only_the_breaker_fields():
    saved = []
    t = target()
    t.save = lambda update_fields: saved.append(update_fields)
    t.record_failure("x", now=NOW)
    t.record_success()
    assert saved == [list(CircuitBreakerMixin.BREAKER_FIELDS)] * 2
