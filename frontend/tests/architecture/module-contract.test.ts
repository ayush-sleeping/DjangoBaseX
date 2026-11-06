/**
 * The module UI contract (FRONTEND_PLATFORM § 11, BUILD_ORDER 8.3 acceptance part 2).
 *
 * The bug it prevents: modules copied from each other drift. Unifying four copied modules into one
 * shape found seven live bugs, none visible until someone clicked to page 2 or selected a row. A
 * module supplies columns, fields and handlers; the shells supply every layout.
 *
 * How (TypeScript AST over src/core/modules/** and src/plugins/*\/modules/**):
 * - a view file named *Index.tsx renders <ResourceIndex>, *Form.tsx renders <ResourceForm>,
 *   *Show.tsx renders <ResourceShow> — or carries `ui-contract-deviation: <reason>`;
 * - no module file renders layout the shells own (<main>, <table>);
 * - every column array in a columns.tsx is in the fixed order: identifier → status → data… →
 *   updated → actions (selection is the table's own);
 * - a page or module file over 400 lines fails (a budget, not an aesthetic; two-way ratchet).
 * And for the reference module: every Users route file is a thin wrapper that renders the module.
 * Do NOT silence this by adding an exception — move the shape into the shell.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { assertRatchet, type Hit, iterSources, parse, rel, SRC } from "./walk";

const DEVIATION = /ui-contract-deviation:\s*\S/;
const SHELL_FOR: [RegExp, string][] = [
  [/Index\.tsx$/, "ResourceIndex"],
  [/Form\.tsx$/, "ResourceForm"],
  [/Show\.tsx$/, "ResourceShow"],
];
const ORDER = ["identifier", "status", "data", "updated", "actions"];
const LINE_BUDGET = 400;
// path::value → why. Each entry must still offend (two-way ratchet).
const OVER_BUDGET: Record<string, string> = {
  "src/app/(core)/settings/roles/[publicId]/role-editor.tsx::lines":
    "the roles screens are not yet a module on the shells; split when they move (follow-up after 8.3b)",
};

function isModuleFile(file: string): boolean {
  const r = rel(file);
  return r.startsWith("src/core/modules/") || /^src\/plugins\/[^/]+\/modules\//.test(r);
}

function jsxTags(source: ts.SourceFile): string[] {
  const tags: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) tags.push(node.tagName.getText(source));
    ts.forEachChild(node, visit);
  };
  visit(source);
  return tags;
}

/** Problems in one module view file's text (exported for the positive controls). */
export function viewProblems(file: string, text: string): string[] {
  const name = path.basename(file);
  const source = parse(file, text);
  const tags = jsxTags(source);
  const problems: string[] = [];
  const deviates = DEVIATION.test(text);
  for (const [pattern, shell] of SHELL_FOR) {
    if (pattern.test(name) && !tags.includes(shell) && !deviates) problems.push(`${name} must render <${shell}>`);
  }
  for (const owned of ["main", "table"]) {
    if (tags.includes(owned) && !deviates) problems.push(`${name} renders <${owned}>, which the shells own`);
  }
  return problems;
}

/** Column kinds in each array literal of a columns file, out of order → a problem. */
export function columnProblems(file: string, text: string): string[] {
  const source = parse(file, text);
  const problems: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isArrayLiteralExpression(node)) {
      const kinds = node.elements.flatMap((el) => {
        if (!ts.isObjectLiteralExpression(el)) return [];
        const kind = el.properties.find((p) => ts.isPropertyAssignment(p) && p.name.getText(source) === "kind");
        return kind && ts.isPropertyAssignment(kind) && ts.isStringLiteral(kind.initializer) ? [kind.initializer.text] : [];
      });
      if (kinds.length) {
        const ranks = kinds.map((k) => ORDER.indexOf(k));
        const sorted = ranks.every((r, i) => r >= 0 && (i === 0 || ranks[i - 1] <= r));
        const singles = ["identifier", "status", "updated", "actions"].every((k) => kinds.filter((x) => x === k).length <= 1);
        if (!sorted || !singles || kinds[0] !== "identifier") {
          problems.push(`${path.basename(file)}:${source.getLineAndCharacterOfPosition(node.getStart()).line + 1} columns [${kinds.join(", ")}] are not identifier → status → data → updated → actions`);
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return problems;
}

function* routeFiles(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) yield* routeFiles(full);
    else if (entry === "page.tsx") yield full;
  }
}

const MODULE_FILES = [...iterSources()].filter(isModuleFile);

describe("module UI contract", () => {
  it("finds the reference module", () => {
    expect(MODULE_FILES.map(rel)).toEqual(expect.arrayContaining(["src/core/modules/users/Index.tsx", "src/core/modules/users/Show.tsx", "src/core/modules/users/Form.tsx"]));
  });

  it("every module view composes its shell and renders no layout of its own", () => {
    const problems = MODULE_FILES.filter((f) => f.endsWith(".tsx")).flatMap((f) => viewProblems(f, readFileSync(f, "utf8")).map((p) => `${rel(f)}: ${p}`));
    expect(problems).toEqual([]);
  });

  it("every columns.tsx keeps the fixed column order", () => {
    const columns = MODULE_FILES.filter((f) => path.basename(f) === "columns.tsx");
    expect(columns.length).toBeGreaterThan(0);
    expect(columns.flatMap((f) => columnProblems(f, readFileSync(f, "utf8")))).toEqual([]);
  });

  it("keeps page and module files within the line budget", () => {
    const hits: Hit[] = [...iterSources()]
      .filter((f) => f.endsWith(".tsx") && (rel(f).startsWith("src/app/") || isModuleFile(f)))
      .filter((f) => readFileSync(f, "utf8").split("\n").length > LINE_BUDGET)
      .map((f) => ({ path: rel(f), line: 1, value: "lines" }));
    assertRatchet(hits, OVER_BUDGET, "module_line_budget");
  });

  it("the Users routes are thin wrappers over the module (acceptance: the Users module uses only the shells)", () => {
    const users = [...routeFiles(path.join(SRC, "app", "(core)", "users"))];
    expect(users.length).toBe(4);
    for (const file of users) {
      const text = readFileSync(file, "utf8");
      expect(text, rel(file)).toMatch(/from "@\/core\/modules\/users\//);
      const intrinsic = jsxTags(parse(file, text)).filter((t) => /^[a-z]/.test(t));
      expect(intrinsic, `${rel(file)} renders markup of its own`).toEqual([]);
    }
  });
});

describe("module contract guards (positive controls)", () => {
  it("catches an Index without the shell, and a hand-made table", () => {
    expect(viewProblems("src/core/modules/x/Index.tsx", "export const I = () => <main><table /></main>;")).toEqual([
      "Index.tsx must render <ResourceIndex>",
      "Index.tsx renders <main>, which the shells own",
      "Index.tsx renders <table>, which the shells own",
    ]);
  });

  it("accepts a stated deviation", () => {
    expect(viewProblems("src/core/modules/x/Show.tsx", "// ui-contract-deviation: an audit log has no record page\nexport const S = () => null;")).toEqual([]);
  });

  it("catches columns out of order", () => {
    const text = 'const c = [{ kind: "status" }, { kind: "identifier" }, { kind: "actions" }];';
    expect(columnProblems("columns.tsx", text)).toHaveLength(1);
    expect(columnProblems("columns.tsx", 'const c = [{ kind: "identifier" }, { kind: "data" }, { kind: "data" }, { kind: "actions" }];')).toEqual([]);
  });
});
