/**
 * The pages under src/app still holding English copy (FRONTEND_PLATFORM § 22, BUILD_ORDER 8.4c).
 *
 * src/core's shells, components, modules, shell and theme are fully translated, and lint refuses copy
 * there. The pages under src/app are not yet: this ratchet runs the SAME copy rules over them
 * (react/jsx-no-literals plus the copy selectors from eslint.config.mjs) and holds the list of files
 * that still fail. Two-way: a new page with copy fails (translate it), and a listed page that no
 * longer has any fails (delete it from the list). When the list is empty, src/app joins the lint scope.
 * Do NOT silence this by listing a new page — translate it with getServerT or useT.
 */
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

import { COPY_SELECTORS, JSX_NO_LITERALS } from "../../eslint.config.mjs";

import { assertRatchet, FRONTEND, type Hit } from "./walk";

const LATER = "copy not yet extracted (BUILD_ORDER 8.4c follow-up: the auth and settings pages)";
const UNTRANSLATED: Record<string, string> = {
  "src/app/(core)/accept-invitation/accept-invitation-form.tsx::copy": LATER,
  "src/app/(core)/accept-invitation/page.tsx::copy": LATER,
  "src/app/(core)/account/security/page.tsx::copy": LATER,
  "src/app/(core)/account/security/security-panel.tsx::copy": LATER,
  "src/app/(core)/forgot-password/forgot-password-form.tsx::copy": LATER,
  "src/app/(core)/forgot-password/page.tsx::copy": LATER,
  "src/app/(core)/login/login-panel.tsx::copy": LATER,
  "src/app/(core)/login/page.tsx::copy": LATER,
  "src/app/(core)/page.tsx::copy": LATER,
  "src/app/(core)/reset-password/page.tsx::copy": LATER,
  "src/app/(core)/reset-password/reset-password-form.tsx::copy": LATER,
  "src/app/(core)/settings/roles/[publicId]/page.tsx::copy": LATER,
  "src/app/(core)/settings/roles/[publicId]/role-editor.tsx::copy": LATER,
  "src/app/(core)/settings/roles/page.tsx::copy": LATER,
  "src/app/(core)/settings/roles/role-badges.tsx::copy": LATER,
  "src/app/(core)/settings/roles/roles-panel.tsx::copy": LATER,
};

const COPY_RULES = new Set(["react/jsx-no-literals", "no-restricted-syntax"]);

async function pagesWithCopy(patterns: string[]): Promise<Hit[]> {
  const eslint = new ESLint({
    cwd: FRONTEND,
    overrideConfig: {
      files: ["src/app/**"],
      rules: { "react/jsx-no-literals": ["error", JSX_NO_LITERALS], "no-restricted-syntax": ["error", ...COPY_SELECTORS] },
    },
  });
  const results = await eslint.lintFiles(patterns);
  return results.flatMap((result) => {
    const copy = result.messages.filter((m) => COPY_RULES.has(m.ruleId ?? ""));
    if (!copy.length) return [];
    const file = result.filePath.slice(FRONTEND.length + 1).split("\\").join("/");
    return [{ path: file, line: copy[0].line, value: "copy" }];
  });
}

describe("untranslated pages (src/app)", () => {
  it("only the listed pages still hold copy, and every listed one still does", async () => {
    assertRatchet(await pagesWithCopy(["src/app"]), UNTRANSLATED, "untranslated-pages");
  }, 60_000);

  it("the scan finds copy in a page (positive control)", async () => {
    // A listed page is known to hold copy; if the scan stopped seeing it, the ratchet above would
    // pass vacuously.
    const listed = Object.keys(UNTRANSLATED).map((key) => key.split("::")[0]);
    expect(listed.length).toBeGreaterThan(0);
    expect((await pagesWithCopy([listed[0]])).map((h) => h.path)).toEqual([listed[0]]);
  }, 60_000);
});
