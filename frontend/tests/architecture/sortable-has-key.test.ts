/**
 * A sortable column names the key it sorts by (FRONTEND_PLATFORM § 12, BUILD_ORDER 8.3b).
 *
 * The bug it prevents: seventy list endpoints accepted a sort parameter unguarded and fifty-two
 * sortable headers did nothing. A column declaring `sortable: true` without a `sortKey` draws an
 * arrow nothing honours.
 *
 * How (TypeScript AST over src/**):
 * - every object literal with `sortable: true` also has `sortKey`;
 * - a file whose columns declare any `sortKey` exports `LIST_ENDPOINT = "<route name>"`, and every
 *   sortKey is in that endpoint's ordering allow-list, exported by the backend
 *   (src/generated/ordering.ts, BUILD_ORDER 8.4a) — an arrow the API would ignore fails here.
 * The DataTable also warns about a sortable column without a sortKey at runtime in development.
 * Do NOT silence this — add the field to the view's ordering_fields, or drop the sortKey.
 */
import { readFileSync } from "node:fs";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { ORDERING } from "@/generated/ordering";

import { iterSources, parse, rel } from "./walk";

export function sortableWithoutKey(file: string, text: string): number[] {
  const source = parse(file, text);
  const lines: number[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isObjectLiteralExpression(node)) {
      const names = new Map(
        node.properties.filter(ts.isPropertyAssignment).map((p) => [p.name.getText(source), p.initializer]),
      );
      const sortable = names.get("sortable");
      if (sortable && sortable.kind === ts.SyntaxKind.TrueKeyword && !names.has("sortKey")) {
        lines.push(source.getLineAndCharacterOfPosition(node.getStart()).line + 1);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return lines;
}

/** Problems with a file's sortKeys against the exported allow-lists. */
export function sortKeyProblems(file: string, text: string, ordering: Readonly<Record<string, readonly string[]>> = ORDERING): string[] {
  const source = parse(file, text);
  const keys: string[] = [];
  let endpoint: string | null = null;
  const visit = (node: ts.Node) => {
    if (ts.isPropertyAssignment(node) && node.name.getText(source) === "sortKey" && ts.isStringLiteralLike(node.initializer)) {
      keys.push(node.initializer.text);
    }
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === "LIST_ENDPOINT" && node.initializer && ts.isStringLiteralLike(node.initializer)) {
      endpoint = node.initializer.text;
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  if (!keys.length) return [];
  if (endpoint === null) return [`sortKey without an exported LIST_ENDPOINT naming the list route`];
  const allowed = Object.hasOwn(ordering, endpoint) ? ordering[endpoint] : null;
  if (!allowed) return [`LIST_ENDPOINT "${endpoint}" declares no ordering_fields (src/generated/ordering.ts)`];
  return keys.filter((k) => !allowed.includes(k.replace(/^-/, ""))).map((k) => `sortKey "${k}" is not in ${endpoint}'s ordering_fields [${allowed.join(", ")}]`);
}

describe("sortable columns", () => {
  it("every sortable column has a sortKey", () => {
    const offenders = [...iterSources()].flatMap((f) => sortableWithoutKey(f, readFileSync(f, "utf8")).map((line) => `${rel(f)}:${line}`));
    expect(offenders).toEqual([]);
  });

  it("catches one (positive control)", () => {
    expect(sortableWithoutKey("c.tsx", 'const c = [{ id: "a", sortable: true }, { id: "b", sortable: true, sortKey: "b" }];')).toEqual([1]);
  });

  it("every sortKey is one its endpoint accepts", () => {
    const problems = [...iterSources()].flatMap((f) => sortKeyProblems(f, readFileSync(f, "utf8")).map((p) => `${rel(f)}: ${p}`));
    expect(problems).toEqual([]);
  });

  it("catches a sortKey the endpoint ignores, and one with no endpoint (positive controls)", () => {
    const ordering = { "core:activity": ["id"] };
    const good = 'export const LIST_ENDPOINT = "core:activity"; const c = [{ sortKey: "id" }];';
    expect(sortKeyProblems("c.tsx", good, ordering)).toEqual([]);
    expect(sortKeyProblems("c.tsx", 'export const LIST_ENDPOINT = "core:activity"; const c = [{ sortKey: "name" }];', ordering)).toHaveLength(1);
    expect(sortKeyProblems("c.tsx", 'const c = [{ sortKey: "id" }];', ordering)).toEqual(["sortKey without an exported LIST_ENDPOINT naming the list route"]);
    expect(sortKeyProblems("c.tsx", 'export const LIST_ENDPOINT = "users:user-list"; const c = [{ sortKey: "email" }];', ordering)).toHaveLength(1);
  });
});
