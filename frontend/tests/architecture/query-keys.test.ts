/**
 * Query-key roots (FRONTEND_PLATFORM.md § 4): a plugin's defineKeys root starts with its plugin
 * key, and roots are unique across the tree. A plugin's keys must never collide with core's or
 * another plugin's, or one invalidation reaches the wrong cache.
 *
 * How: a regex over defineKeys("…") string literals in src/** (keys are declared with a literal).
 * Blind spot: a root built from a variable. Do NOT silence this by adding an exception.
 */
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { iterSources, rel } from "./walk";

const DEFINE = /defineKeys\(\s*["'`]([^"'`]+)["'`]/g;

export function rootsIn(text: string): string[] {
  return [...text.matchAll(DEFINE)].map((m) => m[1]);
}

describe("query-key roots", () => {
  it("are unique and plugin-namespaced", () => {
    const seen = new Map<string, string>();
    for (const f of iterSources()) {
      const path = rel(f);
      for (const root of rootsIn(readFileSync(f, "utf8"))) {
        const plugin = /^src\/plugins\/([^/]+)\//.exec(path)?.[1];
        if (plugin) expect(root, `${path}: ${root}`).toMatch(new RegExp(`^${plugin}\\.`));
        expect(seen.has(root), `${root} is defined in both ${seen.get(root)} and ${path}`).toBe(false);
        seen.set(root, path);
      }
    }
  });

  it("extracts roots (positive control)", () => {
    expect(rootsIn('defineKeys("billing.invoices", {}); defineKeys(`users`, {})')).toEqual([
      "billing.invoices",
      "users",
    ]);
  });
});
