"""
TOTP secrets move from the single MFA_ENCRYPTION_KEY to the encryption service (JOBS § 25,
BUILD 6.3, TECH_DEBT DB-33): BinaryField `secret` → TextField `totp_secret_ciphertext`, purpose
"mfa_totp", re-encrypted row by row.

The old key is read from settings IF it still exists, else from the process environment — so a
product migrating after MFA_ENCRYPTION_KEY left settings.py still converts, from its own .env.
Rows with no readable old key FAIL the migration: losing every enrolled device silently is the one
outcome this migration exists to prevent. Irreversible by design.
"""

import os

from django.conf import settings
from django.db import migrations, models


def reencrypt(apps, schema_editor):
    MfaDevice = apps.get_model("users", "MfaDevice")
    rows = MfaDevice.objects.exclude(secret=b"")
    if not rows.exists():
        return

    from cryptography.fernet import Fernet

    from core.crypto import encrypt  # the real service: the migration must write what it reads

    old_key = getattr(settings, "MFA_ENCRYPTION_KEY", "") or os.environ.get(
        "MFA_ENCRYPTION_KEY", ""
    )
    if not old_key.strip():
        raise RuntimeError(
            "users.0006: MfaDevice rows exist but MFA_ENCRYPTION_KEY is not available in settings "
            "or the environment, so their TOTP secrets cannot be re-encrypted. Set it for this one "
            "migrate run (it can be removed afterwards)."
        )
    old = Fernet(old_key.strip())
    batch = []
    for device in rows.iterator(chunk_size=500):
        plain = old.decrypt(bytes(device.secret)).decode()  # InvalidToken fails the migration: loud
        device.totp_secret_ciphertext = encrypt(plain, purpose="mfa_totp")
        batch.append(device)
        if len(batch) >= 500:
            MfaDevice.objects.bulk_update(batch, ["totp_secret_ciphertext"])
            batch = []
    if batch:
        MfaDevice.objects.bulk_update(batch, ["totp_secret_ciphertext"])


class Migration(migrations.Migration):
    dependencies = [("users", "0005_invitation")]

    operations = [
        migrations.AddField(
            model_name="mfadevice",
            name="totp_secret_ciphertext",
            field=models.TextField(default=""),
            preserve_default=False,
        ),
        migrations.RunPython(reencrypt),
        migrations.RemoveField(model_name="mfadevice", name="secret"),
    ]
