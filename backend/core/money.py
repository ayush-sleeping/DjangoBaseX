"""
Money (DOMAIN_PRIMITIVES.md § 1; BUILD_ORDER 6.5): one value object, one quantisation point, one
rounding mode, and an allocation that always sums exactly.

Every rule here is a bug that shipped somewhere: five surfaces each rounding for themselves and
disagreeing by ±1; a report subtracting a monthly rate from a term total; a float in a request
body reaching a balance debit unquantised; a charge in one currency collected in another at 1:1.

- `Money` is an amount quantised to its currency's scale. `+`/`-` need the same currency and the
  same type: `Money - Rate` is a TypeError, which is the "never subtract a rate from a total" rule
  enforced by the type. `Money * Decimal` is an unquantised Decimal that must pass through
  `to_money()` again: round once, where the figure is computed, and store that.
- `Rate` (a unit price, a percentage) is a separate type at RATE_SCALE. Percentages are Rates;
  fixed amounts are Money. A column that mixes them is a modelling error.
- `to_money()` is the one quantisation point. It rejects float with a TypeError: a float reaching
  money code is a bug to find, not to paper over with str(). Garbage is a ValueError, never
  decimal.InvalidOperation, so callers handle one exception.
- The scale comes from currency metadata (core/data/iso4217.txt: JPY 0, EUR 2, KWD 3). Never a
  default of 2 in code. A code that is not money (XAU, XTS, XXX) is refused.
- ROUNDING is platform-wide. Changing it is an ADR, not a per-call argument.
- `allocate()` splits by largest remainder so the parts always sum exactly to the total.

Storage: `money_fields()` gives the (amount, currency) column pair, written already quantised;
`money_property()` reads them back as Money. The API carries amounts as strings
(core/api/fields.py). Every price comes from master data: an unresolvable component raises
PriceNotFound, which the API reports as 409 pricing_incomplete. Zero is a price someone must set.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

ROUNDING = ROUND_HALF_UP  # the mode most invoicing expects; changing it is an ADR
RATE_SCALE = 6
ISO4217_FILE = Path(__file__).resolve().parent / "data" / "iso4217.txt"


def _load_minor_units() -> tuple[frozenset[str], dict[str, int]]:
    codes, units = set(), {}
    for line in ISO4217_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        tokens = line.split()
        code, minor = tokens[0], tokens[1] if len(tokens) > 1 else "-"
        codes.add(code)
        if minor != "-":
            units[code] = int(minor)
    return frozenset(codes), units


CURRENCY_CODES, MINOR_UNITS = _load_minor_units()


class MoneyError(ValueError):
    """Base: every refusal here is one exception family for callers."""


class UnknownCurrency(MoneyError):
    def __init__(self, currency: object) -> None:
        super().__init__(f"{currency!r} is not a currency money can be held in")
        self.currency = currency


class CurrencyMismatch(MoneyError):
    def __init__(self, left: str, right: str) -> None:
        super().__init__(f"{left} and {right} cannot be combined without an explicit conversion")
        self.left, self.right = left, right


class PriceNotFound(MoneyError):
    """A price component master data does not resolve. The API answers 409 pricing_incomplete,
    naming the component: zero is a price someone must set, never a default."""

    code = "pricing_incomplete"

    def __init__(self, component: str) -> None:
        super().__init__(f"no price is configured for {component}")
        self.component = component


def scale(currency: str) -> int:
    """Minor units of a currency, from data. Unknown or non-money codes are refused."""
    if not isinstance(currency, str) or currency not in MINOR_UNITS:
        raise UnknownCurrency(currency)
    return MINOR_UNITS[currency]


def _decimal(value: object, what: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(
            f"{what} must be a Decimal, int or str, not {type(value).__name__}: a float reaching "
            "money code is a bug to find, not to convert (parse JSON with parse_float=Decimal)"
        )
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation:
            raise ValueError(f"{what} {value!r} is not a number") from None
    else:
        raise TypeError(f"{what} must be a Decimal, int or str, not {type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"{what} must be finite, not {result}")
    return result


def _quantum(places: int) -> Decimal:
    return Decimal(1).scaleb(-places)


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        places = scale(self.currency)
        if not isinstance(self.amount, Decimal) or self.amount != self.amount.quantize(
            _quantum(places)
        ):
            raise ValueError(
                f"Money amounts are quantised to {self.currency}'s {places} places: build one "
                "with to_money(), never Money() on a raw value"
            )
        object.__setattr__(self, "amount", self.amount.quantize(_quantum(places)))

    def _same(self, other: object, op: str) -> Money:
        if not isinstance(other, Money):
            raise TypeError(f"Money {op} {type(other).__name__}: a Rate is not an amount")
        if other.currency != self.currency:
            raise CurrencyMismatch(self.currency, other.currency)
        return other

    def __add__(self, other: object) -> Money:
        other = self._same(other, "+")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: object) -> Money:
        other = self._same(other, "-")
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __mul__(self, factor: object) -> Decimal:
        """An UNQUANTISED intermediate: pass it through to_money() where the figure is computed."""
        if isinstance(factor, Rate):
            return self.amount * factor.value
        return self.amount * _decimal(factor, "factor")

    __rmul__ = __mul__

    def __lt__(self, other: object) -> bool:
        return self.amount < self._same(other, "<").amount

    def __le__(self, other: object) -> bool:
        return self.amount <= self._same(other, "<=").amount

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    def as_json(self) -> dict[str, str]:
        """The wire form: strings, never JSON numbers."""
        return {"amount": str(self.amount), "currency": self.currency}


@dataclass(frozen=True, slots=True)
class Rate:
    """A unit price, a per-hour rate, a percentage: not an amount, and never added to one."""

    value: Decimal

    def __post_init__(self) -> None:
        value = _decimal(self.value, "rate")
        object.__setattr__(self, "value", value.quantize(_quantum(RATE_SCALE), rounding=ROUNDING))

    def __mul__(self, factor: object) -> Decimal:
        if isinstance(factor, Money):
            return factor.amount * self.value
        return self.value * _decimal(factor, "factor")

    __rmul__ = __mul__

    def __add__(self, other: object):
        raise TypeError("Rate + anything: rates are not summed; convert to Money first")

    __sub__ = __radd__ = __rsub__ = __add__

    def __str__(self) -> str:
        return str(self.value)


def to_money(value: object, currency: str) -> Money:
    """The one quantisation point. Decimal, int or str in; a float is a TypeError."""
    amount = _decimal(value, "amount")
    return Money(amount.quantize(_quantum(scale(currency)), rounding=ROUNDING), currency)


def to_rate(value: object) -> Rate:
    return Rate(_decimal(value, "rate"))


def allocate(total: Money, weights: Iterable[object]) -> list[Money]:
    """Split `total` in proportion to `weights` so the parts sum EXACTLY to the total (largest
    remainder). Rounding each part independently loses or invents a minor unit."""
    ws = [_decimal(w, "weight") for w in weights]
    if not ws:
        raise ValueError("allocate() needs at least one weight")
    if any(w < 0 for w in ws):
        raise ValueError("weights must not be negative")
    whole = sum(ws)
    if whole == 0:
        raise ValueError("weights must not all be zero")
    quantum = _quantum(scale(total.currency))
    units = int((total.amount / quantum).to_integral_value())
    raw = [Decimal(units) * w / whole for w in ws]
    floors = [int(r.to_integral_value(rounding="ROUND_FLOOR")) for r in raw]
    remainder = units - sum(floors)
    order = sorted(range(len(ws)), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
    step = 1 if remainder >= 0 else -1
    for i in order[: abs(remainder)]:
        floors[i] += step
    return [Money(Decimal(n) * quantum, total.currency) for n in floors]


# --- Storage helpers -----------------------------------------------------------------------------

AMOUNT_MAX_DIGITS, AMOUNT_PLACES = 19, 4  # headroom above the largest minor-unit scale (4)


def money_fields(**amount_options):
    """The (amount, currency) column pair, always written already quantised:

    total_amount, total_currency = money_fields()
    total = money_property("total")
    """
    from django.db import models

    return (
        models.DecimalField(
            max_digits=AMOUNT_MAX_DIGITS, decimal_places=AMOUNT_PLACES, **amount_options
        ),
        models.CharField(max_length=3),
    )


def money_property(name: str) -> property:
    def read(self) -> Money:
        return to_money(getattr(self, f"{name}_amount"), getattr(self, f"{name}_currency"))

    return property(read)
