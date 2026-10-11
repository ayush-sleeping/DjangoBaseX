import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// The core/project boundary (ADR-0010): project may import core; core never imports project.
// A product takes core updates by replacing core's files, which only works while core knows
// nothing about any product. See src/project/README.md.
const CORE_IMPORTS_PROJECT =
  "Core must not import project code (ADR-0010, src/project/README.md). Move the shared part into " +
  "src/core/, or invert the dependency so project code calls core.";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["src/core/**", "src/app/(core)/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            // By alias: @/project/…, @/app/(project)/…
            { regex: "^@/(project|app/\\(project\\))(/|$)", message: CORE_IMPORTS_PROJECT },
            // By relative path: ../../project/…, ../(project)/…, at any depth.
            { regex: "^\\.{1,2}/(.*/)?(project|\\(project\\))(/|$)", message: CORE_IMPORTS_PROJECT },
          ],
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
