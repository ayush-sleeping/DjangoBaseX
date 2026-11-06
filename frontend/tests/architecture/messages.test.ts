/**
 * Core's catalogue and core's code agree, both ways (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4c).
 * Plugins' catalogues have their own test, plugin-messages.test.ts (8.4d).
 *
 * - Every key the code translates exists in src/core/messages/en.json (the compiler checks this too,
 *   from the typed catalogue; this also covers what it cannot, such as a dynamic key).
 * - Every key in en.json is translated somewhere: an orphan is copy nobody reads, and it rots.
 * - Each namespace is used only by the code that owns it, so a module's copy moves with the module,
 *   and core's namespaces are reserved plugin names (backend core.plugins.RESERVED_LABELS).
 * - Keys are string literals: `t(\`status.${x}\`)` cannot be checked, so it is refused here.
 *
 * How: the TypeScript AST of every core source file (the scanner is i18n-scan.ts).
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { CATALOGUES, catalogueModule, SOURCE_LOCALE, SOURCE_MESSAGES } from "@/core/lib/i18n/messages";
import { catalogueProblems } from "@/core/lib/i18n/validate";

import { leaves, references } from "./i18n-scan";
import { FRONTEND, iterSources, rel } from "./walk";

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

const catalogue = JSON.parse(readFileSync(CATALOGUE, "utf8")) as Record<string, unknown>;
const KEYS = new Set(leaves(catalogue));
// A linked plugin's files (src/plugins/<prefix>, a symlink) are checked against ITS catalogue by
// plugin-messages.test.ts, not against core's.
const REFS = [...iterSources()]
  .filter((file) => !rel(file).startsWith("src/plugins/"))
  .flatMap((file) => references(rel(file), readFileSync(file, "utf8")));

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

  it("holds only ICU messages that format, with no concatenation seams", () => {
    // Every message formatted through next-intl with sample values (validate.ts): a malformed
    // plural or an unbalanced brace fails here, not on a customer's screen.
    expect(catalogueProblems(SOURCE_MESSAGES, SOURCE_MESSAGES, SOURCE_LOCALE)).toEqual([]);
    const seams = [...KEYS].filter((key) => {
      const text = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], catalogue) as string;
      return text !== text.trim() || text.length === 0;
    });
    expect(seams).toEqual([]);
  });

  it("ships translations that match the source, key by key", async () => {
    const problems: string[] = [];
    for (const [tag, load] of Object.entries(CATALOGUES)) {
      const translated = catalogueModule(await load());
      problems.push(...catalogueProblems(SOURCE_MESSAGES, translated, tag).map((p) => `${tag}: ${p}`));
    }
    expect(problems).toEqual([]);
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
