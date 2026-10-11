"""APP_ENV classification and the environment ribbon (CONFIGURATION.md § 4)."""

import pytest

from core.env import (
    NON_PRODUCTION,
    TONE_DEV,
    TONE_LOUD,
    TONE_STAGING,
    environment_label,
    is_production_like,
    normalise,
)


@pytest.mark.parametrize(
    "value",
    ["production", "Production", " prod ", "PRODUCTION", "staging", "qa", "uat", "", "   ", None],
)
def test_anything_not_allow_listed_is_production_like(value):
    # Explicit values only: None here would fall back to settings, tested separately below.
    assert is_production_like(value if value is not None else "") is True


@pytest.mark.parametrize("value", ["development", "local", "test", "ci", " Development ", "CI"])
def test_only_the_four_allow_listed_values_are_not(value):
    assert is_production_like(value) is False


def test_the_allow_list_is_exactly_four_values():
    assert NON_PRODUCTION == {"development", "local", "test", "ci"}


def test_no_argument_reads_settings(settings):
    settings.APP_ENV = "test"
    assert is_production_like() is False
    settings.APP_ENV = "Staging"
    assert is_production_like() is True


def test_an_unset_settings_value_is_production_like(settings):
    if hasattr(settings, "APP_ENV"):
        del settings.APP_ENV
    assert is_production_like(None) is True


@pytest.mark.parametrize("value", [None, 0, ["production"], object()])
def test_normalise_never_raises_and_treats_non_strings_as_blank(value):
    assert normalise(value) == ""


@pytest.mark.parametrize(
    "value, expected",
    [
        ("production", {"label": None, "tone": None}),
        (" Production ", {"label": None, "tone": None}),
        ("staging", {"label": "Staging", "tone": TONE_STAGING}),
        ("development", {"label": "Development", "tone": TONE_DEV}),
        ("local", {"label": "Development", "tone": TONE_DEV}),
        ("test", {"label": "Test", "tone": TONE_DEV}),
        ("ci", {"label": "Test", "tone": TONE_DEV}),
    ],
)
def test_the_ribbon_table(value, expected):
    assert environment_label(value) == expected


@pytest.mark.parametrize("value", ["prod", "qa", "Prodution", "", None])
def test_an_unknown_value_gets_the_loudest_ribbon(value):
    assert environment_label(value) == {
        "label": "Unknown environment: set APP_ENV",
        "tone": TONE_LOUD,
    }


def test_labelling_never_disagrees_with_classification():
    # Every value that is labelled as non-production must also be classified non-production.
    for value in ["production", "staging", "development", "local", "test", "ci", "qa", ""]:
        if environment_label(value)["tone"] == TONE_DEV:
            assert not is_production_like(value)
        else:
            assert is_production_like(value)
