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

// One transport (FRONTEND_PLATFORM § 2): every backend call goes through src/core/lib/api/, so
// headers, credentials, timeouts, refresh and error decoding are never forgotten by a copy.
const RAW_FETCH =
  "Call the backend through src/core/lib/api (request/upload/download or the api() shim), never " +
  "fetch/XMLHttpRequest/axios directly (FRONTEND_PLATFORM § 2).";
// One data layer (§ 4): callers use useApiQuery/useApiList/useApiMutation, which add the scope
// context to every key, the load-state contract and the required invalidation.
const RAW_TANSTACK =
  "Use useApiQuery / useApiList / useApiMutation from @/core/lib/query, not TanStack's hooks " +
  "directly (FRONTEND_PLATFORM § 4).";
// ESLint flat config: a later block REPLACES a rule's options, so every block that configures
// no-restricted-imports must carry these paths itself.
const AXIOS = { name: "axios", message: RAW_FETCH };
const TANSTACK = {
  name: "@tanstack/react-query",
  importNames: ["useQuery", "useMutation", "useInfiniteQuery", "useQueries", "useSuspenseQuery"],
  message: RAW_TANSTACK,
};
const CORE_PATTERNS = [
  // By alias: @/project/…, @/app/(project)/…
  { regex: "^@/(project|app/\\(project\\))(/|$)", message: CORE_IMPORTS_PROJECT },
  // By relative path: ../../project/…, ../(project)/…, at any depth.
  { regex: "^\\.{1,2}/(.*/)?(project|\\(project\\))(/|$)", message: CORE_IMPORTS_PROJECT },
  { regex: "^@/plugins(/|$)", message: CORE_IMPORTS_PLUGIN },
  { regex: "^\\.{1,2}/(.*/)?plugins(/|$)", message: CORE_IMPORTS_PLUGIN },
];

// The mandatory primitives (FRONTEND_PLATFORM § 13, BUILD_ORDER 8.3a): each ban names the ONE place
// the banned thing may live. All of them are one no-restricted-syntax list, because a later block
// replaces a rule's options: each home's block re-lists every ban except its own.
const PALETTE =
  "(bg|text|border|ring|fill|stroke|from|to|via|divide|outline|placeholder|decoration|shadow|accent|caret)-" +
  "(white|black|(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|" +
  "indigo|violet|purple|fuchsia|pink|rose)-\\d{2,3})";
// left/right utilities and the bare words "left"/"right" used as a direction value.
const PHYSICAL =
  "(^|\\s|:)-?(m[lr]|p[lr]|left|right|border-[lr]|rounded-[lr][tb]?|text-(left|right)|float-(left|right)|scroll-[mp][lr])(-|\\s|$)";
const UI_BANS = [
  {
    key: "table",
    home: ["src/core/components/data-table/**"],
    message: "Lists render through the DataTable (src/core/components/data-table/), never a hand-written <table> (FRONTEND_PLATFORM § 12).",
    selectors: ["JSXOpeningElement[name.name='table']"],
  },
  {
    key: "select",
    home: [],
    message: "Use Select / MultiSelect / AsyncSelect from @/core/components/Select: searchable, styled, async — never a native <select> (§ 13).",
    selectors: ["JSXOpeningElement[name.name='select']"],
  },
  {
    key: "html",
    home: ["src/core/theme/ThemeScript.tsx"],
    message: "dangerouslySetInnerHTML is an XSS sink: render text, or use SafeHtml once it exists (FRONTEND_PLATFORM § 18).",
    selectors: ["JSXAttribute[name.name='dangerouslySetInnerHTML']"],
  },
  {
    key: "overlay",
    home: ["src/core/components/Modal.tsx"],
    message: "A hand-rolled overlay (`fixed inset-0`) skips the focus trap, Escape and scroll lock: use Modal (§ 13).",
    selectors: ["Literal[value=/fixed inset-0/]", "TemplateElement[value.raw=/fixed inset-0/]"],
  },
  {
    key: "dialogs",
    home: [],
    message: "window.confirm/alert/prompt block the page and cannot be styled or tested: use confirm() or toast() from @/core/components (§ 13).",
    selectors: [
      "CallExpression[callee.object.name=/^(window|globalThis)$/][callee.property.name=/^(confirm|alert|prompt)$/]",
      "CallExpression[callee.name=/^(alert|prompt)$/]",
    ],
  },
  {
    key: "palette",
    home: ["src/core/styles/**", "src/core/lib/status-tone.ts"],
    message: "A raw palette colour breaks dark mode and re-branding: use a semantic token (bg-primary text-primary-foreground, bg-err-tint text-err-text…) from src/core/styles/tokens.css (§ 16).",
    selectors: [`Literal[value=/\\b${PALETTE}\\b/]`, `TemplateElement[value.raw=/\\b${PALETTE}\\b/]`],
  },
  {
    key: "storage",
    home: ["src/core/lib/storage/**"],
    message: "localStorage/sessionStorage throw in private modes and break SSR: go through src/core/lib/storage/ (§ 13).",
    selectors: ["Identifier[name=/^(localStorage|sessionStorage)$/]"],
  },
  {
    key: "formatters",
    home: ["src/core/lib/format/**"],
    message:
      "Numbers, amounts, sizes and dates become text only in src/core/lib/format/ (useFormat, <DateTime>, <Money>, <Bytes>): a formatter elsewhere hard-codes a locale or currency into one screen (FRONTEND_PLATFORM § 14).",
    selectors: [
      "FunctionDeclaration[id.name=/^format(Currency|Money|Amount|Price|Cost|Bytes|Size|FileSize|Date|DateTime|Time|Number|Percent)/]",
      "VariableDeclarator[id.name=/^format(Currency|Money|Amount|Price|Cost|Bytes|Size|FileSize|Date|DateTime|Time|Number|Percent)/]",
      "CallExpression[callee.property.name=/^toLocale(String|DateString|TimeString)$/]",
      "NewExpression[callee.object.name='Intl'][callee.property.name=/^(NumberFormat|DateTimeFormat)$/]",
      "CallExpression[callee.object.name='Intl'][callee.property.name=/^(NumberFormat|DateTimeFormat)$/]",
    ],
  },
  {
    key: "physical",
    home: [],
    // Only where the code is already direction-neutral; src/app pages follow when they are translated.
    scope: ["src/core/shells/", "src/core/components/", "src/core/modules/"],
    message:
      "Use logical direction (ms/me/ps/pe, start/end, text-start/end, border-s/e, rounded-s/e), not left/right: a right-to-left locale is then a catalogue, not a rewrite (FRONTEND_PLATFORM § 22).",
    selectors: [`Literal[value=/${PHYSICAL}/]`, `TemplateElement[value.raw=/${PHYSICAL}/]`],
  },
];
// A scoped ban (ban.scope) applies only inside its scope; `inScope` says whether a block's files are.
const uiBans = (except, inScope = false) =>
  UI_BANS.filter((ban) => ban.key !== except && (!ban.scope || inScope)).flatMap((ban) =>
    ban.selectors.map((selector) => ({ selector, message: ban.message })),
  );
const SCOPED = [...new Set(UI_BANS.flatMap((ban) => ban.scope ?? []))];
const withinScope = (globs) => globs.every((glob) => SCOPED.some((prefix) => glob.startsWith(prefix)));
const UI_SOURCES = ["src/**/*.ts", "src/**/*.tsx"];
const UI_TESTS = ["src/**/*.test.ts", "src/**/*.test.tsx"];

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["src/**", "tests/**"],
    ignores: ["src/core/lib/api/**"],
    rules: {
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: RAW_FETCH },
        { name: "XMLHttpRequest", message: RAW_FETCH },
      ],
      "no-restricted-imports": ["error", { paths: [AXIOS, TANSTACK] }],
    },
  },
  {
    files: ["src/core/**", "src/app/(core)/**"],
    rules: {
      "no-restricted-imports": ["error", { paths: [AXIOS, TANSTACK], patterns: CORE_PATTERNS }],
    },
  },
  {
    // The one place TanStack's own hooks are called: the wrappers.
    files: ["src/core/lib/query/**"],
    rules: {
      "no-restricted-imports": ["error", { paths: [AXIOS], patterns: CORE_PATTERNS }],
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
          paths: [AXIOS, TANSTACK],
          patterns: [
            { regex: "^@/(project|plugins|app)(/|$)", message: PLUGIN_IMPORTS_OUTWARD },
            { regex: `^(\\.\\./){${depth + 1},}`, message: PLUGIN_IMPORTS_OUTWARD },
          ],
        },
      ],
    },
  })),
  { files: UI_SOURCES, ignores: UI_TESTS, rules: { "no-restricted-syntax": ["error", ...uiBans(null)] } },
  {
    files: SCOPED.flatMap((prefix) => [`${prefix}**/*.ts`, `${prefix}**/*.tsx`]),
    ignores: UI_TESTS,
    rules: { "no-restricted-syntax": ["error", ...uiBans(null, true)] },
  },
  ...UI_BANS.filter((ban) => ban.home.length).map((ban) => ({
    files: ban.home,
    ignores: UI_TESTS,
    rules: { "no-restricted-syntax": ["error", ...uiBans(ban.key, withinScope(ban.home))] },
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
