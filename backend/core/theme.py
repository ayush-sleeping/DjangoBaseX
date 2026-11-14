"""
Runtime brand colours and the WCAG contrast solver (FRONTEND_PLATFORM § 17, BUILD_ORDER 8.5).

A brand colour is stored as NUMBERS, never CSS: {"l": 0..1, "c": 0..MAX_CHROMA, "h": 0..<360},
the OKLCH channels. The frontend composes `oklch(l c h)` from re-validated numbers, so no string
from the database ever reaches a CSS value.

The colour is refused unless it passes WCAG 2.x AA in BOTH themes, on BOTH axes:

- text on the fill (WCAG 1.4.3, text): the better of the near-white and near-black foreground must
  reach 4.5:1 against the fill;
- the fill against its surroundings (WCAG 1.4.11, a user-interface component): the fill must reach
  3:1 against the page background and the card.

A refusal names every failing measurement with its ratio and suggests the nearest passing colour
(same hue, nearest lightness; less chroma only if no lightness passes), re-verified before it is
offered. The admin's colour is never silently adjusted: what is saved is what they chose. Only the
foreground and the focus ring are DERIVED, from the validated fill.

Standard library only: OKLCH → OKLab → linear sRGB (Björn Ottosson's matrices) → WCAG relative
luminance. Out-of-gamut channels are clipped to sRGB, as browsers display them.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from .settings_registry import Json, meta

# The overridable slots, one constant shared by the solver, its tests and the frontend (exported to
# src/generated/brand.ts by export_frontend_contracts).
BRAND_SLOTS = ("primary",)
MAX_CHROMA = 0.37

TEXT_MIN = 4.5  # WCAG 1.4.3 (AA, normal text)
UI_MIN = 3.0  # WCAG 1.4.11 (AA, user-interface components)

Oklch = tuple[float, float, float]

# The stylesheet's own colours the fill is measured against, per theme: --background and --card in
# src/core/styles/tokens.css. Mirrored by hand today; a drift check is TECH_DEBT DB-70.
SURFACES: dict[str, dict[str, Oklch]] = {
    "light": {"background": (0.99, 0.0, 0.0), "card": (1.0, 0.0, 0.0)},
    "dark": {"background": (0.16, 0.01, 265.0), "card": (0.2, 0.012, 265.0)},
}
# The two foregrounds a fill may carry: the stylesheet's near-white and near-black.
FOREGROUNDS: dict[str, Oklch] = {"light": (0.98, 0.0, 0.0), "dark": (0.21, 0.01, 265.0)}


class BrandColorError(ValueError):
    """A colour that fails AA. `str()` is the API's message: the ratios and a passing suggestion."""

    def __init__(self, failures: list[str], suggestion: dict | None):
        self.failures = failures
        self.suggestion = suggestion
        hint = (
            f" Suggestion: {json.dumps(suggestion)}."
            if suggestion
            else " No lightness or chroma at this hue passes; choose another hue."
        )
        super().__init__("fails WCAG AA: " + "; ".join(failures) + "." + hint)


# --- Colour maths --------------------------------------------------------------------------------


def to_linear_srgb(color: Oklch) -> tuple[float, float, float]:
    lightness, chroma, hue = color
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )
    return tuple(min(1.0, max(0.0, channel)) for channel in rgb)  # type: ignore[return-value]


def luminance(color: Oklch) -> float:
    """WCAG relative luminance (of linear sRGB, which this already is)."""
    r, g, b = to_linear_srgb(color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(one: Oklch, other: Oklch) -> float:
    high, low = sorted((luminance(one), luminance(other)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# --- The check -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Measurement:
    theme: str
    what: str
    ratio: float
    needed: float

    @property
    def passes(self) -> bool:
        return self.ratio >= self.needed

    def describe(self) -> str:
        return f"{self.theme}: {self.what} {self.ratio:.2f}:1, needs {self.needed:g}:1"


def best_foreground(fill: Oklch) -> Oklch:
    """The near-white or near-black foreground with the higher contrast on `fill`."""
    return max(FOREGROUNDS.values(), key=lambda fg: contrast(fg, fill))


def measure(fill: Oklch) -> list[Measurement]:
    out = []
    fg_ratio = contrast(best_foreground(fill), fill)
    for theme, surfaces in SURFACES.items():
        out.append(Measurement(theme, "text on the colour", fg_ratio, TEXT_MIN))
        for name, surface in surfaces.items():
            out.append(
                Measurement(theme, f"the colour on the {name}", contrast(fill, surface), UI_MIN)
            )
    return out


def passes(fill: Oklch) -> bool:
    return all(m.passes for m in measure(fill))


def suggest(fill: Oklch) -> Oklch | None:
    """The nearest passing colour: same hue; nearest lightness; less chroma only if needed."""
    lightness, chroma, hue = fill
    for c_step in range(0, int(chroma * 1000) + 1, 10):
        c = round(max(0.0, chroma - c_step / 1000), 3)
        for step in range(0, 1001):
            for candidate_l in (lightness - step / 1000, lightness + step / 1000):
                if 0 <= candidate_l <= 1:
                    candidate = (round(candidate_l, 3), c, round(hue, 1))
                    if passes(candidate):  # re-verified on the rounded values offered
                        return candidate
    return None


# --- The setting's validator and what the frontend receives ---------------------------------------


def parse_color(value) -> Oklch:
    """{"l","c","h"} numbers in range, or ValueError naming what is wrong. Never a string."""
    if not isinstance(value, dict) or set(value) != {"l", "c", "h"}:
        raise ValueError(f'must be {{"l": 0..1, "c": 0..{MAX_CHROMA:g}, "h": 0..<360}}')
    numbers = []
    for key, high, inclusive in (("l", 1.0, True), ("c", MAX_CHROMA, True), ("h", 360.0, False)):
        number = value[key]
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            raise ValueError(f"{key} must be a number")
        if number < 0 or number > high or (not inclusive and number == high):
            raise ValueError(
                f"{key} must be in 0..{high:g}" + ("" if inclusive else " (exclusive)")
            )
        numbers.append(float(number))
    return numbers[0], numbers[1], numbers[2]


def validate_brand_color(value) -> None:
    """The `platform.brand.primary` validator: ValueError (BrandColorError) unless it passes AA."""
    if value is None:
        return
    fill = parse_color(value)
    failures = [m.describe() for m in measure(fill) if not m.passes]
    if failures:
        found = suggest(fill)
        raise BrandColorError(
            failures, None if found is None else dict(zip("lch", found, strict=True))
        )


@dataclass(frozen=True)
class BrandPolicy:
    """platform.brand.* (§ 17): brand colours, as numbers. Unset: the stylesheet's own."""

    primary: dict | None = field(
        default=None,
        metadata=meta(
            Json(validator=validate_brand_color),
            label="Brand colour",
            description=(
                'The primary colour as OKLCH numbers {"l", "c", "h"}. Refused unless text on it '
                "and it on the page pass WCAG AA in light and dark; the refusal suggests a "
                "passing one."
            ),
            changed_by_event="A rebrand, or a product taking this platform as its own",
            used_by=("Buttons, focus rings and every primary surface",),
            scopes=("platform",),
            exposure="public",
            nullable=True,
        ),
    )


def register_brand_settings(registry) -> None:
    """From CoreConfig.ready(), under the reserved platform. namespace."""
    registry.settings.register_group(
        BrandPolicy, prefix="platform.brand", module="platform", group="Brand"
    )


def _numbers(color: Oklch) -> dict:
    return {"l": round(color[0], 4), "c": round(color[1], 4), "h": round(color[2], 2)}


def derived_tokens(primary) -> dict | None:
    """
    What /api/public/config/ sends as `brand`: per theme, the fill and the tokens derived from it,
    as numbers. None when no brand colour is set (the stylesheet's own colours apply) or when the
    stored value no longer passes (a row written before a rule tightened: never served).
    """
    if primary is None:
        return None
    try:
        validate_brand_color(primary)
    except ValueError:
        return None
    fill = parse_color(primary)
    tokens = {
        "primary": _numbers(fill),
        "primary-foreground": _numbers(best_foreground(fill)),
        "ring": _numbers(
            fill
        ),  # the focus ring: the fill passes 3:1 on every surface by construction
    }
    return {theme: dict(tokens) for theme in SURFACES}
