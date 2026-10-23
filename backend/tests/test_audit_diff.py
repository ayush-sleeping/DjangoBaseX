"""Field diffs (DATA_LIFECYCLE.md § 4.3): pure functions, no database."""

import datetime as dt

from core.audit_diff import MASK, diff_values, is_secret_key


def labels(name, value):
    return {"role": (value, {1: "Editor", 2: "Admin"}.get(value))}.get(name, (value, None))


def test_an_update_records_only_the_changed_fields_with_fk_and_choice_labels():
    before = {"role": 1, "title": "Dealer", "note": "same"}
    after = {"role": 2, "title": "Dealer", "note": "same"}
    changes, event = diff_values(before, after, describe=labels)
    assert list(changes) == ["role"]  # unchanged fields are not recorded
    assert changes["role"] == {"old": 1, "new": 2, "old_label": "Editor", "new_label": "Admin"}
    assert event == "updated"


def test_json_is_diffed_per_key_with_scalar_coercion():
    before = {"config": {"limit": "16384", "mode": "a", "nested": {"on": "true"}}}
    after = {"config": {"limit": 16384, "mode": "b", "nested": {"on": True}}}
    changes, _ = diff_values(before, after)
    assert list(changes) == ["config.mode"]  # "16384" → 16384 and "true" → True record nothing
    assert changes["config.mode"] == {"old": "a", "new": "b"}


def test_a_secret_is_masked_at_depth_three_and_by_declaration():
    before = {"cfg": {"a": {"b": {"api_key": "old-secret-value"}}}, "pin": "1234", "name": "x"}
    after = {"cfg": {"a": {"b": {"api_key": "new-secret-value"}}}, "pin": "9999", "name": "y"}
    changes, _ = diff_values(before, after, secret_fields=("pin",))
    assert changes["cfg.a.b.api_key"] == {"old": MASK, "new": MASK, "secret": True}
    assert changes["pin"] == {"old": MASK, "new": MASK, "secret": True}  # declared secret
    assert "secret-value" not in str(changes)
    assert changes["name"] == {"old": "x", "new": "y"}  # an ordinary field is untouched


def test_a_ciphertext_column_is_always_a_secret():
    assert is_secret_key("totp_secret_ciphertext")
    assert is_secret_key("password") and is_secret_key("refresh_token")
    assert not is_secret_key("label")


def test_noisy_only_and_preference_only_saves_write_nothing():
    changes, _ = diff_values(
        {"updated_at": 1, "version": 1, "last_seen_at": 5, "layout": "a"},
        {"updated_at": 2, "version": 2, "last_seen_at": 6, "layout": "b"},
        preference_fields=("layout",),
    )
    assert changes == {}  # the caller then writes NO row


def test_a_status_only_change_becomes_status_changed():
    changes, event = diff_values({"status": "open"}, {"status": "won"})
    assert event == "status_changed" and changes["status"]["new"] == "won"
    mixed, event = diff_values({"status": "open", "name": "a"}, {"status": "won", "name": "b"})
    assert event == "updated" and set(mixed) == {"status", "name"}


def test_dates_are_iso_8601_utc_never_display_formatted():
    old = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC)
    new = dt.datetime(2026, 1, 2, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
    changes, _ = diff_values(
        {"due": old, "day": dt.date(2026, 1, 1)}, {"due": new, "day": dt.date(2026, 1, 2)}
    )
    assert changes["due"]["old"] == "2026-01-01T12:00:00+00:00"
    assert changes["due"]["new"] == "2026-01-02T06:30:00+00:00"  # converted to UTC
    assert changes["day"] == {"old": "2026-01-01", "new": "2026-01-02"}


def test_long_values_truncate_with_an_explicit_marker(settings):
    settings.AUDIT_DIFF_VALUE_MAX = 10
    changes, _ = diff_values({"body": "a"}, {"body": "b" * 50})
    assert changes["body"]["new"] == "b" * 10 and changes["body"]["truncated"] is True
