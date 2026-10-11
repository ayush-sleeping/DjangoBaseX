"""Invitations: the route to a new account (AUTH_BLUEPRINT § 3.5)."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class InvitationQuerySet(models.QuerySet):
    def live(self):
        """Not accepted and not revoked (expiry aside): what the one-per-address rule counts."""
        return self.filter(accepted_at__isnull=True, revoked_at__isnull=True)


class Invitation(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email = models.EmailField(max_length=254, db_index=True)  # lowercased by the service
    # By string: users never imports rbac's models (Ch. 2). PROTECT: a role with pending
    # invitations cannot be deleted out from under them.
    role = models.ForeignKey("rbac.Role", on_delete=models.PROTECT, related_name="invitations")
    # SHA-256 of the token. The plaintext is emailed and never stored.
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_sent",
    )
    expires_at = models.DateTimeField(db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        db_table = "users_invitation"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["email"],
                condition=models.Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="users_invitation_one_live_per_email",
            )
        ]

    def __str__(self):
        return f"invitation {self.public_id} for {self.email}"

    @property
    def status(self) -> str:
        if self.accepted_at:
            return "accepted"
        if self.revoked_at:
            return "revoked"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"
