/**
 * The translation-key scanner shared by messages.test.ts (core's catalogue) and
 * plugin-messages.test.ts (each plugin's): a translator is a const bound to useT("ns") or
 * await getServerT("ns"); every call of it, or of its .rich/.markup/.has/.raw, is a reference.
 */
import ts from "typescript";

import { parse } from "./walk";

const TRANSLATORS = new Set(["useT", "getServerT"]);
const METHODS = new Set(["rich", "markup", "has", "raw"]);

export type Ref = { file: string; line: number; key: string | null; namespace: string };

export function leaves(node: unknown, prefix = ""): string[] {
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
