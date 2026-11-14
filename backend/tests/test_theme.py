"""Runtime brand colours and the contrast solver (FRONTEND_PLATFORM § 17, BUILD_ORDER 8.5)."""

import pytest

from core.settings_registry import SettingInvalid
from core.settings_service import set_value
from core.theme import (
    BRAND_SLOTS,
    SURFACES,
    TEXT_MIN,
    UI_MIN,
    BrandColorError,
    best_foreground,
    contrast,
    derived_tokens,
    measure,
    parse_color,
    passes,
    validate_brand_color,
)

pytestmark = pytest.mark.django_db

KEY = "platform.brand.primary"
GOOD = {"l": 0.53, "c": 0.15, "h": 260}
TOO_LIGHT = {"l": 0.9, "c": 0.1, "h": 90}  # yellow-ish: 3:1 on a white card fails
MID = {"l": 0.6, "c": 0.15, "h": 260}  # text on it reaches 4.43:1, just under 4.5:1


def _tuple(value):
    return (value["l"], value["c"], value["h"])


def test_a_passing_colour_is_accepted_unchanged():
    validate_brand_color(GOOD)
    assert set_value(KEY, GOOD).value == GOOD


def test_the_known_ratio_anchors_the_maths():
    # white on black is 21:1 by definition; a sanity anchor for the OKLCH -> luminance chain.
    assert contrast((1.0, 0.0, 0.0), (0.0, 0.0, 0.0)) == pytest.approx(21.0, abs=0.01)


@pytest.mark.parametrize("bad", [TOO_LIGHT, MID])
def test_a_failing_colour_is_refused_with_each_ratio_and_a_passing_suggestion(bad):
    with pytest.raises(BrandColorError) as caught:
        validate_brand_color(bad)
    err = caught.value
    fill = _tuple(bad)
    failing = [m for m in measure(fill) if not m.passes]
    assert failing
    for m in failing:
        assert f"{m.ratio:.2f}:1" in str(err) and f"needs {m.needed:g}:1" in str(err)
    assert err.suggestion is not None
    suggested = _tuple(err.suggestion)
    assert suggested != fill
    assert passes(suggested)  # re-verified independently of the solver's own check
    assert all(m.passes for m in measure(suggested))
    assert "Suggestion" in str(err)


@pytest.mark.parametrize("bad", [TOO_LIGHT, MID])
def test_the_refusal_reaches_the_settings_api_as_invalid_value(bad):
    with pytest.raises(SettingInvalid, match=r"\d\.\d\d:1"):
        set_value(KEY, bad)


def test_text_and_ui_axes_are_both_enforced_in_both_themes():
    fill = _tuple(GOOD)
    seen = {(m.theme, m.what) for m in measure(fill)}
    assert {t for t, _ in seen} == {"light", "dark"}
    for theme, surfaces in SURFACES.items():
        assert (theme, "text on the colour") in seen
        for name in surfaces:
            assert (theme, f"the colour on the {name}") in seen
    assert {m.needed for m in measure(fill)} == {TEXT_MIN, UI_MIN}


def test_a_colour_that_only_fails_the_dark_theme_is_refused():
    # Darker blue: fine on the light surfaces, under 3:1 on the dark background.
    darker = {"l": 0.5, "c": 0.15, "h": 260}
    assert all(m.passes for m in measure(_tuple(darker)) if m.theme == "light")
    with pytest.raises(BrandColorError, match="dark: the colour on the card 2.96:1"):
        validate_brand_color(darker)


@pytest.mark.parametrize(
    "bad",
    [
        "red;background:url(x)",
        "oklch(0.5 0.1 200)",
        "#ff0000",
        {"l": "0.5", "c": 0.1, "h": 200},
        {"l": 0.5, "c": "0.1;x", "h": 200},
        {"l": 1.5, "c": 0.1, "h": 200},
        {"l": -0.1, "c": 0.1, "h": 200},
        {"l": 0.5, "c": 0.9, "h": 200},
        {"l": 0.5, "c": 0.1, "h": 360},
        {"l": 0.5, "c": 0.1, "h": float("nan")},
        {"l": 0.5, "c": 0.1, "h": float("inf")},
        {"l": True, "c": 0.1, "h": 200},
        {"l": 0.5, "c": 0.1},
        {"l": 0.5, "c": 0.1, "h": 200, "x": "red;background:url(x)"},
        [0.5, 0.1, 200],
    ],
)
def test_strings_and_out_of_range_channels_are_refused(bad):
    with pytest.raises(ValueError):
        parse_color(bad)
    with pytest.raises(ValueError):
        validate_brand_color(bad)


def test_unset_is_allowed_and_means_the_stylesheet_default():
    validate_brand_color(None)
    assert derived_tokens(None) is None


def test_derived_tokens_are_numbers_only_per_theme():
    tokens = derived_tokens(GOOD)
    assert set(tokens) == {"light", "dark"}
    for theme in tokens.values():
        assert set(theme) == {"primary", "primary-foreground", "ring"}
        for channels in theme.values():
            assert set(channels) == {"l", "c", "h"}
            assert all(type(v) in (int, float) for v in channels.values())
        assert theme["primary"] == GOOD
        fg = _tuple(theme["primary-foreground"])
        assert fg == pytest.approx(best_foreground(_tuple(GOOD)))


def test_a_stored_value_that_no_longer_passes_is_never_served():
    assert derived_tokens(MID) is None
    assert derived_tokens("red;background:url(x)") is None


def test_the_slot_list_is_one_constant():
    assert BRAND_SLOTS == ("primary",)


def test_there_are_no_built_in_presets_to_check():
    # § 17 asks that every preset passes in a parametrised test. None exist yet (a preset is a
    # product decision, TECH_DEBT); this fails the day someone adds one without the test.
    import core.theme as theme

    assert not [n for n in dir(theme) if n.upper().startswith("PRESET")]


def test_public_config_brand_is_null_when_unset(client):
    assert client.get("/api/public/config/").json()["brand"] is None


def test_public_config_brand_is_numbers_only_once_set(client):
    set_value(KEY, GOOD)
    brand = client.get("/api/public/config/").json()["brand"]
    assert set(brand) == {"light", "dark"}
    for theme in brand.values():
        for channels in theme.values():
            assert all(type(v) in (int, float) for v in channels.values())
    assert brand["light"]["primary"] == GOOD
    assert "oklch" not in str(brand)
