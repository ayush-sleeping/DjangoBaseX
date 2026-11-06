/**
 * Token completeness (FRONTEND_PLATFORM § 16, BUILD_ORDER 8.3 acceptance part 1): in BOTH themes.
 *
 * The bug it prevents: a token declared in :root but not in the dark block renders light-on-light in
 * dark mode; one not mapped in @theme makes Tailwind emit no class at all, and the element renders
 * unstyled with no error. And a fill without its -foreground invites `bg-x text-white`, which breaks
 * the day the fill changes.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { iterSources } from "../../../tests/architecture/walk";

const CSS = readFileSync(path.join(__dirname, "tokens.css"), "utf8");

function block(selector: RegExp): string {
  const match = selector.exec(CSS);
  if (!match) throw new Error(`tokens.css has no ${selector}`);
  const start = match.index + match[0].length;
  return CSS.slice(start, CSS.indexOf("\n}", start));
}

function declared(body: string): Set<string> {
  return new Set([...body.matchAll(/^\s*--([a-z0-9-]+)\s*:/gm)].map((m) => m[1]));
}

const THEME = block(/@theme inline\s*\{/);
const LIGHT = declared(block(/:root\s*\{/));
const DARK = declared(block(/\[data-theme="dark"\]\s*\{/));
/** token → the CSS variable @theme maps it to (--color-primary: var(--primary)). */
const MAPPED = new Map(
  [...THEME.matchAll(/--color-([a-z0-9-]+)\s*:\s*var\(--([a-z0-9-]+)\)/g)].map((m) => [m[1], m[2]]),
);
const COLOURS = [...MAPPED.values()];
/** Layout tokens live in :root only; they are not colours and have no dark value. */
const NOT_COLOUR = new Set(["control-h", "row-h"]);

const STATUS = ["ok", "warn", "err", "info", "neutral"];
const FAMILIES = [
  "background", "foreground", "card", "popover", "primary", "secondary", "muted", "accent",
  "destructive", "border", "input", "ring", "sidebar", "sidebar-accent", "sidebar-border",
  "chart-1", "chart-2", "chart-3", "chart-4", "chart-5",
  ...STATUS.flatMap((s) => ["dot", "text", "tint", "solid", "solid-foreground"].map((p) => `${s}-${p}`)),
];
/** Every surface a component paints, with the token that writes on it. */
const FILLS: Record<string, string> = {
  background: "foreground",
  card: "card-foreground",
  popover: "popover-foreground",
  primary: "primary-foreground",
  secondary: "secondary-foreground",
  muted: "muted-foreground",
  accent: "accent-foreground",
  destructive: "destructive-foreground",
  sidebar: "sidebar-foreground",
  "sidebar-accent": "sidebar-accent-foreground",
  ...Object.fromEntries(STATUS.map((s) => [`${s}-solid`, `${s}-solid-foreground`])),
  ...Object.fromEntries(STATUS.map((s) => [`${s}-tint`, `${s}-text`])),
};

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
])("tokens.css — %s theme", (_theme, values) => {
  it("declares every family", () => {
    expect(FAMILIES.filter((f) => !values.has(f))).toEqual([]);
  });

  it("declares every colour @theme maps", () => {
    expect(COLOURS.filter((c) => !values.has(c))).toEqual([]);
  });

  it("gives every fill its foreground", () => {
    expect(Object.entries(FILLS).filter(([fill, fg]) => !values.has(fill) || !values.has(fg))).toEqual([]);
  });
});

describe("tokens.css — across the blocks", () => {
  it("maps every family into Tailwind", () => {
    expect(FAMILIES.filter((f) => !COLOURS.includes(f))).toEqual([]);
  });

  it("maps each token to its own variable (--color-x: var(--x))", () => {
    expect([...MAPPED].filter(([name, variable]) => name !== variable)).toEqual([]);
  });

  it("has no colour that only one theme defines", () => {
    const light = [...LIGHT].filter((v) => !NOT_COLOUR.has(v));
    expect(light.filter((v) => !DARK.has(v))).toEqual([]);
    expect([...DARK].filter((v) => !LIGHT.has(v))).toEqual([]);
    expect(light.filter((v) => !COLOURS.includes(v))).toEqual([]);
  });

  it("pairs every -foreground token with a fill", () => {
    const orphans = COLOURS.filter((c) => c.endsWith("-foreground"))
      .filter((fg) => !Object.values(FILLS).includes(fg));
    expect(orphans).toEqual([]);
  });
});

describe("a foreground token is never a fill", () => {
  it("no source uses bg-*-foreground", () => {
    const hits: string[] = [];
    for (const file of iterSources()) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(/\bbg-[a-z0-9-]+-foreground\b/g)) hits.push(`${file}: ${m[0]}`);
    }
    expect(hits).toEqual([]);
  });
});
