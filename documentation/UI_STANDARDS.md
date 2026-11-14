# DjangoBaseX — UI standards

> **Status:** Hub — checked 2026-11-14 · Tokens, component kit, shells, i18n catalogue and the lint bans are built (BUILD_ORDER 8.3a/8.3b/8.4); the roles screens are not yet on the shells ([`TECH_DEBT.md`](planning/TECH_DEBT.md) DB-54). Stack read from `frontend/package.json`: Next.js 16, React 19, Tailwind `^4`, next-intl, Vitest.

Deep specs: [`FRONTEND_PLATFORM.md`](system-design/FRONTEND_PLATFORM.md) (§ 5 load states, § 11 module contract, § 12 DataTable, § 13 primitives, § 16 tokens, § 22 i18n) and [`NEXTJS_STANDARDS.md`](system-design/NEXTJS_STANDARDS.md) § 5 (styling). Code rules: [`CODE_STANDARDS.md`](CODE_STANDARDS.md). Siblings: [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md), [`TESTING.md`](TESTING.md), [`system-design/TRAPS.md`](system-design/TRAPS.md).

## 1. Design tokens

| Fact | Where |
|---|---|
| The one home of colour: `@theme inline` (maps `--color-x: var(--x)` into Tailwind), `:root` (light), `[data-theme="dark"]` (dark) | `frontend/src/core/styles/tokens.css`, imported by `frontend/src/app/globals.css` |
| Token families | surface/brand pairs (`background`, `card`, `popover`, `primary`, `secondary`, `muted`, `accent`, `destructive`, each with `-foreground`), `border`, `input`, `ring`, `sidebar*`, and status families `ok`, `warn`, `err`, `info`, `neutral` × `-dot/-text/-tint/-solid/-solid-foreground` |
| Sizing tokens | `--control-h` (2.25rem), `--row-h` (2.75rem) |
| Fonts | `--font-sans`, `--font-mono` (Geist) |
| Dark variant | `@custom-variant dark` keyed on `[data-theme=dark]`; toggled by `frontend/src/core/theme/` (`ThemeScript`, `ThemeToggle`, `theme.ts`) |
| Kept in step | `frontend/src/core/styles/tokens.test.ts` — a token missing from any of the three blocks fails |

**Rule:** use semantic utilities only (`bg-primary text-primary-foreground`, `bg-err-tint text-err-text`). A `-foreground` is never a fill.
**Gold:** `frontend/src/core/components/Button.tsx`. **Anti-pattern:** `bg-red-500`, `text-gray-700`, hex values.
**Check:** `npm run lint` (the `palette` ban in `frontend/eslint.config.mjs`); `frontend/tests/architecture/no-raw-colour-on-tokens.test.ts`.
A brand colour is numbers, never CSS: `oklch()` is composed only from re-validated `{l, c, h}` (`core/lib/security/brand.ts`), and the backend refuses one failing WCAG AA with the measured ratios and a passing suggestion.

## 2. Component kit — use these, never re-create

All under `frontend/src/core/components/` unless noted.

| Need | Component → file | Use when |
|---|---|---|
| Action | `Button`, `IconButton`, `buttonClass` → `Button.tsx` | any click target; variants `primary/secondary/ghost/destructive/link`, sizes `sm/md`; `pending` + `pendingLabel` while saving |
| Surface | `Card` → `Card.tsx` | grouped content |
| Dialog | `Modal` → `Modal.tsx` | any overlay (focus trap, Escape, scroll lock); sizes `sm..xl` |
| Confirm a destructive/irreversible act | `confirm()` + `ConfirmHost` → `confirm.tsx` | replaces `window.confirm`; returns `Promise<boolean>` |
| Feedback | `toast()` → `toast.tsx` (`Toaster` mounted once) | success and transient errors |
| Nothing to show | `EmptyState` (`none` / `filtered`) → `EmptyState.tsx` | a load that succeeded with zero rows |
| List failed to load | `ListLoadError` → `ListLoadError.tsx` | a list/table query failed with nothing to show |
| Panel failed to load | `PanelError` → `PanelError.tsx` | a non-list section/record failed |
| Status | `StatusPill` → `StatusPill.tsx` (+ `lib/statuses.tsx`, `lib/status-tone.ts`) | any status value; tone from the registry, not per screen |
| Tables | `DataTable`, `Pager`, `BulkBar` → `data-table/` | every list; never a hand-written `<table>` |
| Forms | `FormField` → `form/FormField.tsx`, `form/styles.ts` | every input; with react-hook-form + zod |
| Choice | `Select`/`MultiSelect`/`AsyncSelect` → `Select.tsx`; `Switch.tsx`; `SearchInput.tsx` | never a native `<select>` |
| Numbers, dates, money, sizes | `DateTime`, `DateOnly`, `Money`, `Bytes` → `format/index.tsx`; `useFormat` → `lib/format/` | the only place values become text |
| Page layouts | `ResourceIndex`, `ResourceShow`, `ResourceForm` → `frontend/src/core/shells/` | a module supplies columns/queries/actions, never layout |
| Permission-gated UI | `Can` and `DeniedCard` → `frontend/src/core/lib/permissions.tsx` | hide controls the user cannot use; show a visible denial for a whole section |

**Check:** `frontend/src/core/components/primitives.test.tsx`; lint bans `table`, `select`, `html`, `overlay`, `dialogs`, `storage`, `formatters` in `frontend/eslint.config.mjs` (`UI_BANS`). Note: the `storage` ban points at `src/core/lib/storage/`, which does not exist yet — report it before using browser storage.

## 3. Every page state

Render order is **error → loading → empty → data** ([`FRONTEND_PLATFORM.md`](system-design/FRONTEND_PLATFORM.md) § 5). `useApiList`/`useApiQuery` return disjoint `showError`, `isLoading`, `isEmpty`.

| State | Component / rule | Anti-pattern (id) |
|---|---|---|
| Loading | `DataTable` skeleton rows on first load; `isFetching` over rows shows a thin progress bar, never blanks the table | spinner that shifts layout |
| Empty | `EmptyState variant="none"` with a create CTA if permitted; `variant="filtered"` with "Clear filters" | "No X yet" after a failed load ([BC-42](system-design/BUG_CLASSES.md)) |
| Error | `ListLoadError {...list.listErrorProps}` / `PanelError` with retry; plain language, request id from the envelope | raw error text, stack trace |
| Forbidden | `DeniedCard` (visible); the route also refuses via `frontend/src/core/shell/nav/route-gate.tsx`; server is the real gate | hiding silently; treating denied as empty ([BC-07](system-design/BUG_CLASSES.md)) |
| Success | `toast()` with a translated message; mutations `invalidates: [root]` | silent save |
| Pending write | `Button pending pendingLabel`; form errors via `frontend/src/core/shells/form-errors.ts` | double-submit |

**Gold:** `frontend/src/core/shells/ResourceIndex.tsx` (header documents the order); **Check:** `frontend/tests/architecture/no-false-empty.test.ts`, `no-effect-fetch.test.ts`.

## 4. Light and dark

Every colour is a token with a value in both `:root` and `[data-theme="dark"]`, so a screen that uses tokens is dark-ready by construction. **Check:** `tokens.test.ts`; toggle the theme on the screen and view both. A `dark:` utility on a palette colour is a smell — add or fix a token instead.

## 5. Responsive

Tailwind 4 default breakpoints (no override in `tokens.css` or `globals.css`): `sm` 640 · `md` 768 · `lg` 1024 · `xl` 1280 px. Used in core today: `sm:`, `md:`, `lg:`, `xl:`. Tables scroll inside their container, the page does not. Use logical properties (`ms-`, `ps-`, `text-start`) — the `physical` lint ban rejects `ml-`, `pr-`, `text-left` etc. **Check:** view at ~375, 768 and 1366 px; report them.

## 6. Accessibility

| Rule | Gold / mechanism | Check |
|---|---|---|
| Visible keyboard focus on every control | `focus-visible:ring-2 focus-visible:ring-ring` in `Button.tsx` | tab through the screen |
| Overlays trap focus, close on Escape | `Modal` (never `fixed inset-0` by hand) | lint `overlay` ban |
| Every input has a label; errors tied to the field | `FormField` | `primitives.test.tsx` |
| Status is never colour-only: a `StatusPill` carries text | `StatusPill.tsx` | review |
| Icon-only buttons have an `aria-label` from the catalogue | `IconButton` | lint `copy` ban covers `aria-label` |
| Errors and toasts are announced | `PanelError`, `Toaster` | review |

## 7. Copy and i18n

All user-facing strings come from the catalogue: `useT("<namespace>")` (client) or `await getServerT("<namespace>")` (server, e.g. `generateMetadata`) from `@/core/lib/i18n`; text lives in `frontend/src/core/messages/en.json` (namespaces today: `common`, `components`, `dataTable`, `permissions`, `shell`, `shells`, `theme`, `users`). Import `next-intl` only inside `src/core/lib/i18n/`. Plugins keep their own `messages/<locale>.json`. Spec: [`FRONTEND_PLATFORM.md`](system-design/FRONTEND_PLATFORM.md) § 22.
**Gold:** `frontend/src/core/modules/users/Index.tsx` (`useT("users.index")`) and `frontend/src/app/(core)/users/page.tsx`. **Anti-pattern:** a literal in `label=`, `title=`, `placeholder=`, `toast("…")` or a `title:` key in `core/{shells,components,modules,shell,theme}`. **Check:** `npm run lint` (`copy` ban + `jsx-no-literals`); `frontend/tests/architecture/messages.test.ts`, `i18n-scan.ts`.
Terminology and tone: generic, plain language; domain words per product.

## 8. Gold-standard pages

| Page type | Copy this |
|---|---|
| List | `frontend/src/app/(core)/users/page.tsx` → `frontend/src/core/modules/users/Index.tsx` (+ `columns.tsx`, `keys.ts`) |
| Detail | `frontend/src/app/(core)/users/[publicId]/page.tsx` → `frontend/src/core/modules/users/Show.tsx` (+ `show-sections.tsx`) |
| Form | `frontend/src/core/modules/users/Form.tsx`, `InvitationForm.tsx` on `ResourceForm` |
| Tested module | `frontend/src/core/modules/users/users.test.tsx` |

## 9. Anti-patterns

| Never | Why |
|---|---|
| Palette colours, hex | breaks dark mode and re-branding (`palette` ban) |
| Native `<table>`/`<select>`, `window.confirm`, hand-rolled overlay | skips sorting, focus trap, styling, tests |
| `fetch` or `useEffect` + `setLoading` in a page | failed load shown as empty ([BC-42](system-design/BUG_CLASSES.md)) |
| Local date/number/currency formatter | hard-codes a locale ([BC-24](system-design/BUG_CLASSES.md)) |
| Literal English in JSX | untranslatable (`copy` ban) |
| A control gated on a different code than the endpoint enforces | affordance mismatch; use `USER_CODES` in `frontend/src/core/lib/users.ts` |

## 10. Check before "done"

```bash
cd frontend && npm run lint && npm run typecheck && npm test
```

Report must also include: states handled (list them); light + dark and mobile + desktop viewed; an ASCII sketch with real measurements, e.g.

```text
┌ 1366px ────────────────────────────────────────────┐
│ Users                          [ Search…  ] [+ New] │  title row · control h 2.25rem (36px)
├─────────────────────────────────────────────────────┤
│ Email           Name        Status      Roles       │  header
│ a@example.test  A. Person   ● Active    Admin       │  row h 2.75rem (44px)
├─────────────────────────────────────────────────────┤
│ 1–20 of 57                          ‹ 1 2 3 ›       │  Pager
└─────────────────────────────────────────────────────┘
```
