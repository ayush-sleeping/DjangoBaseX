/**
 * Runtime brand colours (FRONTEND_PLATFORM § 17, BUILD_ORDER 8.5). The backend sends NUMBERS
 * (`brand` in /api/public/config/); this composes `oklch(l c h)` from re-validated numbers only.
 * A string never reaches a CSS value, so injection is impossible by construction. Anything that
 * fails validation leaves the stylesheet's own colour for that slot.
 */
import { BRAND_MAX_CHROMA } from "@/generated/brand";

const NUMBER = /^\d+(\.\d+)?$/;

function channel(value: unknown, max: number, inclusive: boolean): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const text = String(value);
  if (!NUMBER.test(text)) return null; // exponent form (1e-7), sign, anything but digits and a dot
  return value <= max && (inclusive || value < max) ? text : null;
}

/** `oklch(l c h)` or null. The only place a brand value becomes CSS. */
export function composeOklch(color: unknown): string | null {
  if (typeof color !== "object" || color === null) return null;
  const { l, c, h } = color as Record<string, unknown>;
  const light = channel(l, 1, true);
  const chroma = channel(c, BRAND_MAX_CHROMA, true);
  const hue = channel(h, 360, false);
  return light && chroma && hue ? `oklch(${light} ${chroma} ${hue})` : null;
}

// The token names the backend derives (core.theme.derived_tokens); a name outside this list is
// ignored, so a payload cannot declare an arbitrary custom property.
const TOKENS = ["primary", "primary-foreground", "ring"] as const;
const THEME_SELECTORS = { light: "html:root", dark: 'html[data-theme="dark"]' } as const;

function declarations(theme: unknown): string[] {
  if (typeof theme !== "object" || theme === null) return [];
  const out: string[] = [];
  for (const name of TOKENS) {
    const value = composeOklch((theme as Record<string, unknown>)[name]);
    if (value) out.push(`--${name}:${value}`);
  }
  return out;
}

/** The stylesheet text for a brand payload, or "" when nothing valid remains. */
export function brandCss(brand: unknown): string {
  if (typeof brand !== "object" || brand === null) return "";
  const rules: string[] = [];
  for (const [theme, selector] of Object.entries(THEME_SELECTORS)) {
    const body = declarations((brand as Record<string, unknown>)[theme]);
    if (body.length) rules.push(`${selector}{${body.join(";")}}`);
  }
  return rules.join("");
}
