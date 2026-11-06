/**
 * Exactly one ConfirmHost and one Toaster, in the root providers (FRONTEND_PLATFORM § 13,
 * BUILD_ORDER 8.3a).
 *
 * The bug it prevents: a confirm whose promise only a separately rendered dialog could settle. One
 * caller forgot to render it, and a "Void" button silently did nothing, forever. confirm() talks to
 * ONE host; zero hosts means every confirm() rejects, two means two dialogs per question.
 *
 * How: JSX elements by name, over the TypeScript AST of every source file (comments do not count).
 */
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { iterSources, parse, rel } from "./walk";

function rendered(name: string): string[] {
  const found: string[] = [];
  for (const file of iterSources()) {
    const visit = (node: ts.Node) => {
      if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText() === name) {
        found.push(rel(file));
      }
      ts.forEachChild(node, visit);
    };
    visit(parse(file));
  }
  return found;
}

describe("root-mounted hosts", () => {
  it.each(["ConfirmHost", "Toaster"])("%s is rendered exactly once, by the root providers", (name) => {
    expect(rendered(name)).toEqual(["src/core/providers/Providers.tsx"]);
  });
});
