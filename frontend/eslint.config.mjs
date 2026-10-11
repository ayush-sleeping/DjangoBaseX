import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// The core/project boundary (ADR-0010): project may import core; core never imports project.
// A product takes core updates by replacing core's files, which only works while core knows
// nothing about any product. See src/project/README.md.
const CORE_IMPORTS_PROJECT =
  "Core must not import project code (ADR-0010, src/project/README.md). Move the shared part into " +
  "src/core/, or invert the dependency so project code calls core.";

// Core never names a plugin either: it reads src/plugins/registry.generated.ts only through the
// (plugins) catch-all route, which lives outside src/core/ (CORE_ARCHITECTURE_PLAN § 5, § 6).
const CORE_IMPORTS_PLUGIN =
  "Core must not import plugin code (CORE_ARCHITECTURE_PLAN § 6). A plugin registers; core reads " +
  "the registry.";
// A plugin's frontend half (symlinked into src/plugins/<name>) imports core and its own files
// only: never the product, another plugin, or a route's private components (§ 4).
const PLUGIN_IMPORTS_OUTWARD =
  "A plugin imports @/core/… and its own files only: never @/project, another plugin, or @/app " +
  "(CORE_ARCHITECTURE_PLAN § 4). Use a signal, a core contract or an API call instead.";

const PLUGIN_DEPTHS = [0, 1, 2, 3, 4, 5];

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
            { regex: "^@/plugins(/|$)", message: CORE_IMPORTS_PLUGIN },
            { regex: "^\\.{1,2}/(.*/)?plugins(/|$)", message: CORE_IMPORTS_PLUGIN },
          ],
        },
      ],
    },
  },
  // One block per directory depth inside a plugin, so `../` is refused only when it climbs out of
  // the plugin's own root: src/plugins/<name>/a.ts may not use ../, but …/<name>/x/b.ts may use
  // ../a. Files nested more than six directories deep are not checked for ../; keep plugins flatter.
  ...PLUGIN_DEPTHS.map((depth) => ({
    files: [`src/plugins/*/${"*/".repeat(depth)}*`],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            { regex: "^@/(project|plugins|app)(/|$)", message: PLUGIN_IMPORTS_OUTWARD },
            { regex: `^(\\.\\./){${depth + 1},}`, message: PLUGIN_IMPORTS_OUTWARD },
          ],
        },
      ],
    },
  })),
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
