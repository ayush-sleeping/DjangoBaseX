"""
Locale, currency, timezone and formats (CONFIGURATION.md § 15; BUILD 5.5).

The ONE formatter home on the backend — the few server-rendered surfaces (emails, PDFs, CSV
exports). The API itself never returns a display-formatted value: datetimes are ISO-8601, money is
{"amount": "12.50", "currency": "EUR"}, and formatting is the client's job.

The identity settings live in the registry at platform/tenant/user scope (`resolve(LocalePolicy,
user=viewer)`), so a page renders in the VIEWER's zone and an email in the RECIPIENT's. There is no
default currency and no default country: every possible default is one market's assumption, and a
missing currency is never silently replaced — format_money raises instead of guessing the money.

This module is the settings layer: the "UTC" and "en" literals here are the declared defaults the
anti-hard-coding scan allows; everywhere else they are a finding.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal as _Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from core.settings_registry import Choice, SettingType, meta

# Data, not code: the scan (§ 18) reads the same file to refuse these codes as literals elsewhere.
ISO4217_FILE = Path(__file__).resolve().parent / "data" / "iso4217.txt"
# Each data line starts with the code; later columns (minor units, for core.money) are ignored here.
CURRENCY_CODES = frozenset(
    line.split()[0]
    for line in ISO4217_FILE.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
)

STYLES = ("locale", "short", "medium", "long")
# Until translations land, "locale" renders the neutral ISO form; the named styles are fixed
# patterns. The frontend's Intl formatters are the genuinely locale-aware side (§ 15).
_DATE_PATTERNS = {"short": "%d %b %Y", "medium": "%d %B %Y", "long": "%A, %d %B %Y"}
_TIME_PATTERNS = {"short": "%H:%M", "medium": "%H:%M", "long": "%H:%M:%S %Z"}


# --- The § 15 setting types -----------------------------------------------------------------------


@dataclass(frozen=True)
class _ValidatedString(SettingType):
    name = "string"

    def parse(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be text")
        return self.validate(value.strip())

    def validate(self, value: str) -> str:
        raise NotImplementedError

    def describe(self):
        return {"type": self.name, "format": self.format}


@dataclass(frozen=True)
class TimezoneName(_ValidatedString):
    format = "iana-timezone"

    def validate(self, value):
        if value not in available_timezones():
            raise ValueError("must be an IANA timezone name (zoneinfo knows it)")
        return value


@dataclass(frozen=True)
class CurrencyCode(_ValidatedString):
    format = "iso-4217"

    def validate(self, value):
        if value.upper() != value or value not in CURRENCY_CODES:
            raise ValueError("must be an ISO-4217 currency code (core/data/iso4217.txt)")
        return value


@dataclass(frozen=True)
class CountryCode(_ValidatedString):
    format = "iso-3166-alpha2"

    def validate(self, value):
        # Shape only, for now: no country data file ships yet (owner-accepted, 2026-10-24).
        if len(value) != 2 or not value.isalpha() or value.upper() != value:
            raise ValueError("must be an ISO-3166 alpha-2 code (two uppercase letters)")
        return value


@dataclass(frozen=True)
class LocaleTag(_ValidatedString):
    format = "bcp-47"

    def validate(self, value):
        if not re.fullmatch(r"[a-z]{2,3}(-[A-Z][a-z]{3})?(-(?:[A-Z]{2}|[0-9]{3}))?", value):
            raise ValueError('must be a BCP-47 tag like "en", "pt-BR" or "zh-Hant-TW"')
        return value


# --- The settings (§ 15's table) ------------------------------------------------------------------

_EVERYONE = ("platform", "tenant", "user")
_STYLE_CHOICES = Choice(choices=STYLES)


def _meta(type_, label, description, *, scopes=_EVERYONE, nullable=False):
    return meta(
        type_,
        label=label,
        description=description,
        changed_by_event="Entering a market, or a person's own preference",
        used_by=("Every formatted date, time and amount",),
        scopes=scopes,
        exposure="authenticated",
        nullable=nullable,
    )


@dataclass(frozen=True)
class LocalePolicy:
    """platform.* identity (§ 15). No default currency or country — the first-run wizard asks."""

    locale: str = field(
        default="en",
        metadata=_meta(LocaleTag(), "Locale", "The language and regional formats people see."),
    )
    timezone: str = field(
        default="UTC",
        metadata=_meta(
            TimezoneName(),
            "Timezone",
            "Dates and times render in the viewer's zone; storage stays UTC.",
        ),
    )
    currency: str | None = field(
        default=None,
        metadata=_meta(
            CurrencyCode(),
            "Currency",
            "Unset renders amounts with the bare ISO code and warns: no market is assumed.",
            scopes=("platform", "tenant"),
            nullable=True,
        ),
    )
    country: str | None = field(
        default=None,
        metadata=_meta(
            CountryCode(),
            "Country",
            "Unset until the first-run wizard asks: no market is assumed.",
            scopes=("platform", "tenant"),
            nullable=True,
        ),
    )
    date_style: str = field(
        default="locale",
        metadata=_meta(_STYLE_CHOICES, "Date style", "How dates render on formatted surfaces."),
    )
    time_style: str = field(
        default="locale",
        metadata=_meta(_STYLE_CHOICES, "Time style", "How times render on formatted surfaces."),
    )
    week_start: str = field(
        default="locale",
        metadata=_meta(
            Choice(choices=("locale", "monday", "sunday", "saturday")),
            "Week starts on",
            "Calendars and week groupings start here; locale follows the locale's rule.",
        ),
    )


def register_locale_settings(registry) -> None:
    """From CoreConfig.ready(): the § 15 table, under the reserved platform. namespace."""
    registry.settings.register_group(
        LocalePolicy, prefix="platform", module="platform", group="Locale & formats"
    )


# --- Resolving the viewer's settings --------------------------------------------------------------


def locale_policy(user=None) -> LocalePolicy:
    """
    The VIEWER's resolved locale settings (§ 15): what an email, PDF or CSV export passes to the
    formatters below, and what /api/auth/me/ will expose. Degrades to the shipped defaults like
    every settings read; it never fails the surface that asked.
    """
    from core.settings_service import resolve

    return resolve(LocalePolicy, user)


def format_datetime_for(value: datetime, user=None) -> str:
    """format_datetime in the viewer's own zone and style — the email/PDF entry point."""
    policy = locale_policy(user)
    return format_datetime(value, timezone=policy.timezone, style=policy.time_style)


# --- Formatters: date and datetime are different types, and each refuses the other ----------------


def _check(value, wanted: type, other: type, name: str):
    # datetime subclasses date, so the refusal must test the exact unwanted type first.
    if isinstance(value, other) if other is datetime else type(value) is other:
        raise TypeError(
            f"{name}() got a {other.__name__}; use the {other.__name__} formatter. "
            "A date is not a point in time and a datetime is not a calendar day (§ 15)."
        )
    if not isinstance(value, wanted):
        raise TypeError(f"{name}() formats {wanted.__name__}, got {type(value).__name__}")


def format_date(value: date, *, style: str = "locale") -> str:
    """A calendar day. Never converted into any timezone: a date has no zone to convert."""
    _check(value, date, datetime, "format_date")
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}")
    return value.isoformat() if style == "locale" else value.strftime(_DATE_PATTERNS[style])


def format_datetime(value: datetime, *, timezone: str = "UTC", style: str = "locale") -> str:
    """A point in time, rendered in the VIEWER's zone (resolve LocalePolicy for them first)."""
    _check(value, datetime, date, "format_datetime")
    if value.utcoffset() is None:
        raise ValueError("format_datetime() needs an aware datetime (storage is UTC, USE_TZ=True)")
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}")
    try:
        localised = value.astimezone(ZoneInfo(timezone))
    except (KeyError, ValueError, OSError):
        localised = value  # an invalid stored zone must not fail the request (§ 15): UTC
    if style == "locale":
        return localised.isoformat()
    pattern = f"{_DATE_PATTERNS[style]} {_TIME_PATTERNS[style]}"
    return localised.strftime(pattern).strip()


def format_money(amount, currency: str | None) -> str:
    """`"12.50 EUR"` — the bare ISO form (§ 15: symbols and placement are the frontend's Intl).
    A missing currency raises: substituting a default shows an amount in the wrong money."""
    if currency is None or not str(currency).strip():
        raise ValueError(
            "format_money() needs the money's own currency; it never substitutes a default. "
            "Unconfigured currency is a data-plane warning, not a guess (§ 15)."
        )
    code = CurrencyCode().validate(str(currency).strip())
    if not isinstance(amount, _Decimal):
        raise TypeError("format_money() takes a Decimal amount (never a float)")
    return f"{amount} {code}"
