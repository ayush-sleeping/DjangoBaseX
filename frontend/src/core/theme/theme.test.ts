import { afterEach, describe, expect, it, vi } from "vitest";

import { readThemeChoice, resolveTheme, THEME_COOKIE, themeScript } from "./theme";

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
  document.cookie = `${THEME_COOKIE}=; Max-Age=0; Path=/`;
  vi.restoreAllMocks();
});

function systemPrefersDark(dark: boolean) {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query) => ({ matches: dark && query.includes("dark"), media: query }) as MediaQueryList,
  );
}

describe("theme", () => {
  it("reads the stored choice, defaulting to system", () => {
    expect(readThemeChoice("")).toBe("system");
    expect(readThemeChoice(`a=1; ${THEME_COOKIE}=dark`)).toBe("dark");
    expect(readThemeChoice(`${THEME_COOKIE}=purple`)).toBe("system");
  });

  it("resolves system from the OS preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
  });

  it.each([
    ["dark", false, "dark"],
    ["light", true, "light"],
    ["system", true, "dark"],
    [null, false, "light"],
  ])("the pre-paint script applies %s (system dark: %s) → %s", (stored, dark, expected) => {
    systemPrefersDark(dark);
    if (stored) document.cookie = `${THEME_COOKIE}=${stored}; Path=/`;
    new Function(themeScript())();
    expect(document.documentElement.getAttribute("data-theme")).toBe(expected);
  });
});
