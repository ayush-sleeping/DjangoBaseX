"""
Retention for the three auth tables that grow forever (AUTH_BLUEPRINT § 19.2; BUILD_ORDER 1.7).

A management command run by cron: there is no scheduler in Phase 1. It deletes ONLY:

  users_login_attempt         created_at older than LOGIN_ATTEMPT_RETENTION_DAYS
  users_user_session          dead sessions (see _dead_sessions), SESSION_RETENTION_DAYS after
                              they stopped working; a live session is never touched
  users_password_reset_token  used or expired, PASSWORD_RESET_TOKEN_RETENTION_DAYS after that

Never users, invitations, rbac, or the audit trail: core_activity_log is append-only (§ 3.12).
Deletes run in batches, each its own short transaction, so a table grown by an attack is never
held under one long lock.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from users.models import LoginAttempt, UserSession
from users.models.password_reset import PasswordResetToken

DEFAULT_BATCH_SIZE = 5000
# Lockout reads the last 24 hours of login attempts (users.services.lockout), so even a clamped
# retention keeps it working.
MINIMUM_DAYS = 1


class Command(BaseCommand):
    help = (
        "Delete expired auth records: old login attempts, dead sessions, used or expired reset "
        "tokens. --dry-run reports the counts and deletes nothing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Count what would go; delete nothing."
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Rows per delete transaction (default {DEFAULT_BATCH_SIZE}).",
        )

    def handle(self, *args, dry_run, batch_size, **options):
        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1.")
        now = timezone.now()

        attempts_cutoff = now - self._retention("LOGIN_ATTEMPT_RETENTION_DAYS")
        sessions_cutoff = now - self._retention("SESSION_RETENTION_DAYS")
        tokens_cutoff = now - self._retention("PASSWORD_RESET_TOKEN_RETENTION_DAYS")

        plan = [
            (LoginAttempt, LoginAttempt.objects.filter(created_at__lt=attempts_cutoff)),
            (UserSession, _dead_sessions(sessions_cutoff, now)),
            (
                PasswordResetToken,
                PasswordResetToken.objects.filter(
                    Q(used_at__lt=tokens_cutoff) | Q(expires_at__lt=tokens_cutoff)
                ),
            ),
        ]
        for model, queryset in plan:
            table = model._meta.db_table
            if dry_run:
                self.stdout.write(f"would delete {queryset.count()} from {table}")
            else:
                count = _delete_in_batches(model, queryset, batch_size)
                self.stdout.write(f"deleted {count} from {table}")

    def _retention(self, name: str) -> timedelta:
        days = getattr(settings, name)
        if days < MINIMUM_DAYS:
            self.stderr.write(
                self.style.WARNING(
                    f"{name}={days} is below {MINIMUM_DAYS}; using {MINIMUM_DAYS} day. "
                    "A retention of 0 would delete every row, including today's."
                )
            )
            days = MINIMUM_DAYS
        return timedelta(days=days)


def _dead_sessions(cutoff, now):
    """
    A session that stopped working before `cutoff`, and whose refresh token can no longer verify.

    Expired before the cutoff: gone. Revoked before the cutoff: gone only once its token has also
    expired. A revoked token that has not expired is exactly the one a thief replays, and its row
    is what lets refresh recognise the replay and revoke the whole family (§ 6.3). Deleting it
    early would turn "reuse detected, family revoked" into a plain "unknown token".
    Live sessions (not revoked, not expired) match neither branch, whatever their age.
    """
    return UserSession.objects.filter(
        Q(expires_at__lt=cutoff) | Q(revoked_at__lt=cutoff, expires_at__lt=now)
    )


def _delete_in_batches(model, queryset, batch_size: int) -> int:
    """Primary keys first, then a delete by key: each batch is one short transaction."""
    deleted = 0
    label = model._meta.label
    while True:
        batch = list(queryset.order_by("pk").values_list("pk", flat=True)[:batch_size])
        if not batch:
            return deleted
        _, per_model = model.objects.filter(pk__in=batch).delete()
        removed = per_model.get(label, 0)
        if removed == 0:  # someone else deleted them first; never spin
            return deleted
        deleted += removed
