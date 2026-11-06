/**
 * Tokens are paired, never mixed with raw colours (FRONTEND_PLATFORM § 16, BUILD_ORDER 8.3a).
 *
 * The bugs it prevents: `bg-primary text-white` looks right until a tenant or dark mode changes the
 * fill and not the text (a real incident measured white on a pale brand colour at about 1.4:1); and
 * `bg-${tone}-tint` compiles to NOTHING, because Tailwind only emits class names it finds whole in
 * source, so the chip renders transparent with no error.
 *
 * How: a scan of every source file's string and template literals (tests/architecture/walk.ts). The
 * ESLint palette ban catches palette classes; this catches what a regex over one literal cannot:
 * token fills next to absolute text colours, and interpolated colour utilities.
 * Do NOT silence this by adding an exception — fix the class string.
 */

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { iterSources, parse, rel } from "./walk";

const TOKEN_FILL = /\bbg-(primary|secondary|destructive|accent|muted|card|popover|sidebar|(ok|warn|err|info|neutral)-(solid|tint))\b/;
const ABSOLUTE_TEXT = /\btext-(white|black)\b/;
/** `bg-${…}`, `text-${…}-text`: a colour utility whose name is built at runtime. */
const INTERPOLATED_COLOUR = /(^|\s)(bg|text|border|ring|fill|stroke|from|to|via)-$/;

function offenders(file: string): string[] {
  const found: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isStringLiteralLike(node) && TOKEN_FILL.test(node.text) && ABSOLUTE_TEXT.test(node.text)) {
      found.push(`${rel(file)}: "${node.text}" pairs a token fill with an absolute text colour`);
    }
    if (ts.isTemplateExpression(node)) {
      const parts = [node.head, ...node.templateSpans.map((s) => s.literal)];
      for (const part of parts.slice(0, -1)) {
        if (INTERPOLATED_COLOUR.test(part.text)) found.push(`${rel(file)}: \`…${part.text}\${…}\` builds a colour class at runtime`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(parse(file));
  return found;
}

describe("no raw colour on tokens", () => {
  it("scans something", () => {
    expect([...iterSources()].length).toBeGreaterThan(20);
  });

  it("never pairs a token fill with text-white/black, nor builds a colour class at runtime", () => {
    expect([...iterSources()].flatMap(offenders)).toEqual([]);
  });

  it("catches both shapes (positive control)", () => {
    const probe = parse("probe.tsx", 'const a = "bg-primary text-white"; const b = (t: string) => `bg-${t}-tint`;');
    const hits: string[] = [];
    const visit = (node: ts.Node) => {
      if (ts.isStringLiteralLike(node) && TOKEN_FILL.test(node.text) && ABSOLUTE_TEXT.test(node.text)) hits.push("pair");
      if (ts.isTemplateExpression(node) && INTERPOLATED_COLOUR.test(node.head.text)) hits.push("interp");
      ts.forEachChild(node, visit);
    };
    visit(probe);
    expect(hits).toEqual(["pair", "interp"]);
  });
});
