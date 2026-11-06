/**
 * Every page has a navigation entry (FRONTEND_PLATFORM § 10, BUILD_ORDER 8.2 acceptance (a)).
 *
 * The bug it prevents: navigation is the route gate and the gate is default-deny, so a page added
 * without an entry is refused at runtime. Before default-deny the same mistake left the page
 * reachable by URL by anyone signed in, ungated until someone added a menu item. This test fails
 * the build instead.
 *
 * How: walk src/app/**\/page.tsx, turn each file into a route (route groups stripped, a [param]
 * replaced by a sample segment), and resolve it with resolveRoute() — the same function the gate
 * uses — against src/generated/nav-manifest.json. Two-way: every manifest href must also reach a
 * real page, so the menu has no dead links.
 *
 * Blind spot: plugin pages. They live behind the one (plugins)/[plugin]/[[...slug]] catch-all and
 * their entries arrive per user in bootstrap (the committed manifest is the boilerplate's own); the
 * runtime gate still refuses a plugin page with no entry. Do NOT silence this test with an
 * exception — register the page's navigation.
 */
import { readdirSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { MANIFEST_ENTRIES } from "@/core/shell/nav/manifest";
import { normalisePath, resolveRoute, type RouteEntry } from "@/core/shell/nav/resolve-route";

import { rel, SRC } from "./walk";

const APP = path.join(SRC, "app");
/** The plugin catch-all: its pages are a plugin's, gated through bootstrap (see the blind spot). */
const PLUGIN_CATCH_ALL = "src/app/(plugins)/[plugin]/[[...slug]]/page.tsx";

function* pageFiles(dir: string = APP): Generator<string> {
  for (const entry of readdirSync(dir).sort()) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) yield* pageFiles(full);
    else if (entry === "page.tsx") yield rel(full);
  }
}

/** "src/app/(core)/users/[publicId]/page.tsx" → "/users/sample". */
export function routeOf(file: string): string {
  const segments = file
    .replace(/^src\/app\//, "")
    .split("/")
    .slice(0, -1)
    .filter((s) => !(s.startsWith("(") && s.endsWith(")")))
    .filter((s) => !s.startsWith("[[...")) // an optional catch-all may be empty
    .map((s) => (s.startsWith("[") ? "sample" : s));
  return `/${segments.join("/")}`;
}

/** A page's route as a pattern matching the hrefs that reach it. */
function patternOf(file: string): RegExp {
  const parts = file
    .replace(/^src\/app\//, "")
    .split("/")
    .slice(0, -1)
    .filter((s) => !(s.startsWith("(") && s.endsWith(")")))
    .map((s) => (s.startsWith("[[...") ? "(?:/.*)?" : s.startsWith("[...") ? "/.+" : s.startsWith("[") ? "/[^/]+" : `/${s}`));
  return new RegExp(`^${parts.join("") || "/"}$`);
}

export function pagesWithoutAnEntry(files: readonly string[], entries: readonly RouteEntry[]): string[] {
  return files.filter((file) => resolveRoute(routeOf(file), entries) === null);
}

const PAGES = [...pageFiles()].filter((f) => f !== PLUGIN_CATCH_ALL);

describe("route manifest", () => {
  it("is generated and not empty (an empty manifest would make every check below vacuous)", () => {
    expect(MANIFEST_ENTRIES.length).toBeGreaterThan(0);
    expect(PAGES.length).toBeGreaterThan(0);
  });

  it("gives every page under src/app a navigation entry", () => {
    expect(pagesWithoutAnEntry(PAGES, MANIFEST_ENTRIES)).toEqual([]);
  });

  it("fails for a page nobody registered (the guard itself works)", () => {
    const orphan = "src/app/(core)/orphan-report/page.tsx";
    expect(pagesWithoutAnEntry([...PAGES, orphan], MANIFEST_ENTRIES)).toEqual([orphan]);
  });

  it("links no menu entry to a page that does not exist", () => {
    const patterns = PAGES.map(patternOf);
    const dead = MANIFEST_ENTRIES.filter((e) => !patterns.some((p) => p.test(normalisePath(e.href))));
    expect(dead.map((e) => e.href)).toEqual([]);
  });

  it("keeps plugin pages behind the one catch-all", () => {
    expect([...pageFiles()].filter((f) => f.startsWith("src/app/(plugins)/"))).toEqual([PLUGIN_CATCH_ALL]);
  });

  it("converts files to routes as the gate sees them", () => {
    expect(routeOf("src/app/(core)/page.tsx")).toBe("/");
    expect(routeOf("src/app/(core)/users/[publicId]/page.tsx")).toBe("/users/sample");
    expect(routeOf("src/app/(plugins)/[plugin]/[[...slug]]/page.tsx")).toBe("/sample");
  });
});
