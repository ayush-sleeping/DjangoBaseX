"""
Money on the wire (DOMAIN_PRIMITIVES.md § 1.4): `{"amount": "12.50", "currency": "EUR"}`, strings
both ways. A JSON number is refused: json.loads has already turned it into a float before any
serializer sees it, and a float is the hole every `Decimal(str(x))` call elsewhere papers over.
"""

from rest_framework import serializers

from core.money import Money, MoneyError, scale, to_money


class StrictMoneyField(serializers.Field):
    """Input and output. Rejects JSON numbers and more decimals than the currency allows."""

    default_error_messages = {
        "shape": "Expected an object with string 'amount' and 'currency'.",
        "amount_not_string": "'amount' must be a string such as \"12.50\", not a JSON number.",
        "currency": "'currency' is not a currency money can be held in.",
        "too_precise": "'amount' has more decimal places than {currency} allows ({places}).",
        "invalid": "'amount' is not a number.",
    }

    def to_internal_value(self, data) -> Money:
        if not isinstance(data, dict) or set(data) != {"amount", "currency"}:
            self.fail("shape")
        amount, currency = data["amount"], data["currency"]
        if not isinstance(amount, str):
            self.fail("amount_not_string")
        if not isinstance(currency, str):
            self.fail("currency")
        try:
            places = scale(currency)
        except MoneyError:
            self.fail("currency")
        try:
            money = to_money(amount, currency)
        except (TypeError, ValueError):
            self.fail("invalid")
        if str(money.amount) != amount.strip() and _places(amount) > places:
            self.fail("too_precise", currency=currency, places=places)
        return money

    def to_representation(self, value: Money) -> dict[str, str]:
        if not isinstance(value, Money):
            raise TypeError("StrictMoneyField serialises Money; build one with to_money()")
        return value.as_json()


class MoneySerializerField(StrictMoneyField):
    """Output only."""

    def __init__(self, **kwargs):
        kwargs["read_only"] = True
        super().__init__(**kwargs)


def _places(text: str) -> int:
    text = text.strip()
    if "e" in text.lower():
        return 99  # exponent notation is never an amount a client typed
    return len(text.split(".", 1)[1]) if "." in text else 0
