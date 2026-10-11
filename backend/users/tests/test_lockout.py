"""Progressive lockout over users_login_attempt (AUTH_BLUEPRINT § 6.2 step 2, A17)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from users.models import LoginAttempt
from users.services import lockout

pytestmark = pytest.mark.django_db

VICTIM, IP = "victim@example.com", "203.0.113.7"
THRESHOLD, WINDOW, DURATION = 10, 900, 900  # settings_test pins these


def attempt(identifier=VICTIM, ip=IP, *, ago, succeeded=False, reason="bad_password"):
    """A LoginAttempt `ago` seconds old. created_at is auto_now_add, so it is set afterwards."""
    row = LoginAttempt.objects.create(
        identifier=identifier,
        ip=ip,
        succeeded=succeeded,
        failure_reason="" if succeeded else reason,
    )
    LoginAttempt.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - timedelta(seconds=ago)
    )


def burst(n, *, latest_ago, spacing=10, **kwargs):
    """n failures, `spacing` seconds apart, the newest `latest_ago` seconds old."""
    for i in range(n):
        attempt(ago=latest_ago + i * spacing, **kwargs)


def test_settings_are_the_ones_these_tests_assume(settings):
    assert (settings.LOCKOUT_THRESHOLD, settings.LOCKOUT_WINDOW, settings.LOCKOUT_DURATION) == (
        THRESHOLD,
        WINDOW,
        DURATION,
    )


# --- Identifier ---------------------------------------------------------------------------------


def test_one_under_the_threshold_is_not_locked():
    burst(THRESHOLD - 1, latest_ago=1)
    assert not lockout.is_locked(VICTIM, IP)


def test_the_threshold_locks_from_any_ip():
    burst(THRESHOLD, latest_ago=1)
    assert lockout.is_locked(VICTIM, IP)
    assert lockout.is_locked(VICTIM, "198.51.100.1")
    assert lockout.is_locked(VICTIM, None)
    assert not lockout.is_locked("someone-else@example.com", "198.51.100.1")


def test_a_success_resets_the_identifier_count():
    burst(THRESHOLD - 1, latest_ago=20)
    attempt(ago=15, succeeded=True)
    burst(THRESHOLD - 1, latest_ago=1)  # 18 failures in all, but only 9 since the success
    assert not lockout.is_locked(VICTIM, IP)


def test_a_success_before_the_burst_does_not_reset_it():
    attempt(ago=500, succeeded=True)
    burst(THRESHOLD, latest_ago=1)
    assert lockout.is_locked(VICTIM, IP)


def test_the_lock_expires_duration_after_the_latest_failure():
    burst(THRESHOLD, latest_ago=DURATION - 5)
    assert lockout.is_locked(VICTIM, IP)
    LoginAttempt.objects.all().delete()
    burst(THRESHOLD, latest_ago=DURATION + 5)
    assert not lockout.is_locked(VICTIM, IP)


def test_the_window_is_measured_across_the_burst_not_back_from_now():
    # 10 failures spread over 810s, the newest 200s ago. Measured back from now, the oldest has
    # aged out of the window and the lock would already have lifted after 90s.
    burst(THRESHOLD, latest_ago=200, spacing=90)
    assert lockout.is_locked(VICTIM, IP)


def test_failures_further_apart_than_the_window_do_not_lock():
    burst(THRESHOLD, latest_ago=1, spacing=WINDOW // (THRESHOLD - 1) + 1)
    assert not lockout.is_locked(VICTIM, IP)


def test_attempts_made_while_locked_do_not_extend_the_lock():
    burst(THRESHOLD, latest_ago=DURATION + 5)
    for ago in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
        attempt(ago=ago, reason=LoginAttempt.FailureReason.LOCKED)
    assert not lockout.is_locked(VICTIM, IP)


# --- IP -----------------------------------------------------------------------------------------


def _spray(n, *, ip=IP):
    """n failures from one IP, each against a different address: no identifier gets near a lock."""
    for i in range(n):
        attempt(identifier=f"target{i}@example.com", ip=ip, ago=1 + i)


def test_the_ip_threshold_is_five_times_the_identifier_threshold():
    _spray(THRESHOLD * 5 - 1)
    assert not lockout.is_locked("fresh@example.com", IP)
    attempt(identifier="one-more@example.com", ago=0)
    assert lockout.is_locked("fresh@example.com", IP)
    assert not lockout.is_locked("fresh@example.com", "198.51.100.1")


def test_a_success_does_not_reset_an_ip():
    _spray(THRESHOLD * 5 - 1)
    attempt(identifier="real-user@example.com", ago=0, succeeded=True)
    attempt(identifier="one-more@example.com", ago=0)
    assert lockout.is_locked("fresh@example.com", IP)


def test_no_ip_means_only_the_identifier_is_checked():
    _spray(THRESHOLD * 5)
    assert not lockout.is_locked("fresh@example.com", None)


# --- Progressive (A17) --------------------------------------------------------------------------


def test_a_first_lock_lasts_the_base_duration():
    burst(THRESHOLD, latest_ago=DURATION + 100)
    assert not lockout.is_locked(VICTIM, IP)


def test_a_second_lock_within_24h_lasts_twice_as_long():
    burst(THRESHOLD, latest_ago=5 * 3600)  # an earlier lock, hours ago
    burst(THRESHOLD, latest_ago=DURATION + 100)
    assert lockout.is_locked(VICTIM, IP)  # 2 × 900s, so still locked at 1000s


def test_a_lock_older_than_24h_does_not_count_towards_doubling():
    burst(THRESHOLD, latest_ago=25 * 3600)
    burst(THRESHOLD, latest_ago=DURATION + 100)
    assert not lockout.is_locked(VICTIM, IP)


def test_the_duration_doubles_and_is_capped_at_24h():
    assert lockout._duration(0) == timedelta(seconds=DURATION)  # k ≥ 1
    assert lockout._duration(1) == timedelta(seconds=DURATION)
    assert lockout._duration(2) == timedelta(seconds=DURATION * 2)
    assert lockout._duration(3) == timedelta(seconds=DURATION * 4)
    assert lockout._duration(10) == timedelta(hours=24)
    assert lockout._duration(10_000) == timedelta(hours=24)  # no overflow on an attacker's k
