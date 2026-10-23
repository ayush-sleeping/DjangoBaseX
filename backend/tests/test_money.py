"""Money (DOMAIN_PRIMITIVES.md § 1; BUILD_ORDER 6.5)."""

import random
from decimal import Decimal

import pytest

from core.money import (
    MINOR_UNITS,
    CurrencyMismatch,
    Money,
    PriceNotFound,
    Rate,
    UnknownCurrency,
    allocate,
    scale,
    to_money,
    to_rate,
)

# Test values only: the anti-hard-coding scan excludes tests by path (CONFIGURATION § 18).
EUR, JPY, KWD = "EUR", "JPY", "KWD"


def test_scale_comes_from_data_never_a_default_of_two():
    assert (scale(JPY), scale(EUR), scale(KWD)) == (0, 2, 3)
    assert len(MINOR_UNITS) > 150
    with pytest.raises(UnknownCurrency):
        scale("XAU")  # a metal, not money
    with pytest.raises(UnknownCurrency):
        scale("eur")  # case matters: the code is data, not a guess


@pytest.mark.parametrize(
    "value, expected", [("12.345", "12.35"), (Decimal("1.005"), "1.01"), (7, "7.00")]
)
def test_to_money_quantises_half_up_to_the_currency_scale(value, expected):
    assert str(to_money(value, EUR).amount) == expected
    assert str(to_money("1234.56", JPY)) == f"1235 {JPY}"
    assert str(to_money("1.23456", KWD)) == f"1.235 {KWD}"


def test_float_is_rejected_not_converted():
    with pytest.raises(TypeError, match="float"):
        to_money(12.5, EUR)
    with pytest.raises(TypeError):
        to_money(True, EUR)
    with pytest.raises(TypeError):
        to_rate(0.1)


def test_garbage_is_a_value_error_never_invalid_operation():
    with pytest.raises(ValueError, match="not a number"):
        to_money("twelve", EUR)
    with pytest.raises(ValueError, match="finite"):
        to_money("NaN", EUR)


def test_money_cannot_be_built_unquantised():
    with pytest.raises(ValueError, match="to_money"):
        Money(Decimal("1.005"), EUR)


def test_same_currency_arithmetic_and_mismatch():
    a, b = to_money("10.00", EUR), to_money("2.50", EUR)
    assert a + b == to_money("12.50", EUR)
    assert a - b == to_money("7.50", EUR)
    assert -b == to_money("-2.50", EUR)
    assert b < a and b <= a
    with pytest.raises(CurrencyMismatch):
        a + to_money("1", JPY)


def test_money_minus_rate_is_a_type_error():
    total, rate = to_money("100.00", EUR), to_rate("19.5")
    with pytest.raises(TypeError, match="Rate is not an amount"):
        total - rate  # noqa: B018 — the expression IS the test
    with pytest.raises(TypeError):
        total + rate  # noqa: B018
    with pytest.raises(TypeError):
        rate + rate  # noqa: B018


def test_multiplying_gives_an_unquantised_intermediate():
    product = to_money("10.00", EUR) * to_rate("0.333333")
    assert isinstance(product, Decimal) and product == Decimal("3.33333")
    assert to_money(product, EUR) == to_money("3.33", EUR)
    assert Rate(Decimal("0.1")).value == Decimal("0.100000")


def test_allocate_sums_exactly_for_random_splits():
    rng = random.Random(6_5)
    for _ in range(1000):
        currency = rng.choice([EUR, JPY, KWD])
        total = to_money(Decimal(rng.randint(-10_000_000, 10_000_000)) / 1000, currency)
        weights = [rng.randint(0, 50) for _ in range(rng.randint(1, 7))]
        if sum(weights) == 0:
            weights[0] = 1
        parts = allocate(total, weights)
        assert sum((p.amount for p in parts), Decimal(0)) == total.amount
        assert all(p.currency == currency for p in parts)


def test_allocate_refuses_bad_weights():
    total = to_money("10.00", EUR)
    with pytest.raises(ValueError):
        allocate(total, [])
    with pytest.raises(ValueError):
        allocate(total, [0, 0])
    with pytest.raises(ValueError):
        allocate(total, [1, -1])
    with pytest.raises(TypeError):
        allocate(total, [0.5, 0.5])


def test_allocate_largest_remainder_is_deterministic():
    assert [str(p.amount) for p in allocate(to_money("100.00", EUR), [1, 1, 1])] == [
        "33.34",
        "33.33",
        "33.33",
    ]


def test_price_not_found_names_the_component():
    exc = PriceNotFound("plan:gold")
    assert exc.code == "pricing_incomplete" and "plan:gold" in str(exc)


def test_wire_form_is_strings():
    assert to_money("12.5", EUR).as_json() == {"amount": "12.50", "currency": EUR}
