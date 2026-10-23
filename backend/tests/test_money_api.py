"""Money on the wire (DOMAIN_PRIMITIVES.md § 1.4): strings in, strings out, numbers refused."""

import pytest
from django.conf import settings
from rest_framework import serializers

from core.api.fields import MoneySerializerField, StrictMoneyField
from core.money import to_money

EUR, JPY = "EUR", "JPY"  # test values; the scan excludes tests by path


class QuoteIn(serializers.Serializer):
    total = StrictMoneyField()


class QuoteOut(serializers.Serializer):
    total = MoneySerializerField()


def validate(payload):
    s = QuoteIn(data={"total": payload})
    s.is_valid()
    return s


def test_a_string_amount_is_accepted_and_quantised():
    s = validate({"amount": "12.5", "currency": EUR})
    assert s.errors == {} and s.validated_data["total"] == to_money("12.50", EUR)


def test_a_json_number_is_refused():
    s = validate({"amount": 12.5, "currency": EUR})
    assert s.errors["total"][0].code == "amount_not_string"
    s = validate({"amount": 12, "currency": EUR})
    assert s.errors["total"][0].code == "amount_not_string"


def test_too_many_decimals_is_refused():
    assert validate({"amount": "12.505", "currency": EUR}).errors["total"][0].code == "too_precise"
    assert validate({"amount": "1.5", "currency": JPY}).errors["total"][0].code == "too_precise"
    assert validate({"amount": "12.50", "currency": EUR}).errors == {}
    assert validate({"amount": "1e2", "currency": EUR}).errors["total"][0].code == "too_precise"


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"amount": "1", "currency": "XAU"}, "currency"),
        ({"amount": "1", "currency": 978}, "currency"),
        ({"amount": "abc", "currency": EUR}, "invalid"),
        ("12.50", "shape"),
        ({"amount": "1"}, "shape"),
    ],
)
def test_bad_shapes_name_their_rule(payload, code):
    assert validate(payload).errors["total"][0].code == code


def test_responses_are_strings():
    out = QuoteOut({"total": to_money("7", EUR)}).data
    assert out == {"total": {"amount": "7.00", "currency": EUR}}
    assert settings.REST_FRAMEWORK.get("COERCE_DECIMAL_TO_STRING", True) is True


def test_output_field_refuses_a_raw_decimal():
    with pytest.raises(TypeError, match="to_money"):
        QuoteOut({"total": "7.00"}).data  # noqa: B018
