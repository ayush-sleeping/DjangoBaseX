"""manage.py auth_cleanup: retention for the auth tables (AUTH_BLUEPRINT § 19.2, BUILD_ORDER 1.7).

Boundaries use a one-hour margin either side of the cutoff: the test's clock and the command's are
a few milliseconds apart, and an hour is far from both.
"""

import secrets
import uuid
from datetime import timedelta
from io import StringIO

import pytest
from django.apps import apps
from django.core.management import CommandError, call_command
from django.utils import timezone

from tests.factories import UserFactory
from users.models import LoginAttempt, UserSession
from users.models.password_reset import PasswordResetToken

pytestmark = pytest.mark.django_db

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
ATTEMPTS, SESSIONS, TOKENS = 90, 30, 7  # settings_test pins these
CLEANED = {"users_login_attempt", "users_user_session", "users_password_reset_token"}


def cleanup(*args) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("auth_cleanup", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def ago(delta: timedelta):
    return timezone.now() - delta


def attempt(age: timedelta) -> LoginAttempt:
    row = LoginAttempt.objects.create(identifier="x@example.com", succeeded=False)
    LoginAttempt.objects.filter(pk=row.pk).update(created_at=ago(age))
    return row


def session(user, *, expires_at, revoked_at=None) -> UserSession:
    now = timezone.now()
    return UserSession.objects.create(
        user=user,
        jti=secrets.token_hex(32),
        family_id=uuid.uuid4(),
        issued_at=min(now, expires_at) - DAY,
        expires_at=expires_at,
        last_seen_at=min(now, expires_at) - HOUR,
        revoked_at=revoked_at,
        revoked_reason="logout" if revoked_at else "",
    )


def reset_token(user, *, expires_at, used_at=None) -> PasswordResetToken:
    return PasswordResetToken.objects.create(
        user=user, token_hash=secrets.token_hex(32), expires_at=expires_at, used_at=used_at
    )


def exists(row) -> bool:
    return type(row).objects.filter(pk=row.pk).exists()


def test_the_settings_are_the_ones_these_tests_assume(settings):
    assert (
        settings.LOGIN_ATTEMPT_RETENTION_DAYS,
        settings.SESSION_RETENTION_DAYS,
        settings.PASSWORD_RESET_TOKEN_RETENTION_DAYS,
    ) == (ATTEMPTS, SESSIONS, TOKENS)


# --- users_login_attempt ------------------------------------------------------------------------


def test_login_attempts_older_than_retention_go_and_newer_stay():
    inside = attempt(ATTEMPTS * DAY - HOUR)
    outside = attempt(ATTEMPTS * DAY + HOUR)
    fresh = attempt(timedelta(0))
    out, _ = cleanup()
    assert exists(inside) and exists(fresh)
    assert not exists(outside)
    assert "deleted 1 from users_login_attempt" in out


# --- users_user_session -------------------------------------------------------------------------


def test_sessions_expired_beyond_retention_go_and_recently_expired_stay():
    user = UserFactory()
    inside = session(user, expires_at=ago(SESSIONS * DAY - HOUR))
    outside = session(user, expires_at=ago(SESSIONS * DAY + HOUR))
    cleanup()
    assert exists(inside)
    assert not exists(outside)


def test_sessions_revoked_beyond_retention_go_once_their_token_has_expired():
    user = UserFactory()
    inside = session(user, revoked_at=ago(SESSIONS * DAY - HOUR), expires_at=ago(DAY))
    outside = session(user, revoked_at=ago(SESSIONS * DAY + HOUR), expires_at=ago(DAY))
    cleanup()
    assert exists(inside)
    assert not exists(outside)


def test_a_revoked_session_whose_token_still_verifies_is_kept_for_reuse_detection():
    # Revoked long ago, but its refresh token has not expired: a replay of it must still find this
    # row, so refresh can say "reuse detected" and revoke the family.
    user = UserFactory()
    row = session(user, revoked_at=ago(SESSIONS * DAY + DAY), expires_at=timezone.now() + DAY)
    cleanup()
    assert exists(row)


@pytest.mark.parametrize("issued_days_ago", [1, 45, 400])
def test_live_sessions_survive_whatever_their_age(issued_days_ago):
    user = UserFactory()
    row = session(user, expires_at=timezone.now() + HOUR)
    UserSession.objects.filter(pk=row.pk).update(
        issued_at=ago(issued_days_ago * DAY), last_seen_at=ago(issued_days_ago * DAY)
    )
    cleanup()
    assert exists(row)
    assert row in UserSession.objects.live()


# --- users_password_reset_token -----------------------------------------------------------------


def test_reset_tokens_used_beyond_retention_go_and_recently_used_stay():
    user = UserFactory()
    later = timezone.now() + HOUR  # not expired: only used_at decides
    inside = reset_token(user, used_at=ago(TOKENS * DAY - HOUR), expires_at=later)
    outside = reset_token(user, used_at=ago(TOKENS * DAY + HOUR), expires_at=later)
    cleanup()
    assert exists(inside)
    assert not exists(outside)


def test_reset_tokens_expired_beyond_retention_go_and_recently_expired_stay():
    user = UserFactory()
    inside = reset_token(user, expires_at=ago(TOKENS * DAY - HOUR))
    outside = reset_token(user, expires_at=ago(TOKENS * DAY + HOUR))
    cleanup()
    assert exists(inside)
    assert not exists(outside)


def test_an_outstanding_reset_token_is_never_deleted():
    user = UserFactory()
    row = reset_token(user, expires_at=timezone.now() + HOUR)
    PasswordResetToken.objects.filter(pk=row.pk).update(created_at=ago(365 * DAY))
    cleanup()
    assert exists(row)


# --- --dry-run (the 1.7 done-when) --------------------------------------------------------------


def test_dry_run_reports_every_count_and_deletes_nothing():
    user = UserFactory()
    attempt(ATTEMPTS * DAY + HOUR)
    attempt(ATTEMPTS * DAY + DAY)
    session(user, expires_at=ago(SESSIONS * DAY + HOUR))
    reset_token(user, expires_at=ago(TOKENS * DAY + HOUR))
    before = (LoginAttempt.objects.count(), UserSession.objects.count())

    out, _ = cleanup("--dry-run")

    assert out.splitlines() == [
        "would delete 2 from users_login_attempt",
        "would delete 1 from users_user_session",
        "would delete 1 from users_password_reset_token",
    ]
    assert (LoginAttempt.objects.count(), UserSession.objects.count()) == before
    assert PasswordResetToken.objects.count() == 1


def test_a_real_run_prints_one_line_per_table():
    out, _ = cleanup()
    assert out.splitlines() == [
        "deleted 0 from users_login_attempt",
        "deleted 0 from users_user_session",
        "deleted 0 from users_password_reset_token",
    ]


# --- Batching -----------------------------------------------------------------------------------


def test_small_batches_still_delete_everything_and_count_it_once():
    for _ in range(5):
        attempt(ATTEMPTS * DAY + DAY)
    keep = attempt(timedelta(0))
    out, _ = cleanup("--batch-size", "2")
    assert "deleted 5 from users_login_attempt" in out
    assert list(LoginAttempt.objects.values_list("pk", flat=True)) == [keep.pk]


def test_a_batch_size_below_one_is_refused():
    with pytest.raises(CommandError, match="at least 1"):
        cleanup("--batch-size", "0")


# --- Clamping -----------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, -5])
def test_a_retention_below_one_day_is_clamped_with_a_warning(settings, value):
    settings.LOGIN_ATTEMPT_RETENTION_DAYS = value
    today = attempt(timedelta(hours=12))
    yesterday = attempt(DAY + HOUR)
    _, err = cleanup()
    assert f"LOGIN_ATTEMPT_RETENTION_DAYS={value} is below 1; using 1 day" in err
    assert exists(today)
    assert not exists(yesterday)


@pytest.mark.parametrize("name", ["SESSION_RETENTION_DAYS", "PASSWORD_RESET_TOKEN_RETENTION_DAYS"])
def test_every_retention_setting_is_clamped(settings, name):
    setattr(settings, name, 0)
    _, err = cleanup("--dry-run")
    assert f"{name}=0 is below 1" in err


# --- Nothing else -------------------------------------------------------------------------------


def _row_counts() -> dict[str, int]:
    return {
        model._meta.db_table: model.objects.count()
        for model in apps.get_models()
        if model._meta.db_table not in CLEANED and model._meta.managed
    }


def test_no_other_table_is_touched():
    old_user = UserFactory(is_active=False)
    UserFactory()
    # Old rows everywhere this command cleans, owned by a user that must itself survive.
    attempt(ATTEMPTS * DAY + DAY)
    session(old_user, expires_at=ago(SESSIONS * DAY + DAY))
    reset_token(old_user, expires_at=ago(TOKENS * DAY + DAY))
    before = _row_counts()
    assert before["users_user"] == 2 and before.get("rbac_role", 0) > 0  # the snapshot is real

    cleanup()

    assert _row_counts() == before
    assert exists(old_user)
