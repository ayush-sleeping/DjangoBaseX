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
    # core.crypto ciphertext, purpose "mfa_totp" (JOBS § 25) — never the raw base32 secret, and
    # never decrypted on attribute access: reading it is an explicit users.mfa.decrypt_secret call.
    totp_secret_ciphertext = models.TextField()
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

    def set_secret(self, secret_b32: str) -> None:
        """Encrypt and store. The ONE write path: nothing assigns the ciphertext column raw."""
        from users import mfa

        self.totp_secret_ciphertext = mfa.encrypt_secret(secret_b32)

    @property
    def has_secret(self) -> bool:
        return bool(self.totp_secret_ciphertext)


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
