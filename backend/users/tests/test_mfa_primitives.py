"""TOTP and recovery-code primitives (AUTH_BLUEPRINT § 6.8, A16). No database: pure functions."""

import math
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlparse

import pyotp
import pytest
from cryptography.fernet import Fernet, InvalidToken

from users import mfa

AT = datetime(2026, 10, 11, 12, 0, 15, tzinfo=UTC)
STEP = int(AT.timestamp()) // 30
SECRET = "JBSWY3DPEHPK3PXP"


def code_at(step: int, secret: str = SECRET) -> str:
    return pyotp.TOTP(secret).generate_otp(step)


# --- Secrets at rest ----------------------------------------------------------------------------


def test_new_secrets_are_random_base32():
    a, b = mfa.new_secret(), mfa.new_secret()
    assert a != b
    assert re.fullmatch(r"[A-Z2-7]{32}", a)


def test_a_secret_round_trips_and_is_not_stored_in_the_clear():
    secret = mfa.new_secret()
    token = mfa.encrypt_secret(secret)
    assert isinstance(token, bytes)
    assert secret.encode() not in token
    assert mfa.decrypt_secret(token) == secret


def test_decrypt_accepts_a_memoryview_as_postgres_binaryfield_returns():
    secret = mfa.new_secret()
    assert mfa.decrypt_secret(memoryview(mfa.encrypt_secret(secret))) == secret


def test_an_empty_key_means_mfa_is_not_configured(settings):
    token = mfa.encrypt_secret(SECRET)
    settings.MFA_ENCRYPTION_KEY = ""
    with pytest.raises(mfa.MfaNotConfigured):
        mfa.encrypt_secret(SECRET)
    with pytest.raises(mfa.MfaNotConfigured):
        mfa.decrypt_secret(token)


def test_a_secret_encrypted_under_another_key_is_refused(settings):
    token = mfa.encrypt_secret(SECRET)
    settings.MFA_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(InvalidToken):
        mfa.decrypt_secret(token)


def test_the_provisioning_uri_names_the_issuer_and_the_account(settings):
    settings.MFA_ISSUER = "Acme Portal"
    uri = mfa.provisioning_uri(SECRET, "person@example.com")
    parsed = urlparse(uri)
    assert (parsed.scheme, parsed.netloc) == ("otpauth", "totp")
    assert unquote(parsed.path) == "/Acme Portal:person@example.com"
    query = parse_qs(parsed.query)
    assert query["issuer"] == ["Acme Portal"]
    assert query["secret"] == [SECRET]


# --- TOTP verification --------------------------------------------------------------------------


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_the_current_step_and_one_either_side_are_accepted(offset):
    assert mfa.verify_totp(SECRET, code_at(STEP + offset), 0, at=AT) == STEP + offset


@pytest.mark.parametrize("offset", [-2, 2])
def test_two_steps_away_is_refused(offset):
    assert mfa.verify_totp(SECRET, code_at(STEP + offset), 0, at=AT) is None


def test_a_code_is_not_accepted_twice():
    code = code_at(STEP)
    accepted = mfa.verify_totp(SECRET, code, 0, at=AT)
    assert accepted == STEP
    assert mfa.verify_totp(SECRET, code, accepted, at=AT) is None


def test_a_step_before_the_last_used_one_is_refused():
    # A code from the previous step is still inside the ±1 window, but a later step was used.
    assert mfa.verify_totp(SECRET, code_at(STEP - 1), STEP, at=AT) is None
    assert mfa.verify_totp(SECRET, code_at(STEP + 1), STEP, at=AT) == STEP + 1


def test_when_two_steps_share_a_code_the_later_one_is_burned(monkeypatch):
    # 1 in 10⁶ for real; forced here. Accepting the earlier step would let the code replay.
    monkeypatch.setattr(pyotp.TOTP, "generate_otp", lambda self, step: "123456")
    assert mfa.verify_totp(SECRET, "123456", 0, at=AT) == STEP + 1
    assert mfa.verify_totp(SECRET, "123456", STEP - 1, at=AT) == STEP + 1


def test_spaces_are_ignored():
    code = code_at(STEP)
    assert mfa.verify_totp(SECRET, f" {code[:3]} {code[3:]} ", 0, at=AT) == STEP


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "12345a", "abcdef", "١٢٣٤٥٦", "12-345"])
def test_anything_but_six_ascii_digits_is_refused(bad):
    assert mfa.verify_totp(SECRET, bad, 0, at=AT) is None


def test_another_secrets_code_is_refused():
    assert mfa.verify_totp(SECRET, code_at(STEP, secret=mfa.new_secret()), 0, at=AT) is None


def test_at_defaults_to_now():
    code = pyotp.TOTP(SECRET).now()
    assert mfa.verify_totp(SECRET, code, 0) is not None


# --- Recovery codes -----------------------------------------------------------------------------

FORMAT = re.compile(r"[A-HJKMNP-Z2-9]{6}-[A-HJKMNP-Z2-9]{6}")


def test_recovery_codes_are_unique_and_readable():
    codes = mfa.generate_recovery_codes()
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(FORMAT.fullmatch(code) for code in codes)
    assert not set("".join(codes)) & set("01OIL")


def test_recovery_codes_carry_at_least_50_bits():
    symbols = mfa.RECOVERY_GROUPS * mfa.RECOVERY_GROUP_LENGTH
    assert symbols * math.log2(len(set(mfa.RECOVERY_ALPHABET))) >= 50
    assert not set(mfa.RECOVERY_ALPHABET) & set("01OIL")


def test_the_count_is_honoured():
    assert len(mfa.generate_recovery_codes(3)) == 3


def test_a_recovery_code_hashes_the_same_however_it_is_typed():
    expected = mfa.hash_recovery_code("ABCDEF-GHJKMN")
    assert re.fullmatch(r"[0-9a-f]{64}", expected)
    for typed in ("abcdef-ghjkmn", "ABCDEF GHJKMN", " abcdefghjkmn ", "abc-def ghj-kmn"):
        assert mfa.hash_recovery_code(typed) == expected
    assert mfa.hash_recovery_code("ABCDEF-GHJKMP") != expected
