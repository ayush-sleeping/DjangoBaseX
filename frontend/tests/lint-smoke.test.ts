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
});
