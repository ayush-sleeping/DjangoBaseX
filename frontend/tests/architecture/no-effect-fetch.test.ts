/**
 * No useEffect + setLoading fetches (FRONTEND_PLATFORM.md § 5; BUILD_ORDER 8.1).
 *
 * The bug it prevents: a hand-rolled effect that fetches on mount, sets a loading flag and stores
 * the result ships the same three defects every time: a failed fetch rendered as an authoritative
 * empty state, no cancellation (a slow response overwrites a newer one), and a cache not keyed by
 * scope. Data comes through useApiQuery / useApiList, which carry the load-state contract.
 *
 * How (TypeScript AST over src/**): a `useEffect(...)` whose callback body calls `fetch`, a
 * transport entry point (request/get/post/patch/del/upload/download/api), or a setter matching
 * /^set(Is)?Loading$/.
 *
 * Blind spots: a fetch wrapped in a helper named differently; an effect in a custom hook that
 * does not call useEffect directly. Two-way ratchet: the allow-list starts empty; every entry
 * must still offend. Do NOT silence this by adding an exception — fix the code.
 */
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { assertRatchet, iterSources, parse, rel, type Hit } from "./walk";

const TRANSPORT = new Set(["fetch", "request", "get", "post", "patch", "del", "upload", "download", "api"]);
const LOADING_SETTER = /^set(Is)?Loading$/;
// path::value -> why it is allowed. Do not add an entry without a reason.
const ALLOWED: Record<string, string> = {};

function calleeName(node: ts.CallExpression): string {
  const e = node.expression;
  if (ts.isIdentifier(e)) return e.text;
  if (ts.isPropertyAccessExpression(e)) return e.name.text;
  return "";
}

export function effectFetchHits(file: ts.SourceFile): Hit[] {
  const hits: Hit[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node) && calleeName(node) === "useEffect" && node.arguments[0]) {
      const body = node.arguments[0];
      const inner = (n: ts.Node) => {
        if (ts.isCallExpression(n)) {
          const name = calleeName(n);
          if (TRANSPORT.has(name) || LOADING_SETTER.test(name)) {
            const line = file.getLineAndCharacterOfPosition(n.getStart()).line + 1;
            hits.push({ path: rel(file.fileName), line, value: `useEffect→${name}()` });
          }
        }
        ts.forEachChild(n, inner);
      };
      ts.forEachChild(body, inner);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return hits;
}

describe("no useEffect + setLoading fetches", () => {
  it("finds none in production code", () => {
    const hits: Hit[] = [];
    for (const f of iterSources()) hits.push(...effectFetchHits(parse(f)));
    assertRatchet(hits, ALLOWED, "no_effect_fetch");
  });

  it("catches a planted effect fetch (positive control)", () => {
    const source = parse(
      "/planted/page.tsx",
      [
        'import { useEffect, useState } from "react";',
        "export function Page() {",
        "  const [rows, setRows] = useState([]);",
        "  const [isLoading, setIsLoading] = useState(false);",
        "  useEffect(() => {",
        "    setIsLoading(true);",
        '    fetch("/api/users/").then((r) => r.json()).then(setRows);',
        "  }, []);",
        "  useEffect(() => { document.title = String(rows.length); }, [rows]);",
        "  return null;",
        "}",
      ].join("\n"),
    );
    expect(effectFetchHits(source).map((h) => `${h.line}: ${h.value}`)).toEqual([
      "6: useEffect→setIsLoading()",
      "7: useEffect→fetch()",
    ]);
  });
});
