"""TOTP devices and recovery codes (AUTH_BLUEPRINT § 3.6)."""

from django.conf import settings
from django.db import models


class MfaDeviceQuerySet(models.QuerySet):
    def confirmed(self):
        # Setup is not enrolment: an unconfirmed device never counts for anything.
        return self.filter(confirmed_at__isnull=False)


class MfaDevice(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_devices"
    )
    label = models.CharField(max_length=64, blank=True, default="")
    # Fernet-encrypted with MFA_ENCRYPTION_KEY (users.mfa). Never the raw base32 secret.
    secret = models.BinaryField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    # The replay guard: a code whose time step is <= this is refused (§ 6.8).
    last_used_timestep = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MfaDeviceQuerySet.as_manager()

    class Meta:
        db_table = "users_mfa_device"

    def __str__(self):
        state = "confirmed" if self.confirmed_at else "pending"
        return f"mfa device ({state}) for user {self.user_id}"


class MfaRecoveryCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_recovery_codes"
    )
    # SHA-256 of the normalised code. Shown to the user once, at generation.
    code_hash = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users_mfa_recovery_code"

    def __str__(self):
        return f"recovery code for user {self.user_id}"
