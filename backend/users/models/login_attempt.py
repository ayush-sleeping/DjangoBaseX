"""Every login attempt, for throttling and forensics (AUTH_BLUEPRINT § 3.3)."""

from django.conf import settings
from django.db import models


class LoginAttempt(models.Model):
    class FailureReason(models.TextChoices):
        BAD_PASSWORD = "bad_password"
        UNKNOWN_USER = "unknown_user"
        INACTIVE = "inactive"
        MFA_FAILED = "mfa_failed"
        LOCKED = "locked"

    # The submitted address, lowercased. Deliberately not a foreign key: the attempts worth
    # recording are the ones against addresses that do not exist.
    identifier = models.CharField(max_length=254, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")
    succeeded = models.BooleanField(db_index=True)
    failure_reason = models.CharField(
        max_length=32, blank=True, default="", choices=FailureReason.choices
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "users_login_attempt"
        indexes = [
            models.Index(fields=["identifier", "created_at"], name="users_attempt_ident_time"),
            models.Index(fields=["ip", "created_at"], name="users_attempt_ip_time"),
        ]

    def __str__(self):
        outcome = "ok" if self.succeeded else self.failure_reason
        return f"login {self.identifier} {outcome}"
