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
// One translation entry (FRONTEND_PLATFORM § 22): useT and getServerT from src/core/lib/i18n, which
// alone import next-intl. Its server hooks need a plugin this app does not install, and one entry
// keeps the typed catalogue and the missing-key policy in one place.
const RAW_I18N =
  "Translate with useT (client) or getServerT (server) from @/core/lib/i18n, never next-intl or " +
  "use-intl directly (FRONTEND_PLATFORM § 22).";
const I18N = { regex: "^(next-intl|use-intl)(/|$)", message: RAW_I18N };
// ESLint flat config: a later block REPLACES a rule's options, so every block that configures
// no-restricted-imports must carry these paths and patterns itself.
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
  I18N,
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
// The directories whose copy is fully in the catalogue (BUILD_ORDER 8.4c).
const TRANSLATED = ["src/core/shells/", "src/core/components/", "src/core/modules/", "src/core/shell/", "src/core/theme/"];
// Props and object keys that carry text a user reads, and the calls that show one.
const COPY_PROPS =
  "aria-label|aria-description|aria-placeholder|title|alt|placeholder|label|pendingLabel|submitLabel|confirmLabel|cancelLabel|noun|resource|what|intro|description|hint|body|caption|emptyBody";
const COPY_KEYS = "title|body|label|header|headerTooltip|confirmLabel|cancelLabel|message|error|description|hint|placeholder";
const WORDS = "/[A-Za-z]/";
const COPY_SELECTORS = [
  `JSXAttribute[name.name=/^(${COPY_PROPS})$/] > Literal[value=${WORDS}]`,
  `JSXAttribute[name.name=/^(${COPY_PROPS})$/] > JSXExpressionContainer > Literal[value=${WORDS}]`,
  `JSXAttribute[name.name=/^(${COPY_PROPS})$/] > JSXExpressionContainer > ConditionalExpression > Literal[value=${WORDS}]`,
  `JSXAttribute[name.name=/^(${COPY_PROPS})$/] > JSXExpressionContainer > TemplateLiteral > TemplateElement[value.raw=${WORDS}]`,
  `Property[key.name=/^(${COPY_KEYS})$/] > Literal[value=${WORDS}]`,
  `Property[key.name=/^(${COPY_KEYS})$/] > ConditionalExpression > Literal[value=${WORDS}]`,
  `Property[key.name=/^(${COPY_KEYS})$/] > TemplateLiteral > TemplateElement[value.raw=${WORDS}]`,
  `CallExpression[callee.name='toast'] > Literal[value=${WORDS}]`,
  `CallExpression[callee.name='toast'] > TemplateLiteral > TemplateElement[value.raw=${WORDS}]`,
  `AssignmentPattern[left.name=/^(${COPY_PROPS})$/] > Literal[value=${WORDS}]`,
  // Text computed between tags, which jsx-no-literals does not see.
  `:matches(JSXElement, JSXFragment) > JSXExpressionContainer > TemplateLiteral > TemplateElement[value.raw=${WORDS}]`,
  `:matches(JSXElement, JSXFragment) > JSXExpressionContainer > :matches(ConditionalExpression, LogicalExpression) > Literal[value=${WORDS}]`,
  `:matches(JSXElement, JSXFragment) > JSXExpressionContainer > :matches(ConditionalExpression, LogicalExpression) > TemplateLiteral > TemplateElement[value.raw=${WORDS}]`,
];
const JSX_NO_LITERALS = {
  noStrings: true,
  ignoreProps: true,
  allowedStrings: ["—", "–", "·", "…", "*", "(", ")", ":", "/", "|", "×", "+", "-", ","],
};
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
    scope: [...TRANSLATED, "src/app/"],
    message:
      "Use logical direction (ms/me/ps/pe, start/end, text-start/end, border-s/e, rounded-s/e), not left/right: a right-to-left locale is then a catalogue, not a rewrite (FRONTEND_PLATFORM § 22).",
    selectors: [`Literal[value=/${PHYSICAL}/]`, `TemplateElement[value.raw=/${PHYSICAL}/]`],
  },
  {
    key: "copy",
    home: [],
    // Where every string a user reads comes from the catalogue. src/app/** is held by a ratchet
    // instead (tests/architecture/untranslated-pages.test.ts) until its pages are translated.
    scope: TRANSLATED,
    message:
      "User-facing copy comes from the catalogue: t(\"key\") from useT/getServerT, with the text in src/core/messages/en.json (FRONTEND_PLATFORM § 22). A literal here is English for every locale.",
    selectors: COPY_SELECTORS,
  },
];
// A scoped ban (ban.scope) applies only to files inside its scope: `globs` are a block's files.
const applies = (ban, globs) => !ban.scope || (globs.length > 0 && globs.every((glob) => ban.scope.some((prefix) => glob.startsWith(prefix))));
const uiBans = (except, globs = []) =>
  UI_BANS.filter((ban) => ban.key !== except && applies(ban, globs)).flatMap((ban) =>
    ban.selectors.map((selector) => ({ selector, message: ban.message })),
  );
const SCOPED = [...new Set(UI_BANS.flatMap((ban) => ban.scope ?? []))];
const sourcesUnder = (prefix) => [`${prefix}**/*.ts`, `${prefix}**/*.tsx`];
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
      "no-restricted-imports": ["error", { paths: [AXIOS, TANSTACK], patterns: [I18N] }],
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
  {
    // The one place next-intl is imported: the translation entry, and the tests' source-catalogue
    // provider (which must not read bootstrap).
    files: ["src/core/lib/i18n/**"],
    rules: {
      "no-restricted-imports": ["error", { paths: [AXIOS, TANSTACK], patterns: CORE_PATTERNS.filter((p) => p !== I18N) }],
    },
  },
  {
    files: ["tests/i18n.tsx"],
    rules: { "no-restricted-imports": ["error", { paths: [AXIOS, TANSTACK] }] },
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
            I18N,
          ],
        },
      ],
    },
  })),
  { files: UI_SOURCES, ignores: UI_TESTS, rules: { "no-restricted-syntax": ["error", ...uiBans(null)] } },
  ...SCOPED.map((prefix) => ({
    files: sourcesUnder(prefix),
    ignores: UI_TESTS,
    rules: { "no-restricted-syntax": ["error", ...uiBans(null, [prefix])] },
  })),
  ...UI_BANS.filter((ban) => ban.home.length).map((ban) => ({
    files: ban.home,
    ignores: UI_TESTS,
    rules: { "no-restricted-syntax": ["error", ...uiBans(ban.key, ban.home)] },
  })),
  {
    // Text between tags comes from the catalogue too; punctuation and the empty marker are not copy.
    files: TRANSLATED.flatMap(sourcesUnder),
    ignores: UI_TESTS,
    rules: { "react/jsx-no-literals": ["error", JSX_NO_LITERALS] },
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

// The copy rules, for the untranslated-pages ratchet (tests/architecture/untranslated-pages.test.ts).
export { COPY_SELECTORS, JSX_NO_LITERALS };

export default eslintConfig;
