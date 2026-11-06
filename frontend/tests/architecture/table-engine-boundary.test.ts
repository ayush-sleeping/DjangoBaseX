/**
 * The table engine stays behind the DataTable (FRONTEND_PLATFORM § 12, BUILD_ORDER 8.3b).
 *
 * Modules declare our own DataTableColumn<T>; only src/core/components/data-table/ may import
 * @tanstack/react-table (types included). The bug it prevents: one engine import in a shell or a
 * module turns the next engine upgrade, or a swap, from one directory into a hunt across every
 * product built on this core.
 *
 * How: import and export declarations over the TypeScript AST of every source file.
 */
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { iterSources, parse, rel } from "./walk";

const ENGINE = "@tanstack/react-table";
const HOME = "src/core/components/data-table/";

function importers(source: ts.SourceFile): boolean {
  return source.statements.some(
    (s) =>
      (ts.isImportDeclaration(s) || ts.isExportDeclaration(s)) &&
      s.moduleSpecifier !== undefined &&
      ts.isStringLiteral(s.moduleSpecifier) &&
      s.moduleSpecifier.text === ENGINE,
  );
}

describe("table engine boundary", () => {
  it("only the data-table directory imports the engine", () => {
    const outside: string[] = [];
    let inside = 0;
    for (const file of iterSources()) {
      if (!importers(parse(file))) continue;
      if (rel(file).startsWith(HOME)) inside += 1;
      else outside.push(rel(file));
    }
    expect(outside).toEqual([]);
    // Not vacuous: the DataTable itself must be found importing the engine.
    expect(inside).toBeGreaterThan(0);
  });

  it("catches a type-only import (positive control)", () => {
    const probe = ts.createSourceFile(
      "probe.ts",
      `import type { RowData } from "${ENGINE}";`,
      ts.ScriptTarget.Latest,
    );
    expect(importers(probe)).toBe(true);
  });
});
