/**
 * The strict check of a catalogue (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4d), for tests: every
 * message is FORMATTED through next-intl, with sample values built from the source message's
 * arguments, and any ICU error is a problem. It catches what the load-time shape check cannot — a
 * plural with no `other` branch, an unknown argument type — before a translation ships.
 *
 * Also: a translation's keys must exist in the source (no stale keys) and keep the source's shape.
 */
import { createTranslator } from "next-intl";

import { messageShape, type Tree } from "./messages";

function leaves(node: Tree, prefix = ""): [string, string][] {
  return Object.entries(node).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === "string" ? [[path, value] as [string, string]] : leaves(value, path);
  });
}

/** Sample values for a message, from its shape: numbers for number/plural, text otherwise. */
function samples(shape: string): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const part of shape ? shape.split("|") : []) {
    const [kind, name, type] = part.split(":");
    if (kind === "tag") values[name] = (chunks: string) => chunks;
    else if (type === "number" || type === "plural" || type === "selectordinal") values[name] = 2;
    else if (type === "date" || type === "time") values[name] = new Date(0);
    else values[name] = "x";
  }
  return values;
}

/**
 * Problems with `catalogue` in `locale`, checked against `source`. Each problem names its key.
 * Pass the source itself (with its own locale) to check that the source formats.
 */
export function catalogueProblems(source: Tree, catalogue: Tree, locale: string): string[] {
  const sourceText = new Map(leaves(source));
  const problems: string[] = [];
  const errors: string[] = [];
  const t = createTranslator({
    locale,
    messages: catalogue,
    timeZone: "UTC",
    onError: (error) => void errors.push(error.message),
    getMessageFallback: ({ key }) => key,
  });
  for (const [key, text] of leaves(catalogue)) {
    const original = sourceText.get(key);
    if (original === undefined) {
      problems.push(`${key}: not in the source catalogue (a stale key)`);
      continue;
    }
    const expected = messageShape(original);
    if (expected === null) {
      problems.push(`${key}: the source message does not parse`);
      continue;
    }
    if (messageShape(text) !== expected) {
      problems.push(`${key}: its arguments or tags differ from the source, or it does not parse`);
      continue;
    }
    errors.length = 0;
    (t.markup as (key: string, values: Record<string, unknown>) => string)(key, samples(expected));
    if (errors.length) problems.push(`${key}: ${errors.join("; ")}`);
  }
  return problems;
}
