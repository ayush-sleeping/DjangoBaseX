"""Single-use password-reset tokens (AUTH_BLUEPRINT § 3.4)."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class PasswordResetTokenQuerySet(models.QuerySet):
    def outstanding(self):
        return self.filter(used_at__isnull=True, expires_at__gt=timezone.now())


class PasswordResetToken(models.Model):
    """
    A table, not Django's stateless token generator: a row is what makes a link single-use, lets a
    password change invalidate every other outstanding link, and leaves a trail when an account is
    taken over through the reset flow.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_reset_tokens"
    )
    # SHA-256 of the token. The plaintext is emailed and never stored.
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = PasswordResetTokenQuerySet.as_manager()

    class Meta:
        db_table = "users_password_reset_token"

    def __str__(self):
        return f"reset token for user {self.user_id}"
