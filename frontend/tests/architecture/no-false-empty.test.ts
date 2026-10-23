/**
 * No false empty state (FRONTEND_PLATFORM.md § 5).
 *
 * The bug it prevents: `!isLoading && items.length === 0` renders "nothing here" after a failed
 * fetch, and after a disabled query that never ran. Emptiness is `isEmpty` from useApiList
 * (success AND zero items), and an EmptyState is rendered only where showError was checked first.
 *
 * How (TypeScript AST): a binary `!isLoading && <x>.length === 0` (either order), and an
 * `<EmptyState` JSX element in a file that never reads `isEmpty` or `showError`.
 *
 * Blind spot: it checks presence, not branch order; order is tested in use-api-query.test.tsx.
 * Two-way ratchet. Do NOT silence this by adding an exception — fix the code.
 */
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { assertRatchet, iterSources, parse, rel, type Hit } from "./walk";

const ALLOWED: Record<string, string> = {};

export function falseEmptyHits(file: ts.SourceFile): Hit[] {
  const hits: Hit[] = [];
  const text = file.getFullText();
  const readsContract = /\b(isEmpty|showError)\b/.test(text);
  const visit = (node: ts.Node) => {
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
      const sides = [node.left.getText(), node.right.getText()];
      const notLoading = sides.some((s) => /^!\s*isLoading$/.test(s));
      const lengthZero = sides.some((s) => /\.length\s*===?\s*0$/.test(s));
      if (notLoading && lengthZero) {
        hits.push({
          path: rel(file.fileName),
          line: file.getLineAndCharacterOfPosition(node.getStart()).line + 1,
          value: "!isLoading && …length === 0",
        });
      }
    }
    if (
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      node.tagName.getText() === "EmptyState" &&
      !readsContract
    ) {
      hits.push({
        path: rel(file.fileName),
        line: file.getLineAndCharacterOfPosition(node.getStart()).line + 1,
        value: "EmptyState without isEmpty/showError",
      });
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return hits;
}

describe("no false empty state", () => {
  it("finds none in production code", () => {
    const hits: Hit[] = [];
    for (const f of iterSources()) hits.push(...falseEmptyHits(parse(f)));
    assertRatchet(hits, ALLOWED, "no_false_empty");
  });

  it("catches both shapes (positive control)", () => {
    const source = parse(
      "/planted/list.tsx",
      [
        "export function List({ rows, isLoading }) {",
        "  if (!isLoading && rows.length === 0) return <EmptyState />;",
        "  return <ul />;",
        "}",
      ].join("\n"),
    );
    expect(falseEmptyHits(source).map((h) => h.value)).toEqual([
      "!isLoading && …length === 0",
      "EmptyState without isEmpty/showError",
    ]);
  });
});
