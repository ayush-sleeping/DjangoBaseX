"""The encryption service (JOBS_AND_INTEGRATIONS.md § 25; BUILD 6.3; closes DB-33)."""

import pytest
from cryptography.fernet import Fernet
from django.core.management import CommandError, call_command
from django.urls import reverse
from rest_framework.test import APIClient

from core import crypto
from core.crypto import (
    UNREADABLE,
    CryptoNotConfigured,
    DecryptionError,
    decrypt,
    encrypt,
    key_fingerprints,
    mask,
    self_test,
)
from rbac import services
from tests.factories import UserFactory
from users.models import MfaDevice

KEY_A = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # settings_test's dummy
KEY_B = Fernet.generate_key().decode()


def test_round_trip_and_cross_purpose_separation(settings, monkeypatch):
    token = encrypt("hunter2-but-long", purpose="mfa_totp")
    assert decrypt(token, purpose="mfa_totp") == "hunter2-but-long"
    # Same keyring, different purpose: HKDF separation refuses the paste (§ 25).
    monkeypatch.setattr(crypto, "PURPOSES", ("mfa_totp", "probe"))
    with pytest.raises(DecryptionError):
        decrypt(token, purpose="probe")
    with pytest.raises(ValueError, match="registered purpose"):
        encrypt("x", purpose="not_registered")


def test_old_key_ciphertext_still_decrypts_after_a_new_key_is_prepended(settings):
    token = encrypt("survives-rotation", purpose="mfa_totp")
    settings.FIELD_ENCRYPTION_KEYS = [KEY_B, KEY_A]  # newest first
    assert decrypt(token, purpose="mfa_totp") == "survives-rotation"
    # And new writes use the NEW key: the old one alone cannot read them.
    fresh = encrypt("new-writes-new-key", purpose="mfa_totp")
    settings.FIELD_ENCRYPTION_KEYS = [KEY_A]
    with pytest.raises(DecryptionError):
        decrypt(fresh, purpose="mfa_totp")


def test_decrypt_failure_raises_and_never_returns_input(settings):
    token = encrypt("secret-material-xyz", purpose="mfa_totp")
    settings.FIELD_ENCRYPTION_KEYS = [KEY_B]
    with pytest.raises(DecryptionError) as failure:
        decrypt(token, purpose="mfa_totp")
    message = str(failure.value)
    assert token not in message and "secret-material" not in message
    assert "FIELD_ENCRYPTION_KEYS" in message  # actionable, §25's wording
    assert failure.value.__cause__ is None  # no chained InvalidToken carrying context


def test_an_empty_keyring_is_not_configured_never_plaintext(settings):
    settings.FIELD_ENCRYPTION_KEYS = []
    with pytest.raises(CryptoNotConfigured):
        encrypt("x", purpose="mfa_totp")
    self_test()  # an empty keyring is not a self-test failure (development; cfg refuses prod)


def test_a_slug_change_bricks_decryption_loudly(settings):
    token = encrypt("slug-bound", purpose="mfa_totp")
    settings.PRODUCT_SLUG = "renamed-product"
    with pytest.raises(DecryptionError):
        decrypt(token, purpose="mfa_totp")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("short", "••••••••"),
        ("fifteen-chars..", "••••••••"),
        ("sixteen-chars-ab", "••••s-ab"[0:4] + "s-ab"),
        ("a-long-api-key-value-1234", "••••1234"),
    ],
)
def test_the_masking_table(value, expected):
    assert mask(value) == expected


def test_unreadable_is_its_own_marker_distinct_from_not_set_and_masked():
    assert mask(None, unreadable=True) == UNREADABLE
    assert UNREADABLE not in {mask(None), mask("short"), mask("a-long-api-key-value-1234")}


def test_fingerprints_identify_keys_without_showing_them(settings):
    settings.FIELD_ENCRYPTION_KEYS = [KEY_B, KEY_A]
    prints = key_fingerprints()
    assert len(prints) == 2 and all(len(p) == 8 for p in prints)
    assert KEY_A not in str(prints) and KEY_B not in str(prints)
    token = encrypt("x", purpose="mfa_totp")
    assert crypto.fingerprint_of(token, purpose="mfa_totp") == prints[0]  # newest signs new writes


# --- rotate_encryption (the § 25 procedure) -------------------------------------------------------


@pytest.fixture
def devices(db):
    user = UserFactory()
    rows = []
    for n in range(3):
        device = MfaDevice(user=user, label=f"d{n}")
        device.set_secret("JBSWY3DPEHPK3PXP")
        device.save()
        rows.append(device)
    return rows


def test_rotate_reencrypts_and_verify_reports_per_key(devices, settings, capsys):
    old_fingerprint = key_fingerprints()[0]
    settings.FIELD_ENCRYPTION_KEYS = [KEY_B, KEY_A]  # prepend the new key
    new_fingerprint = key_fingerprints()[0]

    with pytest.raises(CommandError, match="not yet safe"):
        call_command("rotate_encryption", "--verify")
    assert f"{old_fingerprint}=3" in capsys.readouterr().out

    call_command("rotate_encryption", "--dry-run")
    assert "would rotate 3" in capsys.readouterr().out
    call_command("rotate_encryption", "--batch", "2")
    assert "rotated 3" in capsys.readouterr().out
    call_command("rotate_encryption")  # resumable: nothing left to do
    assert "already newest 3" in capsys.readouterr().out

    call_command("rotate_encryption", "--verify")
    out = capsys.readouterr().out
    assert (
        f"{new_fingerprint}=3" in out and f"{old_fingerprint}=0" in out and "safe to remove" in out
    )

    # The secrets still read, under the new key only.
    settings.FIELD_ENCRYPTION_KEYS = [KEY_B]
    for device in devices:
        device.refresh_from_db()
        assert decrypt(device.totp_secret_ciphertext, purpose="mfa_totp") == "JBSWY3DPEHPK3PXP"


def test_rotate_leaves_unreadable_rows_untouched_and_fails_loudly(devices, settings):
    stranger = MfaDevice.objects.first()
    before = Fernet(Fernet.generate_key()).encrypt(b"from-another-world").decode()
    MfaDevice.objects.filter(pk=stranger.pk).update(totp_secret_ciphertext=before)
    with pytest.raises(CommandError, match="Nothing was lost"):
        call_command("rotate_encryption")
    stranger.refresh_from_db()
    assert stranger.totp_secret_ciphertext == before  # untouched, not cleared, not replaced


def test_rotate_refuses_an_unknown_purpose_and_an_empty_keyring(db, settings):
    with pytest.raises(CommandError, match="no registered encrypted field"):
        call_command("rotate_encryption", "--purpose", "unknown")
    settings.FIELD_ENCRYPTION_KEYS = []
    with pytest.raises(CommandError, match="FIELD_ENCRYPTION_KEYS is empty"):
        call_command("rotate_encryption")


# --- GET /api/system/crypto/ ----------------------------------------------------------------------


def test_the_crypto_endpoint_is_gated_and_shows_fingerprints_never_keys(devices):
    viewer = UserFactory()
    client = APIClient()
    client.force_authenticate(user=viewer)
    assert client.get(reverse("core:crypto-status")).status_code == 403
    services.assign_role(
        actor=None,
        user=viewer,
        role=services.create_role(
            actor=None, name="cv", slug="cv", permission_codes=["settings.crypto.view"]
        ),
    )
    client.force_authenticate(user=type(viewer).objects.get(pk=viewer.pk))  # no stale perm cache
    response = client.get(reverse("core:crypto-status"))
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True and body["keys"][0]["newest"] is True
    assert KEY_A not in str(body)
    (field,) = body["fields"]
    assert (field["model"], field["purpose"]) == ("users.MfaDevice", "mfa_totp")
    assert field["rows_per_key"][body["keys"][0]["fingerprint"]] == 3
