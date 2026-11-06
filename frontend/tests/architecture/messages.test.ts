/**
 * The catalogue and the code agree, both ways (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4c).
 *
 * - Every key the code translates exists in src/core/messages/en.json (the compiler checks this too,
 *   from the typed catalogue; this also covers what it cannot, such as a dynamic key).
 * - Every key in en.json is translated somewhere: an orphan is copy nobody reads, and it rots.
 * - Each namespace is used only by the code that owns it, so a module's copy moves with the module,
 *   and a plugin's catalogue (when plugins bring one) cannot collide with core's.
 * - Keys are string literals: `t(\`status.${x}\`)` cannot be checked, so it is refused here.
 *
 * How: the TypeScript AST of every source file. A translator is a const bound to useT("ns") or
 * await getServerT("ns"); every call of it, or of its .rich/.markup/.has, is a reference.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { FRONTEND, iterSources, parse, rel } from "./walk";

/** Top-level namespace → the source paths that may use it. `common` is shared by all of core. */
const OWNERS: Record<string, readonly string[]> = {
  common: ["src/core/"],
  components: ["src/core/components/"],
  dataTable: ["src/core/components/data-table/"],
  permissions: ["src/core/lib/permissions.tsx"],
  shell: ["src/core/shell/"],
  shells: ["src/core/shells/"],
  theme: ["src/core/theme/"],
  users: ["src/core/modules/users/", "src/app/(core)/users/"],
};

const CATALOGUE = path.join(FRONTEND, "src/core/messages/en.json");
const TRANSLATORS = new Set(["useT", "getServerT"]);
const METHODS = new Set(["rich", "markup", "has", "raw"]);

type Ref = { file: string; line: number; key: string | null; namespace: string };

function leaves(node: unknown, prefix = ""): string[] {
  if (typeof node === "string") return [prefix];
  return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) => leaves(v, prefix ? `${prefix}.${k}` : k));
}

/** The namespace a `useT("x")` / `await getServerT("x")` initializer names, or null. */
function translatorNamespace(init: ts.Expression | undefined): string | null {
  const call = init && ts.isAwaitExpression(init) ? init.expression : init;
  if (!call || !ts.isCallExpression(call) || !ts.isIdentifier(call.expression) || !TRANSLATORS.has(call.expression.text)) return null;
  const [arg] = call.arguments;
  if (!arg) return "";
  return ts.isStringLiteral(arg) ? arg.text : "<dynamic>";
}

export function references(file: string, text: string): Ref[] {
  const source = parse(file, text);
  const bound = new Map<string, string>();
  const refs: Ref[] = [];
  const line = (node: ts.Node) => source.getLineAndCharacterOfPosition(node.getStart()).line + 1;
  const visit = (node: ts.Node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
      const ns = translatorNamespace(node.initializer);
      if (ns !== null) bound.set(node.name.text, ns);
    }
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const name = ts.isIdentifier(callee)
        ? callee.text
        : ts.isPropertyAccessExpression(callee) && ts.isIdentifier(callee.expression) && METHODS.has(callee.name.text)
          ? callee.expression.text
          : null;
      if (name && bound.has(name)) {
        const ns = bound.get(name)!;
        const [arg] = node.arguments;
        const key = arg && (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) ? arg.text : null;
        refs.push({ file, line: line(node), namespace: ns, key: key === null || ns === "<dynamic>" ? null : ns ? `${ns}.${key}` : key });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return refs;
}

const catalogue = JSON.parse(readFileSync(CATALOGUE, "utf8")) as Record<string, unknown>;
const KEYS = new Set(leaves(catalogue));
const REFS = [...iterSources()].flatMap((file) => references(rel(file), readFileSync(file, "utf8")));

describe("the message catalogue", () => {
  it("is read by the code (the scan is not vacuous)", () => {
    expect(new Set(REFS.map((r) => r.file)).size).toBeGreaterThan(20);
    expect(KEYS.size).toBeGreaterThan(100);
  });

  it("has every key the code translates, and every key is a literal", () => {
    const dynamic = REFS.filter((r) => r.key === null).map((r) => `${r.file}:${r.line}`);
    expect(dynamic, "translate with a string-literal key (and namespace), so it can be checked").toEqual([]);
    const missing = REFS.filter((r) => r.key && !KEYS.has(r.key)).map((r) => `${r.file}:${r.line}: ${r.key}`);
    expect(missing, "add these keys to src/core/messages/en.json").toEqual([]);
  });

  it("has no orphans: every key is translated somewhere", () => {
    const used = new Set(REFS.map((r) => r.key));
    expect([...KEYS].filter((key) => !used.has(key)), "delete these from en.json, or use them").toEqual([]);
  });

  it("gives every namespace an owner, and each is used only by its owner", () => {
    expect(Object.keys(catalogue).filter((ns) => !Object.hasOwn(OWNERS, ns)), "add an owner to OWNERS").toEqual([]);
    const strays = REFS.filter((r) => r.key).flatMap((r) => {
      const top = r.key!.split(".", 1)[0];
      const owners = OWNERS[top] ?? [];
      return owners.some((prefix) => r.file.startsWith(prefix)) ? [] : [`${r.file}:${r.line}: ${r.key}`];
    });
    expect(strays, "move the copy into the file's own namespace").toEqual([]);
  });

  it("holds only ICU messages with balanced braces and no concatenation seams", () => {
    const bad = [...KEYS].filter((key) => {
      const text = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], catalogue) as string;
      let depth = 0;
      for (const ch of text) {
        depth += ch === "{" ? 1 : ch === "}" ? -1 : 0;
        if (depth < 0) return true;
      }
      return depth !== 0 || text !== text.trim() || text.length === 0;
    });
    expect(bad).toEqual([]);
  });
});

describe("the scan (positive controls)", () => {
  it("finds plain, rich, namespaced, root and server references", () => {
    const text = [
      'const t = useT("users.show");',
      "t(\"title\"); t.rich(\"expires\", {});",
      "const all = useT(); all(\"common.cancel\");",
      'const s = await getServerT("users.index"); s("title");',
    ].join("\n");
    expect(references("x.tsx", text).map((r) => r.key)).toEqual(["users.show.title", "users.show.expires", "common.cancel", "users.index.title"]);
  });

  it("flags a dynamic key or namespace", () => {
    expect(references("x.tsx", 'const t = useT("theme"); t(`${mode}`);')[0].key).toBeNull();
    expect(references("x.tsx", "const t = useT(ns); t(\"a\");")[0].key).toBeNull();
  });
});
