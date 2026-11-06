/**
 * Every plugin's catalogue stays in its lane (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4d).
 *
 * A plugin's copy lives under ONE top-level key, its name; core mounts it there (ExtendMessages) and
 * drops anything else. This test refuses it before it ships:
 *
 * - every catalogue holds exactly one top-level key, the plugin's name; `en` (the source) exists;
 * - the name is not one of core's namespaces (backend RESERVED_LABELS refuses it at scaffold time);
 * - every translation is a subset of the source and matches it key by key (validate.ts: no stale
 *   keys, the same arguments and tags, and every message formats);
 * - two-way inside the plugin: every key its code uses exists, and every source key is used;
 * - its code reads only its own namespace, and core's `common` read-only;
 * - its pages hold no literal copy (the same lint rules as core's translated directories).
 *
 * Scope: the example plugins, the scaffold template (rendered) and any linked plugin, so it runs
 * whether or not a plugin is linked. Positive controls below prove each check fires.
 */
import { existsSync, readdirSync, readFileSync, realpathSync, statSync } from "node:fs";
import path from "node:path";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

import { SOURCE_LOCALE, SOURCE_MESSAGES, type Tree } from "@/core/lib/i18n/messages";
import { catalogueProblems } from "@/core/lib/i18n/validate";

import { leaves, references } from "./i18n-scan";
import { FRONTEND } from "./walk";

const REPO = path.resolve(FRONTEND, "..");
const CORE_NAMESPACES = new Set(Object.keys(SOURCE_MESSAGES));
const CORE_KEYS = new Set(leaves(SOURCE_MESSAGES));
const SHARED = "common";

export type PluginSource = {
  /** Where it came from, for messages. */
  where: string;
  name: string | null;
  catalogues: Record<string, Tree>;
  files: { file: string; text: string }[];
};

// The scaffold template's placeholders, rendered as `scripts/plugins.py new example` would.
const TEMPLATE_VALUES: Record<string, string> = {
  name: "example",
  label: "example",
  title: "Example",
  route: "example",
  package: "djx_example",
};
const renderTemplate = (text: string) => text.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, key: string) => TEMPLATE_VALUES[key] ?? key);

function* filesUnder(root: string): Generator<string> {
  for (const entry of readdirSync(root).sort()) {
    const full = path.join(root, entry);
    if (statSync(full).isDirectory()) yield* filesUnder(full);
    else yield full;
  }
}

function readPlugin(root: string, where: string, template = false): PluginSource {
  const files: PluginSource["files"] = [];
  const catalogues: PluginSource["catalogues"] = {};
  for (const full of filesUnder(root)) {
    const relative = path.relative(root, full).split(path.sep).join("/").replace(/\.tmpl$/, "");
    const raw = readFileSync(full, "utf8");
    const text = template ? renderTemplate(raw) : raw;
    const catalogue = /^messages\/([A-Za-z0-9-]+)\.json$/.exec(relative);
    if (catalogue) catalogues[catalogue[1]] = JSON.parse(text) as Tree;
    else if (/\.tsx?$/.test(relative) && !/\.(test|spec)\.tsx?$/.test(relative)) files.push({ file: relative, text });
  }
  const index = files.find((f) => /^index\.tsx?$/.test(f.file));
  const name = index ? (/\bname:\s*"([^"]+)"/.exec(index.text)?.[1] ?? null) : null;
  return { where, name, catalogues, files };
}

/** Every plugin this checkout can see, once each (a linked plugin is a symlink to an example). */
function allPlugins(): PluginSource[] {
  const found = new Map<string, PluginSource>();
  const examples = path.join(REPO, "examples", "plugins");
  for (const plugin of existsSync(examples) ? readdirSync(examples).sort() : []) {
    const root = path.join(examples, plugin, "frontend");
    if (existsSync(root)) found.set(realpathSync(root), readPlugin(root, `examples/plugins/${plugin}/frontend`));
  }
  const linked = path.join(FRONTEND, "src", "plugins");
  for (const prefix of existsSync(linked) ? readdirSync(linked).sort() : []) {
    const root = path.join(linked, prefix);
    if (statSync(root).isDirectory() && !found.has(realpathSync(root))) {
      found.set(realpathSync(root), readPlugin(root, `src/plugins/${prefix}`));
    }
  }
  const template = path.join(REPO, "scripts", "plugin_template", "frontend");
  found.set(template, readPlugin(template, "scripts/plugin_template/frontend", true));
  return [...found.values()];
}

/** Every catalogue and reference problem of one plugin (lint is checked separately). */
export function pluginProblems(plugin: PluginSource): string[] {
  const at = (text: string) => `${plugin.where}: ${text}`;
  const problems: string[] = [];
  const { name, catalogues } = plugin;
  if (!name) return [at("index.ts declares no `name`")];
  if (CORE_NAMESPACES.has(name)) problems.push(at(`its name "${name}" is one of core's namespaces`));

  const tags = Object.keys(catalogues);
  const uses = plugin.files.flatMap(({ file, text }) => references(`${plugin.where}/${file}`, text));
  if (!tags.length) {
    if (uses.length) problems.push(at("translates copy but ships no messages/en.json"));
    return problems;
  }
  const source = catalogues[SOURCE_LOCALE];
  if (!source) return [...problems, at(`ships catalogues (${tags.join(", ")}) but no messages/${SOURCE_LOCALE}.json`)];

  for (const [tag, catalogue] of Object.entries(catalogues)) {
    const foreign = Object.keys(catalogue).filter((key) => key !== name);
    if (foreign.length) problems.push(at(`messages/${tag}.json defines keys outside "${name}": ${foreign.join(", ")}`));
    if (!(name in catalogue)) problems.push(at(`messages/${tag}.json has no "${name}" key`));
    problems.push(...catalogueProblems(source, catalogue, tag).map((p) => at(`messages/${tag}.json: ${p}`)));
  }

  const own = new Set(leaves({ [name]: source[name] ?? {} }));
  for (const use of uses) {
    if (use.key === null) {
      problems.push(`${use.file}:${use.line}: translate with a string-literal key and namespace`);
      continue;
    }
    const top = use.key.split(".", 1)[0];
    if (top === name) {
      if (!own.has(use.key)) problems.push(`${use.file}:${use.line}: ${use.key} is not in messages/${SOURCE_LOCALE}.json`);
    } else if (top === SHARED) {
      if (!CORE_KEYS.has(use.key)) problems.push(`${use.file}:${use.line}: ${use.key} is not one of core's keys`);
    } else {
      problems.push(`${use.file}:${use.line}: ${use.key} is outside the plugin's namespace (only "${name}" and core's "${SHARED}")`);
    }
  }
  const used = new Set(uses.map((use) => use.key));
  const orphans = [...own].filter((key) => !used.has(key));
  if (orphans.length) problems.push(at(`messages/${SOURCE_LOCALE}.json keys nothing uses: ${orphans.join(", ")}`));
  return problems;
}

const COPY_RULES = new Set(["react/jsx-no-literals", "no-restricted-syntax"]);

/** Lint findings in a plugin's pages, linted as if linked at src/plugins/<name>/. */
async function pluginLint(plugin: PluginSource): Promise<string[]> {
  const eslint = new ESLint({ cwd: FRONTEND });
  const found: string[] = [];
  for (const { file, text } of plugin.files) {
    const [result] = await eslint.lintText(text, { filePath: path.join(FRONTEND, "src", "plugins", plugin.name ?? "x", file) });
    for (const m of result.messages) if (COPY_RULES.has(m.ruleId ?? "")) found.push(`${plugin.where}/${file}:${m.line}: ${m.message.slice(0, 60)}`);
  }
  return found;
}

const PLUGINS = allPlugins();

describe("plugin catalogues", () => {
  it("are found: the example and the scaffold template at least", () => {
    expect(PLUGINS.map((p) => p.where)).toEqual(expect.arrayContaining(["examples/plugins/notes/frontend", "scripts/plugin_template/frontend"]));
    expect(PLUGINS.find((p) => p.where === "examples/plugins/notes/frontend")?.catalogues).toHaveProperty("de");
  });

  it("stay in their lane, match their source, and are used both ways", () => {
    expect(PLUGINS.flatMap(pluginProblems)).toEqual([]);
  });

  it("hold no literal copy in plugin pages", async () => {
    const found = (await Promise.all(PLUGINS.map(pluginLint))).flat();
    expect(found).toEqual([]);
  }, 60_000);
});

describe("plugin catalogue checks (positive controls)", () => {
  const base = (over: Partial<PluginSource>): PluginSource => ({
    where: "probe",
    name: "notes",
    catalogues: { en: { notes: { title: "Notes", count: "{count, plural, one {# note} other {# notes}}" } } },
    files: [{ file: "page.tsx", text: 'const t = useT("notes"); t("title"); t("count", { count: 1 });' }],
    ...over,
  });

  it("a clean plugin passes", () => {
    expect(pluginProblems(base({}))).toEqual([]);
  });

  it("refuses a catalogue that defines keys outside the plugin's name", () => {
    const catalogues = { en: { notes: { title: "Notes", count: "{count, plural, one {# note} other {# notes}}" }, users: { title: "Hijack" } } };
    expect(pluginProblems(base({ catalogues })).join("\n")).toMatch(/outside "notes": users/);
  });

  it("refuses a reference into another namespace, and allows core's common", () => {
    const files = [{ file: "page.tsx", text: 'const t = useT("notes"); t("title"); t("count", {count: 1}); const u = useT("users.index"); u("title"); const c = useT("common"); c("cancel");' }];
    const problems = pluginProblems(base({ files })).join("\n");
    expect(problems).toMatch(/users\.index\.title is outside the plugin's namespace/);
    expect(problems).not.toMatch(/common\.cancel/);
  });

  it("refuses a translation key the source does not have", () => {
    const catalogues = { ...base({}).catalogues, de: { notes: { title: "Notizen", stale: "Alt" } } };
    expect(pluginProblems(base({ catalogues })).join("\n")).toMatch(/messages\/de\.json: notes\.stale: not in the source/);
  });

  it("refuses a name that is one of core's namespaces, and a missing source catalogue", () => {
    expect(pluginProblems(base({ name: "theme", catalogues: { en: { theme: { title: "x" } } }, files: [{ file: "p.tsx", text: 'const t = useT("theme"); t("title");' }] })).join("\n")).toMatch(/one of core's namespaces/);
    expect(pluginProblems(base({ catalogues: { de: { notes: { title: "Notizen" } } } })).join("\n")).toMatch(/no messages\/en\.json/);
  });

  it("refuses orphans and keys missing from the source", () => {
    const files = [{ file: "page.tsx", text: 'const t = useT("notes"); t("title"); t("nope");' }];
    const problems = pluginProblems(base({ files })).join("\n");
    expect(problems).toMatch(/notes\.nope is not in messages\/en\.json/);
    expect(problems).toMatch(/keys nothing uses: notes\.count/);
  });

  it("lint finds literal copy in a plugin page", async () => {
    const found = await pluginLint(base({ files: [{ file: "page.tsx", text: "export const P = () => <h1>Notes</h1>;\n" }] }));
    expect(found).toHaveLength(1);
  });
});
