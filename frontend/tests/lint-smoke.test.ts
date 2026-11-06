/**
 * "The linter actually runs" (FRONTEND_PLATFORM.md § 26): ESLint over one violation per rule this
 * repository adds, asserting each is reported. A dependency bump that breaks the config then fails
 * loudly instead of silently disabling every rule.
 */
import path from "node:path";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const FRONTEND = path.resolve(__dirname, "..");

async function rulesFor(code: string, filePath: string): Promise<string[]> {
  const eslint = new ESLint({ cwd: FRONTEND });
  const [result] = await eslint.lintText(code, { filePath: path.join(FRONTEND, filePath) });
  return result.messages.map((m) => m.ruleId ?? "?");
}

describe("the ESLint rules this repository adds are live", () => {
  it("refuses a raw fetch outside the transport", async () => {
    const rules = await rulesFor('export const x = fetch("/api/x");\n', "src/app/(core)/probe/page.tsx");
    expect(rules).toContain("no-restricted-globals");
  });

  it("allows fetch inside the transport", async () => {
    const rules = await rulesFor('export const x = fetch("/api/x");\n', "src/core/lib/api/probe.ts");
    expect(rules).not.toContain("no-restricted-globals");
  });

  it("refuses TanStack hooks outside the query layer", async () => {
    const rules = await rulesFor(
      'import { useQuery } from "@tanstack/react-query";\nexport const q = useQuery;\n',
      "src/core/shell/probe.tsx",
    );
    expect(rules).toContain("no-restricted-imports");
  });

  it("refuses core importing project", async () => {
    const rules = await rulesFor('import "@/project/x";\n', "src/core/lib/probe.ts");
    expect(rules).toContain("no-restricted-imports");
  });

  // The mandatory primitives (FRONTEND_PLATFORM § 13): one positive control per ban, and its home.
  const UI = "src/app/(core)/probe/page.tsx";
  const banned = async (code: string, file = UI) =>
    (await rulesFor(code, file)).filter((rule) => rule === "no-restricted-syntax").length;

  it.each([
    ["a hand-written <table>", "export const T = () => <table />;\n"],
    ["a native <select>", "export const S = () => <select />;\n"],
    ["dangerouslySetInnerHTML", 'export const H = () => <div dangerouslySetInnerHTML={{ __html: "x" }} />;\n'],
    ["a hand-rolled overlay", 'export const O = () => <div className="fixed inset-0" />;\n'],
    ["window.confirm", 'export const c = () => window.confirm("sure?");\n'],
    ["alert()", 'export const a = () => alert("hi");\n'],
    ["a raw palette class", 'export const P = () => <p className="text-zinc-500" />;\n'],
    ["a raw palette class in a template", "export const P = (x: string) => <p className={`${x} bg-red-600`} />;\n"],
    ["text-white", 'export const W = () => <p className="bg-primary text-white" />;\n'],
    ["localStorage", 'export const l = () => localStorage.getItem("x");\n'],
  ])("refuses %s", async (_name, code) => {
    expect(await banned(code)).toBeGreaterThan(0);
  });

  it("allows semantic tokens and the status tone recipes", async () => {
    expect(await banned('export const P = () => <p className="bg-primary text-primary-foreground bg-neutral-tint text-neutral-text" />;\n')).toBe(0);
  });

  it("allows each banned thing in its one home", async () => {
    expect(await banned('export const O = () => <div className="fixed inset-0" />;\n', "src/core/components/Modal.tsx")).toBe(0);
    expect(await banned("export const T = () => <table />;\n", "src/core/components/data-table/DataTable.tsx")).toBe(0);
    expect(await banned('export const l = () => localStorage.getItem("x");\n', "src/core/lib/storage/index.ts")).toBe(0);
  });

  it("still applies the other bans in a home", async () => {
    expect(await banned('export const P = () => <p className="text-zinc-500" />;\n', "src/core/components/Modal.tsx")).toBeGreaterThan(0);
  });
});
