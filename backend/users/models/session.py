"""One row per issued refresh token: the table that makes JWT revocable (AUTH_BLUEPRINT § 3.2)."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserSessionQuerySet(models.QuerySet):
    def live(self):
        return self.filter(revoked_at__isnull=True, expires_at__gt=timezone.now())

    def for_user(self, user):
        return self.filter(user=user)


class UserSession(models.Model):
    class RevokedReason(models.TextChoices):
        LOGOUT = "logout"
        ROTATED = "rotated"
        REUSE_DETECTED = "reuse_detected"
        PASSWORD_CHANGED = "password_changed"
        ADMIN = "admin"
        EXPIRED = "expired"

    # The id the API exposes (A15). The access token carries it as `sid`.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions"
    )
    # SHA-256 of the refresh token's jti. The plaintext only ever exists in the cookie.
    jti = models.CharField(max_length=64, unique=True)
    # Constant across one login's rotation chain; reuse anywhere in it revokes all of it.
    family_id = models.UUIDField(db_index=True)
    parent_jti = models.CharField(max_length=64, blank=True, default="")
    replaced_by_jti = models.CharField(max_length=64, blank=True, default="")
    issued_at = models.DateTimeField(db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField()
    password_confirmed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_reason = models.CharField(
        max_length=32, blank=True, default="", choices=RevokedReason.choices
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")
    device_label = models.CharField(max_length=64, blank=True, default="")

    objects = UserSessionQuerySet.as_manager()

    class Meta:
        db_table = "users_user_session"
        indexes = [models.Index(fields=["user", "revoked_at"], name="users_session_user_revoked")]

    def __str__(self):
        return f"session {self.public_id} for user {self.user_id}"

    @property
    def is_live(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()
