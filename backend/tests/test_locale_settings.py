"""The § 15 identity settings and the one backend formatter home (CONFIGURATION.md § 15)."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from core.formatting import CURRENCY_CODES, format_date, format_datetime, format_money
from core.registry import registry
from core.settings_registry import SettingInvalid, UnknownSetting
from core.settings_service import get_setting, resolve_setting, set_value

pytestmark = pytest.mark.django_db

AWARE = datetime(2026, 9, 29, 14, 3, tzinfo=UTC)


def test_the_table_is_registered_with_its_scopes_and_defaults():
    expect = {
        "platform.locale": (("platform", "tenant", "user"), "en"),
        "platform.timezone": (("platform", "tenant", "user"), "UTC"),
        "platform.currency": (("platform", "tenant"), None),
        "platform.country": (("platform", "tenant"), None),
        "platform.date_style": (("platform", "tenant", "user"), "locale"),
        "platform.time_style": (("platform", "tenant", "user"), "locale"),
        "platform.week_start": (("platform", "tenant", "user"), "locale"),
    }
    for key, (scopes, default) in expect.items():
        defn = registry.settings.get(key)
        assert (defn.scopes, defn.default) == (scopes, default), key


def test_no_default_currency_or_country_and_never_a_substitute():
    assert get_setting("platform.currency") is None
    assert get_setting("platform.country") is None
    assert resolve_setting("platform.currency").source == "default"
    with pytest.raises(ValueError, match="never substitutes"):
        format_money(Decimal("12.50"), None)


@pytest.mark.parametrize(
    ("key", "good", "bad"),
    [
        ("platform.timezone", "Asia/Kolkata", "Mars/Olympus"),
        ("platform.currency", "EUR", "EURO"),
        ("platform.currency", "INR", "eur"),
        ("platform.country", "IN", "IND"),
        ("platform.locale", "pt-BR", "english"),
        ("platform.date_style", "medium", "iso"),
        ("platform.week_start", "monday", "tuesday"),
    ],
)
def test_each_setting_validates_its_vocabulary(key, good, bad):
    assert set_value(key, good).value == good
    with pytest.raises(SettingInvalid):
        set_value(key, bad)


def test_the_currency_vocabulary_is_the_data_file_not_a_literal_list():
    assert {"EUR", "USD", "INR", "JPY"} <= CURRENCY_CODES
    assert len(CURRENCY_CODES) > 150


def test_a_two_segment_key_outside_the_reserved_namespaces_is_refused():
    # The § 15 keys may drop the group only because they live under platform. (owner ruling).
    from core.registry import Registry, RegistryError
    from core.settings_registry import Int, SettingDef

    reg = Registry()
    with pytest.raises(RegistryError, match="two segments"):
        reg.settings.register(
            SettingDef(
                key="users.probe",
                type=Int(),
                default=1,
                label="x",
                description="d",
                group="g",
                module="users",
                changed_by_event="e",
                used_by=("t",),
            )
        )


def test_unknown_locale_keys_still_raise():
    with pytest.raises(UnknownSetting):
        get_setting("platform.calendar")


# --- Formatters: date and datetime refuse each other ----------------------------------------------


def test_format_date_refuses_a_datetime_and_vice_versa():
    with pytest.raises(TypeError, match="datetime formatter"):
        format_date(AWARE)
    with pytest.raises(TypeError, match="date formatter"):
        format_datetime(date(2026, 9, 29))
    with pytest.raises(ValueError, match="aware"):
        format_datetime(datetime(2026, 9, 29, 14, 3))  # naive: storage is UTC, USE_TZ=True


def test_dates_never_convert_and_datetimes_render_in_the_viewers_zone():
    assert format_date(date(2026, 9, 29)) == "2026-09-29"  # the neutral ISO form
    assert format_date(date(2026, 9, 29), style="medium") == "29 September 2026"
    assert format_datetime(AWARE) == "2026-09-29T14:03:00+00:00"
    kolkata = format_datetime(AWARE, timezone="Asia/Kolkata", style="short")
    assert kolkata == "29 Sep 2026 19:33"
    assert (
        format_datetime(AWARE, timezone="Mars/Olympus") == AWARE.isoformat()
    )  # fall back, not fail


def test_money_is_the_bare_iso_form_and_decimal_only():
    assert format_money(Decimal("12.50"), "EUR") == "12.50 EUR"
    with pytest.raises(TypeError, match="Decimal"):
        format_money(12.50, "EUR")
    with pytest.raises(ValueError):
        format_money(Decimal("1"), "EURO")


def test_the_api_speaks_iso_8601_never_display_strings():
    # DRF's defaults emit ISO-8601; a DATETIME_FORMAT/DATE_FORMAT override is how display
    # formatting sneaks into every response. The settings must not carry one.
    from django.conf import settings as django_settings
    from rest_framework.serializers import DateField, DateTimeField

    for key in ("DATETIME_FORMAT", "DATE_FORMAT", "TIME_FORMAT"):
        assert key not in django_settings.REST_FRAMEWORK, f"{key} overrides ISO-8601 output"
    assert DateTimeField().to_representation(AWARE) == "2026-09-29T14:03:00Z"
    assert DateField().to_representation(date(2026, 9, 29)) == "2026-09-29"
