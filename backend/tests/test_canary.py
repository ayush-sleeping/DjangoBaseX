"""
The leak-test canary is unique and invisible to the scrubber's entropy backstop
(tests/canary.py), so a canary that disappears from a log was removed by a key or path rule.
"""

from core.observability.scrub import default_rules, scrub
from tests.canary import canary

PROSE = (
    "body was {{'note': '{c}'}}",
    "login failed for {c}",
    "{c}",
    "value=({c}) rejected",
)


def test_a_bare_canary_in_prose_is_never_touched_by_the_backstop():
    rules = default_rules()
    for i in range(5000):
        text = PROSE[i % len(PROSE)].format(c=canary())
        assert rules.scrub_text(text) == text


def test_a_canary_under_a_non_secret_key_survives_scrub():
    value = canary()
    assert scrub({"note": value, "extra": [value]}) == {"note": value, "extra": [value]}


def test_canaries_are_unique():
    drawn = [canary() for _ in range(5000)]
    assert len(set(drawn)) == len(drawn)
