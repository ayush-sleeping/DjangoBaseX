import { afterEach, describe, expect, it, vi } from "vitest";

import { readThemeChoice, resolveTheme, scriptStringLiteral, THEME_COOKIE, themeScript } from "./theme";

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

describe("the pre-paint script is safe with a hostile cookie prefix", () => {
  const hostile = 'x</script><script>alert(1)</script><!--" ';

  it("never contains a closing script tag or a raw line separator", () => {
    const body = themeScript(hostile);
    expect(body.toLowerCase()).not.toContain("</script");
    expect(body).not.toContain("<");
    expect(body).not.toContain(" ");
  });

  it("still reads the cookie under that exact name", () => {
    const body = themeScript(hostile);
    vi.spyOn(window, "matchMedia").mockImplementation((q) => ({ matches: false, media: q }) as MediaQueryList);
    vi.spyOn(document, "cookie", "get").mockReturnValue(`${hostile}=dark`);
    new Function(body)();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("round-trips any string through scriptStringLiteral", () => {
    for (const value of [hostile, "plain_theme", "a\"b\\c", " "]) {
      expect(JSON.parse(scriptStringLiteral(value))).toBe(value);
    }
  });
});
