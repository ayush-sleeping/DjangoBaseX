/**
 * A sortable column names the key it sorts by (FRONTEND_PLATFORM § 12, BUILD_ORDER 8.3b).
 *
 * The bug it prevents: seventy list endpoints accepted a sort parameter unguarded and fifty-two
 * sortable headers did nothing. A column declaring `sortable: true` without a `sortKey` draws an
 * arrow nothing honours.
 *
 * How (TypeScript AST over src/**): every object literal with `sortable: true` also has `sortKey`.
 * The DataTable warns about the same thing at runtime in development.
 * Blind spot (until BUILD_ORDER 8.4 exports each endpoint's ordering allow-list): that the sortKey
 * is one the endpoint actually accepts. Do NOT silence this — add the sortKey or drop `sortable`.
 */
import { readFileSync } from "node:fs";

import ts from "typescript";
import { describe, expect, it } from "vitest";

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

describe("sortable columns", () => {
  it("every sortable column has a sortKey", () => {
    const offenders = [...iterSources()].flatMap((f) => sortableWithoutKey(f, readFileSync(f, "utf8")).map((line) => `${rel(f)}:${line}`));
    expect(offenders).toEqual([]);
  });

  it("catches one (positive control)", () => {
    expect(sortableWithoutKey("c.tsx", 'const c = [{ id: "a", sortable: true }, { id: "b", sortable: true, sortKey: "b" }];')).toEqual([1]);
  });
});
