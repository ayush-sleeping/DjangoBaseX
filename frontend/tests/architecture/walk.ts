/**
 * The one source walker for frontend guard tests (ENGINEERING_PRACTICES § 2): every guard parses
 * the same scope with the TypeScript compiler, so a convention change is fixed in one place.
 * Scope is production code: src/**, minus tests, fixtures and generated files.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import ts from "typescript";

export const FRONTEND = path.resolve(__dirname, "..", "..");
export const SRC = path.join(FRONTEND, "src");

export function* iterSources(root: string = SRC): Generator<string> {
  for (const entry of readdirSync(root).sort()) {
    const full = path.join(root, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "node_modules" || entry === "fixtures" || entry.startsWith(".")) continue;
      yield* iterSources(full);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry)) continue;
    if (/\.(test|spec)\.tsx?$/.test(entry) || /\.generated\.ts$/.test(entry) || /\.d\.ts$/.test(entry)) continue;
    yield full;
  }
}

export function parse(file: string, text: string = readFileSync(file, "utf8")): ts.SourceFile {
  return ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
}

export function rel(file: string): string {
  return path.relative(FRONTEND, file).split(path.sep).join("/");
}

export type Hit = { path: string; line: number; value: string };

export function hitKey(hit: Hit): string {
  return `${hit.path}::${hit.value}`;
}

/** The two-way ratchet: nothing new offends, and every allow-list entry still offends. */
export function assertRatchet(hits: Hit[], allowed: Record<string, string>, rule: string): void {
  const blank = Object.entries(allowed).filter(([, reason]) => reason.trim().length < 15);
  if (blank.length) throw new Error(`[${rule}] allow-list entries without a real reason: ${blank.map(([k]) => k)}`);
  const fresh = hits.filter((h) => !(hitKey(h) in allowed)).map((h) => `${h.path}:${h.line}: ${h.value}`);
  if (fresh.length) {
    throw new Error(
      `[${rule}] new offenders — fix the code; do NOT silence this by adding an exception:\n  ${fresh.join("\n  ")}`,
    );
  }
  const present = new Set(hits.map(hitKey));
  const fixed = Object.keys(allowed).filter((k) => !present.has(k));
  if (fixed.length) throw new Error(`[${rule}] no longer offend — delete them from the allow-list: ${fixed}`);
}
