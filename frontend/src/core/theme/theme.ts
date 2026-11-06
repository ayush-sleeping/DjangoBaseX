/**
 * Light, dark or follow the system (FRONTEND_PLATFORM § 16, BUILD_ORDER 8.3a).
 *
 * The choice lives in a readable cookie, `<prefix>_theme`, so the pre-paint script in <head> can
 * apply it before the first frame: no flash of the wrong theme, and no cookies() in the root layout
 * (which would make every route dynamic). The resolved theme is `data-theme` on <html>, which
 * tokens.css and Tailwind's `dark:` variant both read.
 */
import { AUTH_COOKIE_PREFIX } from "@/core/lib/session/cookies";

export const THEMES = ["light", "dark", "system"] as const;
export type ThemeChoice = (typeof THEMES)[number];
export type ResolvedTheme = "light" | "dark";

export const THEME_COOKIE = `${AUTH_COOKIE_PREFIX}_theme`;
/** A year: an appearance preference, not a session. */
export const THEME_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return typeof value === "string" && (THEMES as readonly string[]).includes(value);
}

export function resolveTheme(choice: ThemeChoice, systemPrefersDark: boolean): ResolvedTheme {
  if (choice === "system") return systemPrefersDark ? "dark" : "light";
  return choice;
}

/** The choice stored in a `document.cookie` string, or "system". */
export function readThemeChoice(cookieHeader: string): ThemeChoice {
  for (const part of cookieHeader.split(/;\s*/)) {
    const separator = part.indexOf("=");
    if (separator > 0 && part.slice(0, separator) === THEME_COOKIE) {
      const value = decodeURIComponent(part.slice(separator + 1));
      return isThemeChoice(value) ? value : "system";
    }
  }
  return "system";
}

/**
 * The body of the pre-paint script. Self-contained (no imports at runtime): it is inlined as a
 * string and runs before React. Any failure leaves the light theme, never a broken page.
 *
 * The cookie name comes from operator configuration and is inlined into an HTML <script>, so it goes
 * through scriptStringLiteral(): JSON.stringify alone would let "</script>" in a prefix end the
 * script element and inject markup.
 */
/** A JS string literal that is also safe inside an HTML <script>: "<" can never open "</script>". */
export function scriptStringLiteral(value: string): string {
  return JSON.stringify(value).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}

export function themeScript(cookieName: string = THEME_COOKIE): string {
  return `(function(){try{var n=${scriptStringLiteral(cookieName)},c="system";document.cookie.split(/;\\s*/).forEach(function(p){var i=p.indexOf("=");if(i>0&&p.slice(0,i)===n){c=decodeURIComponent(p.slice(i+1));}});if(c!=="light"&&c!=="dark"){c=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";}document.documentElement.setAttribute("data-theme",c);}catch(e){}})();`;
}

// --- The client store: the cookie is the state; these are its only writers ---------------------

const listeners = new Set<() => void>();

export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function currentThemeChoice(): ThemeChoice {
  return readThemeChoice(document.cookie);
}

/** Set data-theme on <html> from a choice, resolving "system" against the OS now. */
export function applyTheme(choice: ThemeChoice): void {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", resolveTheme(choice, prefersDark));
}

/** Store, apply and announce a choice. */
export function chooseTheme(choice: ThemeChoice): void {
  document.cookie = `${THEME_COOKIE}=${choice}; Path=/; Max-Age=${THEME_COOKIE_MAX_AGE}; SameSite=Lax`;
  applyTheme(choice);
  for (const listener of listeners) listener();
}
