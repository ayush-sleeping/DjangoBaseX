# Next.js Standards

**Conventions for the frontend.** Installed: **Next.js 16.3.4, React 19.2.8, Tailwind CSS 4,
TypeScript 5** — read [`frontend/package.json`](../../frontend/package.json) rather than trusting
this line if it matters.

---

## 0. ⚠️ Read this before writing any Next.js code

**Most published Next.js advice — and most model training data — assumes Next 13 or 14. This is 16.**
What changed is not cosmetic:

- **`params` and `searchParams` are `Promise`s.** `const { id } = await params`. Destructuring them
  synchronously does not compile.
- Caching defaults moved. Do not assume a `fetch` is cached, or that it isn't.
- App Router conventions shifted between 14 and 16.

Next 16 ships **bundled agent docs** at `frontend/node_modules/next/dist/docs/`. Read the relevant
guide there. Verify the version rather than recalling it:

```bash
node -e "console.log(require('./frontend/node_modules/next/package.json').version)"
```

### `frontend/AGENTS.md` is generated — never hand-edit it

`next dev` writes and re-adds that file (see
`frontend/node_modules/next/dist/server/lib/generate-agent-files.js`). Editing it is wasted work:
removing it from a diff only re-creates the uncommitted change, and your edits are overwritten on the
next `next dev`. Commit it with your work to keep the tree clean. **Frontend rules go in the root
`AGENTS.md` or in this file.**

---

## 1. Layout

| Path | Holds |
|------|-------|
| `src/app/` | Routes only. A folder with `page.tsx` is a route |
| `src/core/lib/` | Everything that is not a route or a component — API client, helpers, types |
| `src/core/lib/api.ts` | **The only module that makes HTTP calls** |
| `src/core/shells/` | `ResourceIndex` / `ResourceForm` / `ResourceShow`: every module screen composes one of these, never its own layout |
| `src/core/modules/<name>/` | A core module (`users` is the reference): `Index/Form/Show.tsx`, `columns.tsx`, `fields.ts`, `actions.ts`, `keys.ts` |
| `src/core/components/` | The mandatory primitives (§ 5): Button, Modal, confirm/toast, Select family, FormField, StatusPill, … |
| `src/core/styles/tokens.css` | Every colour, both themes; the only place a colour value is written |
| `src/core/shell/` | The shell: the menu and the route gate (`nav/resolve-route.ts` is the one deepest-prefix function) |
| `src/generated/` | Files generated from the backend (`nav-manifest.json`); never hand-edited |
| `src/proxy.ts` | The page-navigation guard (session marker → render; none → `/login?next=`) |
| `public/` | Static assets, served from `/` |

🔜 A `src/components/` directory is not yet present; add it when the second component appears, not
before.

---

## 2. The API boundary — the one rule that matters most

**All backend calls go through `src/core/lib/api.ts`. Never `fetch()` inside a component.**

That wrapper is where the base URL, error shape, headers, and (🔜) auth token handling and refresh
live. A component that calls `fetch()` directly opts out of all of it, and the failure is not
immediate — it shows up when auth lands, or when error handling changes, and then it shows up in
every component that did this.

```ts
// ✅
import { api } from "@/lib/api";
const health = await api.get<HealthResponse>("/api/health/");

// ❌ — bypasses the wrapper
const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/health/`);
```

**Two base URLs, chosen in one place.** The browser calls `NEXT_PUBLIC_API_URL`. Server components
call `INTERNAL_API_URL` when it is set: under Docker, `localhost` inside the frontend container is
the container itself, so they need the container-network address (`http://backend:8000`). `api.ts`
picks between them. Never read either variable anywhere else (`OPERATIONS.md` § 17).

**Type every response.** An untyped API response is an `any` that spreads through the component tree.

🔜 Generating types from the backend's `/api/schema/` is planned (`TECH_DEBT` **DB-4**). Until then
response types are hand-written in `src/core/lib/`, and they can silently drift from the API — which is
exactly why the generation is worth doing.

---

## 2a. Platform and product ([ADR-0010](../adr/0010-platform-layer-is-logical.md))

| Code | Lives in | May import |
|------|----------|-----------|
| Platform library | `src/core/lib/` | `src/core/**` |
| Platform routes | `src/app/(core)/` (route group: URLs carry no `(core)`) | `src/core/**` |
| Product library | `src/project/` | anything, including `@/core/...` |
| Product routes | `src/app/(project)/` | anything |
| Plugin pages | `backend/plugins/<name>/frontend/`, symlinked to `src/plugins/<prefix>` | `@/core/...` and the plugin's own files only |
| Plugin mounting | `src/app/(plugins)/[plugin]/[[...slug]]/`, `src/plugins/registry.generated.ts` | the generated registry |

**The platform never imports the product.** An ESLint `no-restricted-imports` rule in
`eslint.config.mjs` fails `npm run lint` on any `@/project/...`, `@/app/(project)/...` or relative
reach into them from platform files. Two route groups must never serve the same path; Next.js
refuses to build if they do.

**Plugins (BUILD_ORDER 3.5).**
- A plugin's frontend half is mounted by `scripts/plugins.py link <name>`, never by hand. That
  writes the symlink and regenerates `registry.generated.ts`; never edit either.
- Every plugin page is a client component, loaded lazily through the one catch-all route. A static
  route always wins over it, so a plugin cannot shadow a platform page.
- ESLint refuses a plugin import of `@/project`, `@/app`, another plugin, or a `../` that climbs
  out of the plugin's own root, and a platform import of `@/plugins`.
- A plugin may not use a first URL segment the frontend already serves (`/login`, `/settings`):
  the static page would win. `plugins.py` refuses it.
- `npm run lint` is `eslint . src/plugins/*`, because ESLint does not follow symlinked directories
  on its own.
- `next.config.ts` sets `turbopack.root` to the repository so the symlinks resolve (TECH_DEBT
  DB-28, DB-36).

## 3. Server and client components

- **Server by default.** Add `"use client"` only when the component needs state, an effect, an event
  handler, or a browser API
- Push `"use client"` **as far down the tree as possible.** A `"use client"` on a layout makes
  everything beneath it a client component
- **Authenticated data is fetched client-side; public data server-side** (ADR-0009). The session
  is an `httpOnly` cookie, and a server component's own `fetch()` does not carry the browser's
  cookies, so an authenticated call made there **succeeds, anonymously, and renders the empty
  state**. Nothing errors. A server component that genuinely needs authenticated data must read the
  cookies with `cookies()` from `next/headers` and forward them explicitly; that is a reviewed
  exception, not a pattern. Client components use `src/core/lib/auth.ts` / `api()`, which send cookies,
  echo the CSRF cookie on unsafe methods, and refresh-and-retry once on a 401
- **A page whose URL carries a secret** (a reset or invitation token) sets
  `metadata.referrer = "no-referrer"` and `robots: { index: false, follow: false }`. Without
  that, the token leaves in the `Referer` header of any outbound link or third-party asset. It reads
  the token server-side from `searchParams` (async in Next.js 16) and passes it to the client form as
  a prop. See `src/app/(core)/reset-password/page.tsx`
- Never put business logic in a page or a component (`AGENTS.md` § 3). It goes in `src/core/lib/`

---

## 3a. Pages, navigation and permissions (BUILD_ORDER 8.2)

The full contract is [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) § 7–§ 10. The rules a page
author meets:

- **Every page needs a navigation entry.** Navigation is the route gate, and the gate is
  default-deny: a `page.tsx` with no entry renders the denied card for everyone. Register the
  page's `NavItem` from its app's `AppConfig.ready()` — `hidden=True` for a URL-only page,
  `public=True` for a signed-out page — then regenerate `src/generated/nav-manifest.json`
  (`DBX_WRITE_NAV_MANIFEST=1 uv run pytest tests/test_navigation.py`). If you skip that,
  `tests/architecture/route-manifest.test.ts` fails.
- **Permissions only through the provider.** Use `usePermissions()` or `<Can>` from
  `src/core/lib/permissions.tsx`, which bootstrap feeds. Never fetch `/me` to decide what to show,
  never compute a superuser bypass, and render `permissionsError` as a retry path. A shared
  component that may render outside the shell uses `useOptionalPermissions()`, which denies
  everything.
- **Leave the app with a hard navigation only on an identity change** (sign-in, sign-out), through
  `hardNavigate()` in `src/core/lib/session/navigate.ts`. Everything else uses the router.
- **`src/proxy.ts` decides page navigations on the session marker cookie alone.** Never make it read
  the access or refresh cookie, and never make it call the API.

---

## 4. TypeScript

- **`strict` is on.** Keep it on
- **No `any`.** `unknown` plus a narrow, if you genuinely don't know
- **No `@ts-ignore`** without a comment saying why and what would remove it
- Type props explicitly; do not rely on inference across a module boundary
- `npm run typecheck` must pass. It is `next typegen && tsc --noEmit`: the global `PageProps` /
  `LayoutProps` helpers live in generated `.next/types/`, which a fresh clone or CI does not have.
  Bare `tsc --noEmit` passes only on a machine that has already run `next dev`

---

## 5. Styling

- **Tailwind 4**, utility-first. Tailwind 4 is configured through CSS, not `tailwind.config.js` —
  check `postcss.config.mjs` and the global stylesheet before looking for a config file that isn't
  there
- No inline `style={{}}` except for genuinely dynamic values (a computed width, a chart colour)
- Extract a component when a class list repeats, not a `@apply` rule — `@apply` hides the styles from
  the place they are used
- **Colour comes from tokens, never the palette** ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) § 16):
  - Write `bg-primary text-primary-foreground`, `border-border`, `text-muted-foreground`, and
    `bg-err-tint text-err-text`. Never `bg-zinc-900`, `text-white` or `dark:` colour classes.
  - `src/core/styles/tokens.css` holds both themes; ESLint refuses a raw palette class outside
    `src/core/styles/` and `src/core/lib/status-tone.ts`.
  - Pair every fill with its own `-foreground`.
  - Spell a status's classes whole through `status-tone.ts` / `StatusPill`, never `bg-${tone}-tint`.
- **A module screen composes a shell** ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) § 11):
  - An index is `ResourceIndex` with `DataTableColumn`s in the fixed order (identifier → status →
    data → updated → actions); a form is `ResourceForm`; a record is `ResourceShow`.
  - A route file is a thin wrapper: metadata, `<Suspense>` when the view reads the URL, and one
    module component.
  - Lists go through `useListState` + `useApiList`, mutations through `useApiMutation`.
  - A shape the shell lacks is added to the shell, for every module.
  - A deliberate deviation says `ui-contract-deviation: <reason>` where it happens.
  - `module-contract.test.ts` enforces this.
- **Use the primitives** (§ 13 of the same doc), each enforced by ESLint:
  - `Button`/`IconButton`;
  - `Modal`, never a `fixed inset-0` overlay;
  - `confirm()`/`toast()`, never `window.confirm`/`alert`;
  - `Select`/`MultiSelect`/`AsyncSelect`, never a native `<select>`;
  - `SearchInput`, `EmptyState`, `ListLoadError`/`PanelError`, `StatusPill`, and
    `FormField kind=…`.

---

## 6. Environment variables

| Prefix | Visibility |
|--------|-----------|
| `NEXT_PUBLIC_*` | **Inlined into the client bundle. Public. Readable by anyone** |
| everything else | Server-side only |

**A secret must never carry the `NEXT_PUBLIC_` prefix.** This is not a convention — it is how the
bundler decides what to ship to the browser.

`NEXT_PUBLIC_API_URL` is the backend base, `http://localhost:8000` by default. Add any new key to
`frontend/.env.example` with a placeholder, in the same change.

`NEXT_PUBLIC_AUTH_COOKIE_PREFIX` must equal the backend's `AUTH_COOKIE_PREFIX`. The CSRF echo and
the proxy's session-marker check both read the cookies by that name; on a mismatch, writes are
refused and signed-in users are sent to sign-in.

---

## 7. Before you say it's done

```bash
cd frontend
npm run lint
npm run typecheck
```

⚠️ **`npm run build` is not part of the routine gate** — it is slow and it writes `.next/`, which the
running dev server is also using. Run it deliberately, with the dev server stopped, when you have
changed something only a production build exercises.

There are **no frontend tests**. These two commands are the whole safety net; report their real
output (`AGENTS.md` § 1, rule 9).
