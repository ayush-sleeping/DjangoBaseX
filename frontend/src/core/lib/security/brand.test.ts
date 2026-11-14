import { describe, expect, it } from "vitest";

import { brandCss, composeOklch } from "./brand";

const GOOD = { l: 0.53, c: 0.15, h: 260 };
const tokens = {
  primary: GOOD,
  "primary-foreground": { l: 0.98, c: 0, h: 0 },
  ring: GOOD,
};

describe("composeOklch (§ 17: numbers in, oklch() out)", () => {
  it("composes from valid numbers", () => {
    expect(composeOklch(GOOD)).toBe("oklch(0.53 0.15 260)");
    expect(composeOklch({ l: 1, c: 0, h: 0 })).toBe("oklch(1 0 0)");
  });

  it.each([
    ["a CSS payload", "red;background:url(x)"],
    ["a string colour", "oklch(0.5 0.1 200)"],
    ["a string channel", { l: "0.5", c: 0.1, h: 200 }],
    ["an injected channel", { l: "0.5);background:url(x", c: 0.1, h: 200 }],
    ["NaN", { l: Number.NaN, c: 0.1, h: 200 }],
    ["Infinity", { l: 0.5, c: Number.POSITIVE_INFINITY, h: 200 }],
    ["negative", { l: -0.1, c: 0.1, h: 200 }],
    ["lightness over 1", { l: 1.1, c: 0.1, h: 200 }],
    ["chroma over the bound", { l: 0.5, c: 0.5, h: 200 }],
    ["hue 360", { l: 0.5, c: 0.1, h: 360 }],
    ["exponent form", { l: 1e-7, c: 0.1, h: 200 }],
    ["a missing channel", { l: 0.5, c: 0.1 }],
    ["null", null],
    ["an array", [0.5, 0.1, 200]],
  ])("refuses %s", (_name, value) => expect(composeOklch(value)).toBeNull());
});

describe("brandCss", () => {
  it("writes light on :root and dark on [data-theme=dark], for the derived tokens only", () => {
    const css = brandCss({ light: tokens, dark: tokens });
    expect(css).toContain("html:root{--primary:oklch(0.53 0.15 260);--primary-foreground:oklch(0.98 0 0);--ring:oklch(0.53 0.15 260)}");
    expect(css).toContain('html[data-theme="dark"]{--primary:');
  });

  it("is empty for null, a string or garbage (the stylesheet default stays)", () => {
    for (const bad of [null, undefined, "red", 5, {}, { light: "x", dark: [] }]) expect(brandCss(bad)).toBe("");
  });

  it("drops one invalid token and keeps the valid ones", () => {
    const css = brandCss({ light: { ...tokens, ring: "red;background:url(x)" } });
    expect(css).toContain("--primary:");
    expect(css).not.toContain("--ring");
    expect(css).not.toContain("url");
  });

  it("ignores a token name it does not know", () => {
    expect(brandCss({ light: { "evil}body{x": GOOD } })).toBe("");
  });
});
