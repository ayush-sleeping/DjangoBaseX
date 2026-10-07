# Frontend Platform

**The Next.js half of the core: one transport, one cache, one load-state contract, one table, one
form stack, one navigation manifest that is also the route gate, and the shell every product and
plugin renders inside.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

**Verified against the installed tree on 2026-09-29, not from memory:** Next.js **16.3.4**, React
**19.2.8**, Tailwind CSS **4.3.3**, TypeScript **5.9.3** (`frontend/node_modules/*/package.json`). From
`frontend/node_modules/next/dist/docs/`:

| Next 16 fact this file depends on | Where verified |
|---|---|
| `middleware.ts` is **deprecated and renamed `proxy.ts`** (v16.0.0); the export is `proxy`. Proxy **defaults to the Node.js runtime** and the `runtime` segment option is not available in it | `01-app/03-api-reference/03-file-conventions/proxy.md` |
| `params` and `searchParams` are `Promise`s | `NEXTJS_STANDARDS.md` § 0, `page.md` |
| `fetch` is **not cached by default**; `cacheComponents` / `'use cache'` is an **opt-in flag** (our `next.config.ts` does not set it) | `02-guides/caching-without-cache-components.md`, `05-config/.../cacheComponents.md` |
| `revalidateTag(tag, profile)` takes **two arguments**; the one-argument form is deprecated. `{ expire: 0 }` expires immediately; it cannot be called from Proxy or client code. `updateTag` works only inside Server Actions | `04-functions/revalidateTag.md`, `updateTag.md` |
| Next reads the nonce from the **request** `Content-Security-Policy` header, and a nonce requires **dynamic rendering** | `02-guides/content-security-policy.md` |
| `error.tsx` receives `retry()` (re-fetch and re-render) and `reset()`; `global-error.tsx` renders its own `<html>`/`<body>` and **does not include global styles** | `03-file-conventions/error.md` |
| `useSearchParams` in a prerendered route opts the tree up to the nearest `<Suspense>` into client rendering | `04-functions/use-search-params.md` |
| `experimental.useOffline` **automatically retries Server Actions** after reconnecting | `05-config/.../useOffline.md` |
| `forbidden()` / `unauthorized()` exist but need the **experimental** `authInterrupts` flag | `04-functions/forbidden.md` |

## Scope — read first

**Owns:** the Next.js platform — composition root and provider order; the transport module and the
typed error taxonomy the frontend decodes; the one data/cache layer and its key contract; the
load-state contract; URL-backed list state; the module UI contract (Index/Form/Show); the DataTable;
mandatory primitives and the lint bans that make them mandatory; formatters; forms; the bootstrap
payload's *frontend contract*; session UX and the session marker cookie; the permission provider;
server-built navigation as the route gate; design tokens; **rendering** of runtime branding;
frontend CSP and security headers; runtime vs build-time env; error boundaries; portals; i18n
rendering; offline policy; frontend cache headers; plugin frontend mounting; frontend tests.

**Does not own:**
- The error **envelope**, the error-code catalogue, list/filter/sort/pagination params, rate limits and
  `Retry-After`, idempotency keys server-side, OpenAPI contract generation → [`API_PLATFORM.md`](API_PLATFORM.md)
- Branding **data**, feature flags, locale/currency/timezone **values**, `APP_ENV`, the settings
  registry → [`CONFIGURATION.md`](CONFIGURATION.md)
- UI slot registries, plugin discovery/lifecycle, the SDK facade, absent-vs-broken → [`EXTENSIBILITY.md`](EXTENSIBILITY.md)
- The error-tracker scrubber, request ids server-side, the "zero is not a fact" figure state → [`OBSERVABILITY.md`](OBSERVABILITY.md)
- Reverse proxy, image build, source-map upload → [`OPERATIONS.md`](OPERATIONS.md)
- Money semantics, bulk-action backend, state machines → [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md)
- Tenancy/organisations and white-label **as a module**, global search → [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md)
- Cookies, tokens, refresh, CSRF, re-auth server-side → [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md)
- General test practice and the ratchet helper → [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md)

Where [`NEXTJS_STANDARDS.md`](NEXTJS_STANDARDS.md) already says something (server-by-default,
`strict`, `NEXT_PUBLIC_` visibility, the `AGENTS.md` gate), this file does not repeat it.

---

## 0. The rules in one screen

1. **Only `src/core/lib/api/` calls `fetch`.** Lint bans it everywhere else. → [§ 2](#2-the-transport-module--tier-1--core)
2. **Errors are decoded once, into typed errors, discriminated by `kind` — never `instanceof` alone, never a stringified `detail`.** → [§ 3](#3-the-typed-error-taxonomy--tier-1--core)
3. **One cache: TanStack Query.** Query keys are the contract; every mutation declares what it invalidates. → [§ 4](#4-one-data-and-cache-layer--tier-1--core)
4. **An error is never rendered as empty.** `isEmpty = isSuccess && items.length === 0`. Render order: error → loading → empty → data. → [§ 5](#5-the-load-state-contract--tier-1--core)
5. **No `useEffect` + `setLoading` fetches.** An AST ratchet test fails the build. → [§ 5](#5-the-load-state-contract--tier-1--core)
6. **List state lives in the URL**, only non-defaults, validated server-side against an allow-list; a filter change resets the page **and clears the selection**. → [§ 6](#6-url-backed-list-state--tier-1--core)
7. **One bootstrap round trip** feeds the shell; its permission list is the **effective** set, computed by the same function the API uses. → [§ 7](#7-the-bootstrap-endpoint--tier-1--core)
8. **The route guard in `proxy.ts` reads a `Path=/` session marker, never the credential cookies.** → [§ 8](#8-session-ux-and-the-session-marker-cookie--tier-1--core)
9. **Identity changes go through one cleanup path:** server revoke → `queryClient.clear()` → clear client context → hard navigation. → [§ 8.4](#84-one-identity-change-cleanup-path)
10. **Permissions fail closed.** A fetch error yields an empty set plus a required `permissionsError`; a missing provider denies everything. → [§ 9](#9-the-permission-provider--tier-1--core)
11. **Gate an affordance by passing its callback, on exactly the permission its endpoint enforces.** Never an `isAdmin` flag. → [§ 9](#9-the-permission-provider--tier-1--core)
12. **The navigation manifest is the route gate.** Deepest-prefix match; a page with no manifest entry is denied. → [§ 10](#10-server-built-navigation-that-is-also-the-route-gate--tier-1--core)
13. **Modules supply columns, fields and handlers — never layout.** Index/Form/Show shells own layout. → [§ 11](#11-the-module-ui-contract--tier-1--core)
14. **Every list is `<DataTable>`; a sortable column must carry a key the API allow-lists.** → [§ 12](#12-the-datatable-standard--tier-1--core)
15. **Primitives are mandatory and lint-enforced:** no raw `<table>`, no native `<select>`, no hand-rolled overlay, no local formatter, no raw palette colour. → [§ 13](#13-mandatory-primitives-and-the-lint-rules-that-make-them-mandatory--tier-1--core)
16. **Every fill token has a `-foreground` pair; status tones are spelled as literal class strings.** → [§ 16](#16-design-tokens--tier-1--core)
17. **Tenant colours are numbers validated against a grammar, never CSS strings;** derived tokens come only from validated input. → [§ 17](#17-runtime-branding-and-white-label-rendering--tier-2--core)
18. **Per-request CSP nonce in `proxy.ts`, Report-Only first, enforcement flipped by a runtime env var.** → [§ 18](#18-frontend-security--tier-1--core)
19. **`NEXT_PUBLIC_*` is for public, build-stable values only.** Everything environment-varying is read at runtime. → [§ 19](#19-runtime-vs-build-time-configuration--tier-1--core)
20. **A mutation is never re-sent automatically** — not by the transport, not by TanStack's offline queue, not by a Server Action retry. → [§ 23](#23-offline-policy-and-cache-headers--tier-2--core)

---

## 1. Layout and the composition root — **Tier 1 · Core**

**What.** The directory split from [`CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md)
§ 5, made concrete, plus one root `Providers` tree whose order is written down.

**Why.** Cross-cutting context (cache, session, permissions, theme, toasts, nonce) mounted ad hoc in
several layouts ends up mounted twice, in the wrong order, or not at all on one portal. A real incident:
the theme library's inline script had no nonce, so the moment CSP was enforced every page lost its
theme — the nonce had never been threaded to the one provider that needed it.

**Rules.**
- `src/core/` never imports `src/project/` or `src/plugins/` (the plan's boundary test).
- `src/core/lib/` holds the transport, cache, formatters, config, storage and helpers;
  `src/core/components/` the primitives and shells; `src/core/shell/` the app chrome.
- **Provider order is fixed**, outermost first: `ErrorBoundary` → `QueryClientProvider` →
  `IdentityProvider` (public branding) → `ThemeProvider(nonce)` → `IntlProvider` → `SessionProvider`
  (bootstrap) → `TenantProvider` (only when tenancy is installed) → `PermissionProvider` →
  `ToastHost` + `ConfirmHost`. Each later provider may read the earlier ones; never the reverse.
- The `QueryClient` is created **once per browser session inside `useState`**, never at module scope
  (module scope leaks one user's cache into another request during SSR).
- Plugins contribute providers through their manifest (§ 25), mounted **inside**
  `PermissionProvider`, in manifest order. A plugin never edits the root layout.
- The root `layout.tsx` is a server component: it reads `x-nonce` from `headers()`, fetches public
  identity (§ 17) and passes both down.

**Django + Next shape.**
```
src/core/lib/api/        transport, errors, per-namespace clients (generated types)
src/core/lib/query/      QueryClient factory, useApiQuery, useApiList, useApiMutation, keys
src/core/lib/format/     the only formatters
src/core/lib/config/     public.ts (NEXT_PUBLIC_ reads), server.ts ('server-only', runtime env)
src/core/components/     DataTable, StatusPill, FormField, Modal, ConfirmHost, EmptyState, …
src/core/shell/          Sidebar, Topbar, SessionGuard, EnvironmentRibbon, ImpersonationBanner
src/core/providers/      Providers.tsx and each provider
src/generated/           contracts exported by the backend (§ 2, § 9, § 10) — never hand-edited
```

**Enforced by.** `tests/architecture/provider-order.test.tsx` renders `Providers` and asserts the
order by probing contexts (a `PermissionProvider` above `SessionProvider` fails). The plan's
`frontend/tests/boundaries.test.ts` covers the import direction.

**Configurable, not hard-coded.** Query defaults (§ 4) and transport timeouts (§ 2) live in
`src/core/lib/config/defaults.ts`, overridable in `src/project/config.ts`.

---

## 2. The transport module — **Tier 1 · Core**

**What.** One module that every backend call goes through, with four entry points sharing one
`buildHeaders()`.

**Why.** A real incident: per-feature copies of the fetch helper read only the base credential and
ignored the active-tenant context, so actions taken while an operator was working inside a customer's
tenant **silently targeted the operator's own tenant**. Separately, hand-rolled upload and download
calls forgot the tenant header and ran against the fallback tenant. Every copy of the transport is a
place a header is forgotten.

**Rules.**
- **Entry points:** `request<T>()` (JSON), `upload<T>()` (`FormData`, **no `Content-Type` set** — the
  browser must write the multipart boundary), `download()` (returns a `Blob` + filename from
  `Content-Disposition`, **or** the parsed job descriptor when the server answers `202 Accepted`,
  meaning "an export job was queued"), and `requestWithTotal<T>()` for the rare endpoint that reports
  totals in `X-Total-Count` rather than the list envelope.
- **`buildHeaders()` is the only place headers are assembled:** `Accept`, `X-CSRF-Token` on unsafe
  methods ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 6.1), `Accept-Language` from the active locale,
  `X-Request-ID` (a client-generated id the backend echoes or replaces), `Idempotency-Key` when the
  caller supplies one, and **every header contributed by a registered context contributor**. The
  active-tenant header is a contributor registered by the tenancy module — core names no tenant
  concept, so a product without tenancy sends nothing.
- `credentials: "include"` on every call. `AbortSignal` is always threaded through (TanStack passes
  one), so an unmounted query cancels its request.
- **Base URL:** in the browser the base is **relative** (`/api`), because the recommended topology
  serves the API on the same origin (§ 8.1). The same bundle then works on any custom or white-label
  host without CORS or preflight. On the server the base is `INTERNAL_API_URL`, read at runtime (§ 19).
- **Timeouts:** a default (`transport.timeoutMs`, 15 s) and an explicit `longTimeout: true` for
  unbounded reads (exports, reports). A real incident: a CSV export killed at the global default
  looked exactly like a server fault.
- **Single-flight refresh.** Concurrent `401`s share one module-level refresh promise; each waiting
  request is replayed **once** after it resolves. The backend's rotation grace window
  ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) A23) is for two *tabs*; it must not be what makes one tab
  with six parallel calls survive.
- The refresh call itself, the logout call and client log shipping bypass the 401 interceptor (a 401
  while handling a 401 must not recurse).
- After every response the transport records `X-Request-ID` and the `X-Permissions-Version` header
  (§ 7) into a tiny store the error surfaces and the bootstrap query read.
- **Per-namespace clients**, one file per backend app or plugin (`src/core/lib/api/users.ts`,
  `src/plugins/billing/api.ts`), typed from the generated OpenAPI types. A barrel re-exports them.
  **Never duplicate a namespace to wrap another** — a copied method set is where a fix lands on one
  copy and not the other.

**Django + Next shape.**
```ts
// src/core/lib/api/client.ts
export async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const res = await send(path, { ...opts, headers: buildHeaders(opts) });
  if (res.status === 401 && !opts.noAuthRetry) return retryAfterRefresh<T>(path, opts);
  if (!res.ok) throw await decodeError(res);            // § 3 — the only decoder
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}
let refreshing: Promise<void> | null = null;             // single flight
function refreshOnce() {
  return (refreshing ??= post("/auth/refresh/", { noAuthRetry: true })
    .finally(() => { refreshing = null; }));
}
```
Types: `openapi-typescript` over the committed `schema.yml` into `src/generated/api.d.ts`.

**Enforced by.**
- ESLint in `eslint.config.mjs`: `no-restricted-globals` for `fetch` and `XMLHttpRequest`, and
  `no-restricted-imports` for `axios`, in every file **except** `src/core/lib/api/**`. A test fixture
  that calls `fetch` must make `eslint` exit non-zero (§ 26 — the "the linter actually runs" check).
- `client.test.ts` (with MSW): six parallel 401s produce exactly **one** refresh call; an upload has
  no `Content-Type`; a download of a `202` returns the job descriptor; every entry point carries the
  contributed headers (the upload/download case is the one that regressed in real life).
- CI runs `openapi-typescript` and fails on `git diff --exit-code src/generated/`.

**Configurable, not hard-coded.** `transport.timeoutMs`, `transport.longTimeoutMs`; context
contributors are a registry (`registerRequestContext(fn)`), not a literal header list.

---

## 3. The typed error taxonomy — **Tier 1 · Core**

**What.** Every non-2xx is decoded **once**, in the transport, into one of a closed set of error
types. Components switch on `err.kind`; nothing downstream parses a response body.

**Why.** Three real incidents, each small, each repeated across dozens of screens:
- A validation failure showed "must be ≤ 2000" with no field name; support had to reproduce the
  request to learn which field was wrong.
- A structured `detail` was `JSON.stringify`-ed into a toast and raw enum codes reached users.
- A throttled signup answered "HTTP 429" and left the button live; one user fired thirteen one-time
  codes in under a minute.

**Rules.**

| `kind` | From | Carries | The UI does |
|---|---|---|---|
| `unauthenticated` | 401 after a failed refresh | — | Opens the re-auth modal (§ 8.3) |
| `reauth_required` | 423 | `actionKey` | Opens step-up confirm, then retries once (§ 8.3) |
| `permission` | 403 | `requiredPermission?` | Denied card / toast naming the permission |
| `entitlement` | 403 with an entitlement code (e.g. `onboarding_incomplete`, `mfa_enrollment_required`, plan/quota) | `code`, `unmet[]`, **`remediationUrl`** | One concrete next action — a link to `remediationUrl`, never the list of codes |
| `payment_required` | 402 | `remediationUrl?`, `details` | Routes to the remediation |
| `not_found` | 404 | — | Not-found surface (invisible rows answer 404 by design, `API_DESIGN.md`) |
| `conflict` | 409 / 412 | `details` | "Changed since you opened it" with reload/compare |
| `validation` | 400 | `fields[] = {path, message, code}`, `nonField[]` | `applyServerErrors` onto the form (§ 15) |
| `rate_limited` | 429 | `retryAfterSeconds` | Cooldown on the control that fired it |
| `server` | 5xx | `requestId` | Error panel with the request id |
| `network` | fetch rejected / timeout | `timedOut` | Connectivity bar (§ 23) |

- **The remediation URL comes from the backend**, never a frontend table mapping codes to routes —
  the backend knows where "finish onboarding" lives in this product; the core frontend does not.
- **`retryAfterSeconds`** prefers the body's `retry_after_seconds`, then the `Retry-After` header
  (delta-seconds **or** HTTP-date), **clamped to `transport.maxRetryAfterSeconds` (3600)** so a bad
  header cannot wedge a button for a day. `useCooldown(err)` returns `{disabled, secondsLeft}` and
  every submit button that can hit a throttled endpoint uses it.
- **Never stringify structured detail.** If no message can be derived, the copy is the code→message
  map entry, else a generic "Something went wrong (HTTP 503)".
- **Copy:** server `message` wins; otherwise the **code→message map generated from the backend error
  catalogue** (`src/generated/error-codes.ts`, one i18n key per code — [`API_PLATFORM.md`](API_PLATFORM.md)
  owns the catalogue). An unknown code in development logs a warning naming it.
- **Field paths** are preserved exactly (`lines.2.quantity`) and prefixed in any non-form rendering:
  "Quantity (line 3): must be ≤ 2000".
- **Discriminate on `kind`, not `instanceof`.** Errors that cross a bundle boundary (a plugin chunk, a
  test mock) fail `instanceof`. `isApiError(e)` checks a brand property; `instanceof` is a fast path
  only.
- Every decoded error carries `status`, `code`, `requestId` and `method + path` (for the error panel
  and the tracker — never the body).

**Django + Next shape.** `src/core/lib/api/errors.ts` exports the classes, `decodeError(res)`,
`isApiError`, `messageFor(err, t)` and `useCooldown`. Backend side: the DRF exception handler emits
the envelope [`API_PLATFORM.md`](API_PLATFORM.md) specifies, **including `request_id`** and, for
entitlement errors, `unmet` and `remediation_url`.

**Enforced by.** `errors.test.ts` covers: nested field paths survive; a stringified-object message is
impossible (a fuzz case feeds objects as `detail`); `Retry-After` in both formats plus the clamp;
unknown codes fall back; a cross-realm error still satisfies `isApiError`. A contract test asserts
every code in the backend catalogue has a message key in the `en` catalogue (§ 22).

**Configurable, not hard-coded.** `transport.maxRetryAfterSeconds`; the code map is generated; the
remediation URLs are backend data.

---

## 4. One data and cache layer — **Tier 1 · Core**

**What.** **TanStack Query v5** is the only server-state cache. Query keys are the contract between
readers and writers.

**Why TanStack Query, in one screen.**

| Need | TanStack Query | Alternatives |
|---|---|---|
| Plugins add resources without a central file | Hierarchical array keys; a plugin owns a key factory | RTK Query centres on one `createApi`; plugins must `injectEndpoints` and tag types widen centrally |
| No global client store | Server state only | RTK Query brings Redux for state we don't have |
| Prefix and cross-cutting invalidation | `invalidateQueries({queryKey})` + `predicate` over `meta` | SWR: key-string matching, no mutation cache |
| Keep rows during refetch; poll while transitional | `placeholderData: keepPreviousData`; function `refetchInterval` | Hand-rolled |
| Cancellation | `signal` into the transport | Hand-rolled race counters |

Next's own `fetch` cache does not help here: authenticated reads are client-side
([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 6.1), where that cache does not exist. A real incident:
twenty-three components fetched on mount by hand, three of them fetched the same endpoint, writes did
not refresh other screens, and every component had grown its own unmount guard.

**Rules.**
- **Keys:** `[resource, kind, context, params]`, e.g. `["users", "list", {tenant}, {q, page}]`.
  `context` is inserted by `useApiQuery` from the active scope (tenant/project; `{}` when none) — a
  caller cannot forget it. Invalidating `["users"]` reaches every users query in every context.
- **Key factories** are declared per resource with `defineKeys(root, …)`. A plugin's roots **must start
  with its plugin key** (`"billing.invoices"`), the same namespace rule as permissions and routes.
- **Queries provide, mutations invalidate.** `useApiMutation` takes a **required** `invalidates`
  option (an array of key roots, or `[]` with a mandatory `reason`). A missing invalidation shows stale
  data with no error, which is why it is a type error rather than a review comment.
- **Derived queries declare what they derive from:** `meta: { dependsOn: ["users", "billing.invoices"] }`.
  `invalidateResource(root)` invalidates by prefix **and** every query whose `dependsOn` includes it.
- **Cross-cutting tags** go in `meta.tags` — e.g. `"restorable"`, so a recycle-bin restore refreshes
  every list without core knowing which lists exist.
- **After a mutation, patch or invalidate — both, when the page patched a row locally.** A page that
  patches a row in component state but not the cache replays pre-mutation data on its next mount
  within `staleTime`.
- **Revalidate the current view, filters included** — never navigate to a bare list URL after a save.
- **Do not copy server data into local state in an effect.** Forms seed from the query and keep their
  own dirty values (§ 15); everything else reads the cache.
- **One-shot secrets are never cached.** A single-use token consumption or a create-response that shows
  a secret once (an API key, a webhook secret) is a **mutation**, not a query, so it never sits in the
  cache after use.
- **Defaults:** `staleTime` 60 s, `gcTime` 5 min, `refetchOnWindowFocus: false`, queries `retry: 1`
  **only for `network` and 502/503/504** (never 4xx), **mutations `retry: 0` and `networkMode: "always"`**
  (§ 23 explains the second).
- **Optional per-query settings are spread in only when defined.** An explicit
  `staleTime: undefined` overrides the default with `0` and silently triples request volume.
- **Polling only while a status is transitional:** `refetchInterval: q => isTransitional(q.state.data) ? 3000 : false`.
  "Transitional" comes from the status metadata the backend serves (§ 13), not a frontend list.
  Background tabs do not poll.
- **A finished job announces itself:** `useJobStatus(id)` polls while running and fires one toast on
  the edge to done/failed, via a module-level toast store that outlives the page.
- **Public, cacheable data** (identity, public config) is fetched in server components with
  `next: { tags }` and seeded into the client cache (`initialData` / `HydrationBoundary`).

**Django + Next shape.**
```ts
// src/plugins/billing/keys.ts
export const invoiceKeys = defineKeys("billing.invoices", {
  list: (p: InvoiceListParams) => ["list", p],
  detail: (id: string) => ["detail", id],
});
// usage
const archive = useApiMutation({
  mutationFn: (id: string) => billingApi.invoices.archive(id),
  invalidates: [invoiceKeys.root],
});
```

**Enforced by.**
- Type level: `invalidates` is required on `useApiMutation`.
- `tests/architecture/query-keys.test.ts`: every `defineKeys` root in `src/plugins/<name>/` starts with
  `<name>.`; roots are unique across the tree; the factory registry is alphabetised so two concurrent
  additions conflict visibly in review.
- ESLint `no-restricted-imports` bans `@tanstack/react-query`'s `useQuery`/`useMutation` outside
  `src/core/lib/query/` — callers use the wrappers.

**Configurable, not hard-coded.** `query.staleTimeMs`, `query.gcTimeMs`, `query.retry`,
`query.refetchOnWindowFocus`, `poll.transitionalIntervalMs` in `src/core/lib/config/defaults.ts`.

---

## 5. The load-state contract — **Tier 1 · Core**

**What.** `useApiQuery` and `useApiList` wrap TanStack and return a shape where **failure, loading,
empty and data are disjoint** — and the page renders them in that order.

**Why.** A real incident, measured: roughly three quarters of a large product's pages hand-rolled
`useEffect` + `setLoading`, and shipped the same three defects over and over — a failed fetch rendered
as an authoritative "No invoices yet"; no cancellation, so a slow response overwrote a newer one; and a
cache not keyed by tenant, so the previous tenant's rows appeared after a switch. "No invoices yet"
shown to a billing user after a network blip reads as "your invoices are gone."

**Rules.**
- `useApiQuery` returns `data` (last-good, retained on a failed refetch), `isLoading` (**first load
  only**), `isFetching` (any request in flight), `isError`, `isSuccess`, `error`, **`showError`
  (= failed AND nothing to show)**, `refetch()` (awaitable, **never rejects**) and `queryKey`.
- `useApiList` adds `items`, `count`, **`isEmpty = isSuccess && items.length === 0`** — never
  `!isLoading && …`, because a disabled query is neither loading nor errored — and `listErrorProps`
  to spread into `<ListLoadError>`.
- **Render order is error → loading → empty → data.** `isLoading` draws skeletons; `isFetching` over
  existing rows draws a thin progress bar and never blanks the table.
- **A failed background refetch keeps the data** and toasts **once per distinct error** (keyed by
  `kind + code + status`): "Couldn't refresh — showing the last loaded copy."
- **Form-seeding queries** (`purpose: "form-seed"`) set `refetchOnReconnect: false` and
  `refetchOnWindowFocus: false`. Otherwise a reconnect replaces the user's half-typed draft.
- **Lists wait for their URL state.** A list whose filters are restored on the client passes
  `enabled: urlState.ready` — otherwise it fires one request with default filters, flashes the wrong
  rows, then fires again.
- **No `useEffect` + `setLoading` fetches.** Not in pages, not in components, not "just this once".

**Django + Next shape.**
```tsx
const users = useApiList(userKeys.list(params), () => usersApi.list(params), { enabled: ready });
if (users.showError) return <ListLoadError {...users.listErrorProps} resource={t("users.plural")} />;
if (users.isLoading) return <DataTable.Skeleton rows={params.pageSize} />;
if (users.isEmpty) return <EmptyState variant={hasFilters ? "filtered" : "none"} … />;
return <DataTable rows={users.items} fetching={users.isFetching} … />;
```

**Enforced by.**
- `tests/architecture/no-effect-fetch.test.ts` — a TypeScript-AST walk of `src/**/*.tsx`: fails on any
  `useEffect` whose body calls a transport function, `fetch`, or a setter matching
  `/^set(Is)?Loading$/`. **Two-way ratchet:** an allow-list that starts empty in a fresh core; every
  entry must *still* offend, so fixing a file forces its removal and the list only shrinks.
- `tests/architecture/no-false-empty.test.ts` — AST: fails on `!isLoading && <x>.length === 0` and on
  an `EmptyState` rendered in a component that does not read `isEmpty` or `showError`. The file
  header states its blind spot (it checks presence, not branch order) and where order is tested
  instead (`use-api-query.test.tsx`).
- `use-api-query.test.tsx`: disabled query is not empty; failed refetch retains data and toasts once
  for two identical failures and twice for two different ones; `refetch()` resolves on failure.

**Configurable, not hard-coded.** Toast copy through i18n; the dedupe key function is a core export.

---

## 6. URL-backed list state — **Tier 1 · Core**

**What.** `useUrlState(schema)` and `usePagedQuery({ keys, schema, fetchPage })` keep search, filters,
sort, page and page size in the URL, shared by every list.

**Why.** Shareable links, a working Back button and a refresh that keeps your place. And a real
incident: a selection held in a second `Set` outside the list hook meant every bulk button acted on
nothing — the rows were selected in one place and read from another.

**Rules.**
- **Only non-default values appear in the URL.** A clean URL is a readable, shareable URL.
- **A change to anything except `page` resets `page` to 1 and clears the selection.** A bulk action
  must never reach rows the user can no longer see.
- **Selection lives only in this hook.** DataTable receives it; nothing else holds a copy.
- **Text is debounced by `SearchInput`** (500 ms, 2-character minimum); pages never debounce again.
  Selects, toggles and dates apply immediately.
- **Writes use `history.replaceState`** (Next integrates it with `useSearchParams`), so thirty
  keystrokes do not make thirty history entries and Back leaves the list.
- **Read once, hydration-safe.** The page is a server component: it awaits `searchParams`, validates
  them against the surface's **zod allow-list** (unknown keys dropped, invalid values → default, never
  a 500) and passes `initialState` as a prop. The client hook seeds from that prop and never reads
  `window.location` during render. On a purely client surface the hook reads once in a mount effect and
  exposes `ready`.
- **Parameter names are the platform's** (`q`, `ordering`, `page`, `page_size`, `<field>`,
  `<field>__gte`) — [`API_PLATFORM.md`](API_PLATFORM.md) fixes them, so one hook works on every list.
- `page_size` options never exceed the server's `max_page_size` (from bootstrap).
- A `page` past the end (rows were deleted, filters changed elsewhere) clamps to the last page once the
  count is known.
- **Server components validate `searchParams` for every page**, list or not (`?tab=`, `?view=`), with
  the same schema helper.

**Django + Next shape.**
```tsx
// src/app/(app)/users/page.tsx — server component
export default async function Page({ searchParams }: PageProps<"/users">) {
  const initial = userListSchema.parse(await searchParams);   // allow-list + defaults
  return <UsersIndex initialState={initial} />;
}
// in UsersIndex (client)
const list = usePagedQuery({ keys: userKeys, schema: userListSchema, initialState,
  fetchPage: p => usersApi.list(p) });
```

**Enforced by.** `use-url-state.test.tsx` (defaults omitted; filter change → page 1 + selection
empty; replace not push; invalid values fall back). ESLint bans `useSearchParams` and
`window.location.search` outside `src/core/lib/url/`.

**Configurable, not hard-coded.** `list.searchDebounceMs`, `list.searchMinChars`,
`list.pageSizeOptions` (capped by the server), per-surface defaults in the schema.

---

## 7. The bootstrap endpoint — **Tier 1 · Core**

**What.** `GET /api/me/bootstrap/` — the shell's **one** round trip after sign-in. It supersedes
`/api/auth/me/` *as the shell call*; `/me` stays as the identity endpoint.

**Why.** A shell assembled from six ad-hoc endpoints (flags here, capabilities there, a feature
toggle fetched separately in one layout) has six failure modes and three answers to "is this feature
on". And a real incident: an owner bypass existed on the server but not in the role-derived permission
list, so owners were hidden from actions they were allowed to take — the UI and the API disagreed
because they computed permissions differently.

**Rules.**
- **`permissions` is the *effective* set** for the active scope — after the superuser and any owner
  bypass are expanded — **computed by the same backend function `has_perm()` uses.** The frontend
  never special-cases a bypass.
- **Essential vs decorative sections.** `user`, `permissions` and `session` failing fails the whole
  response (the provider then fails closed, § 9). Decorative contributors (badge counts, notification
  count) are **failure-isolated**: a raising contributor is omitted and listed in `degraded[]`. A
  broken bell must never break sign-in.
- **Permission freshness:** every API response carries `X-Permissions-Version` (the counter from
  [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 7.4). When it differs from the bootstrap's version the
  transport invalidates the bootstrap query, so a revoked grant leaves the UI within one request.
- **Refetched on tenant change** (its key contains the tenant) and on permission-version change —
  not on window focus.
- **Mandatory prompts are data, routed by the shell:** `must_change_password` and
  `mfa_enrollment_required` send every route to the one page that clears them.
- **`server_time`** is included so countdowns (session, impersonation) are computed against the
  server's clock, not a drifting laptop's.
- **`build`** is included; a mismatch with the running bundle's `NEXT_PUBLIC_APP_VERSION` shows a
  "new version — reload" banner (§ 23).
- `Cache-Control: no-store` like every authenticated response.

**Django + Next shape.**
```jsonc
{ "user": { "id": "…", "email": "…", "full_name": "…", "initials": "…", "avatar_url": null,
            "is_superuser": false, "must_change_password": false,
            "preferences": { "theme": "system", "accent": "default", "density": "comfortable" } },
  "permissions": ["users.users.view", "…"], "permissions_version": 42, "roles": [{ "slug": "staff" }],
  "scope": { "tenant": null, "available_tenants": [] },          // present only with tenancy
  "flags": { "billing.new_checkout": true }, "capabilities": { "payments": true },
  "nav": [ … ], "nav_preferences": { "billing": "collapsible" },  // § 10
  "localization": { "locale": "en", "timezone": "UTC", "currency": "EUR", "week_start": 1 },
  "environment": { "key": "staging", "label": "Staging", "tone": "warn" },
  "impersonation": null, "session": { "expires_at": "…", "idle_expires_at": "…", "warn_seconds": 120 },
  "plugins": [{ "key": "billing", "version": "1.4.0", "capabilities": ["invoices"] }],
  "limits": { "max_page_size": 100, "upload_max_bytes": 10485760 },
  "server_time": "…", "build": "…", "degraded": [] }
```
Backend: `core/bootstrap.py` assembles it from `registry.bootstrap` contributors, each declared
`essential` or not. Values come from their owners — flags, localization and environment from
[`CONFIGURATION.md`](CONFIGURATION.md), nav from § 10.

**Enforced by.** Backend `test_bootstrap.py`: a superuser's `permissions` equals the full catalogue;
an owner-bypass principal's list equals what `has_perm` answers for every code (parametrised over the
catalogue — the parity test that would have caught the incident above); a raising decorative
contributor yields `degraded` and a 200; a raising essential one yields a 500.

**Configurable, not hard-coded.** Contributors are a registry; `SESSION_EXPIRY_WARN_SECONDS`
server-side; nothing in core names a plugin's section.

---

## 8. Session UX and the session marker cookie — **Tier 1 · Core**

### 8.1 The topology this assumes

**The browser talks to one origin.** `/api/*` is routed to Django by the reverse proxy (production)
or by a Next `rewrites()` entry (development; rewrites are resolved into the build's manifest, so
production routing belongs to the proxy — [`OPERATIONS.md`](OPERATIONS.md)). Everything below works
without it only if cookies are given a shared `Domain`, which widens them to every sibling host.

### 8.2 The marker cookie

**What.** A non-credential cookie, `dbx_session`, with `Path=/`, set and cleared by the backend in the
same responses that set and clear the refresh cookie.

**Why.** A real incident, measured: the edge route guard checked for the access cookie. The access
token lived an hour and the refresh cookie was path-scoped to the refresh endpoint, so after an hour a
**page** request carried neither — and the guard redirected to sign-in *before any JavaScript ran*,
so the client's transparent refresh never got its chance. Of 77 live sessions only 4 had ever
refreshed; everyone else was quietly signing in every hour. DjangoBaseX's cookie design
(`Path=/api/` access, `Path=/api/auth/refresh/` refresh) reproduces the precondition exactly: **neither
credential cookie is sent on a page navigation.**

**Rules.**
- `dbx_session=1; Path=/; Secure; HttpOnly; SameSite=Lax`, `__Host-` prefixed when no cookie domain is
  configured. Lifetime = the refresh cookie's. **It is a marker, not a credential** — no id, no
  signature. Forging it yields an empty shell whose every API call answers 401.
- `src/proxy.ts` decides: marker present → let the page render (the client refreshes on its first 401);
  marker absent → redirect to `/login?next=<safe path>`. **Proxy never reads `dbx_access` or
  `dbx_refresh`, and never calls the API per request.**
- `next` is accepted only as a same-origin relative path (`safeNext()`): no scheme, no `//`, no
  backslash. An open redirect on the login page is a phishing kit.
- Retired routes redirect in `proxy.ts` with a real 307; a server component's `redirect()` streams and
  is not reliable for this.

### 8.3 Expiry, re-auth and step-up

**Why.** Silent expiry loses unsaved work, and a hard redirect to `/login` on a 401 throws away a
half-filled form.

**Rules.**
- **`SessionGuard`** (in the shell) reads `session` from bootstrap. **Idle expiry:** it warns
  `warn_seconds` before, with "Stay signed in" (calls refresh). **Absolute expiry** cannot be extended —
  the warning says so and offers to re-authenticate in place.
- **A 401 after a failed refresh opens a re-auth modal over the current page.** React state — the
  form — survives. On success, queued GETs replay; **the failed mutation is not replayed** — the user
  presses Save again (§ 23). A hard redirect is used only when there is no page state (initial load).
- **The re-auth modal must re-authenticate the same user.** A different account signing in there runs
  the identity-change path (§ 8.4) and a full navigation.
- **`423` → step-up.** `useStepUp()` shows the confirm-password dialog
  (`POST /api/auth/password/confirm/`), then retries the refused request **once**, with the **same
  `Idempotency-Key`**. 423 guarantees the request was refused before it executed.
- **One-time tokens arrive in the URL fragment** (`/reset-password#token=…`, `/invite#token=…`):
  fragments are not sent to servers or into `Referer`. The page reads the value **once**, immediately
  scrubs the query and fragment with `history.replaceState` (`token`, `code`, `state`, `email`,
  `error`, `error_description`), and POSTs it in a body. Links issued with a query token are read as a
  fallback, then scrubbed.
- Token pages carry `robots: { index: false, follow: false }` and `Referrer-Policy: no-referrer`.

### 8.4 One identity-change cleanup path

**Why.** Real incidents: cached responses from the previous identity survived a sign-out and
sign-in in the same tab; stale tenant and project ids produced spurious 403s for the next person;
and a logout that only cleared client state left the server session alive.

**Rules.** `signOut()` in `src/core/lib/session/` is the **only** path, used by logout, re-auth as a
different user, impersonation start/stop and "session revoked elsewhere":
1. `POST /api/auth/logout/` — revoke the **server** session first, while it is still authenticated.
   Best effort, bounded by a short timeout; it never blocks the rest.
2. `queryClient.cancelQueries()` then `queryClient.clear()`.
3. Clear client context: every key registered through `registerClientStateKey()` (tenant selection,
   per-user UI state) — core and plugins register keys; nobody calls `localStorage.removeItem` by hand.
4. Broadcast `signed-out` on a `BroadcastChannel`, so other tabs run steps 2–3 too.
5. **Hard navigation** to `/login` — a fresh JavaScript heap is the only complete cache clear.

Switching tenant uses the same registry: clear the tenant-scoped keys **before** setting the new
tenant, so a stale "suspended" banner from the old tenant never renders over the new one.

### 8.5 Impersonation UI — **Tier 2 · Core**

The server side is deferred in [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) (`impersonator_id`). The
frontend contract, for when it lands:
- Bootstrap's `impersonation = {actor, subject, mode: "view" | "full", expires_at}`. Two modes behind
  **two permissions**; `view` is enforced **server-side** by rejecting unsafe methods, not by hiding
  buttons.
- A fixed banner in every tab: amber for view, red for full, a countdown from `server_time`, a warning
  in the last five minutes, auto-exit at zero.
- Starting and stopping run § 8.4 steps 2–5, and **back up then restore** the operator's own tenant
  selection. A real incident: the operator's tenant header leaked into impersonated calls and every one
  answered 403.
- A 401 with code `impersonation_expired` ends impersonation only and returns the operator to their
  own session — it is not a sign-out.
- With cookie auth the impersonation session is browser-wide, not tab-scoped; the banner therefore
  appears in every tab (via the broadcast channel), and that trade is stated rather than discovered.

**Enforced by (§ 8 as a whole).**
- Playwright `auth-flows` (§ 26): with the access TTL shortened in the test environment, wait past it,
  **navigate** to a protected page → still signed in (the marker regression test). Delete the marker →
  redirected. Reset link with a fragment token → token absent from `location.href` after load.
- `session.test.ts`: `signOut()` call order is asserted with spies; every registered key is cleared; the
  broadcast fires.
- Backend: `dbx_session` is set on login, refresh and invitation accept, and cleared on logout,
  revocation and reuse detection (one parametrised test per path).
- `safe-next.test.ts` with the classic open-redirect payloads.

**Configurable, not hard-coded.** Warning window and TTLs from the backend; the scrubbed parameter
list is one exported constant.

---

## 9. The permission provider — **Tier 1 · Core**

**What.** `PermissionProvider` exposes `can`, `canAny`, `canAll`, `status` and **`permissionsError`**,
fed by bootstrap. `<Can>` renders or denies.

**Why.** Two real incidents: on a failed permission fetch the provider fell back to a broad default set
and showed controls nobody held; and a tenant-scoped role that happened to be *named* "admin" was
treated as a platform administrator.

**Rules.**
- **Fail closed.** A fetch error yields an **empty** set and a non-null `permissionsError`; pages render
  a retry path, not broad controls. `permissionsError` is a **required** field of the context type, so a
  page cannot destructure the provider without seeing it exists.
- **A missing provider denies everything.** `usePermissions()` throws outside a provider;
  `useOptionalPermissions()` returns an all-deny stub, so a shared component rendered in another portal
  or a test never reveals admin UI by accident.
- **`can()` is typed.** `PermissionCode` is the union generated from the backend catalogue
  (`src/generated/permissions.ts`), so `can("users.user.delete")` is a compile error.
- **Global administration is separate from tenant roles.** `user.is_superuser` is a global claim and is
  already folded into the effective set (§ 7). A tenant role's name never escalates anything. The
  provider exposes **no `isAdmin` flag** — `is_superuser` may drive a badge in the shell, never a gate.
- **Refetch on tenant change** — roles are scope-specific.
- **`<Can perm fallback>`**: while loading, renders nothing inline (or a skeleton for a section); when
  denied, renders a **visible** "You don't have permission to view this section" card unless the caller
  supplies `fallback`. Denied must never look like empty or like loading.
- **Gate affordances by passing the callback.** Components render an action iff its handler is
  defined; the page passes `onDelete={can("users.users.delete") ? del : undefined}`. A component cannot
  show a button nobody authorised.
- **Affordance parity** ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 11): each module's `actions.ts`
  declares `{key, permission, endpoint}`; the gate uses exactly that permission — never a broader
  "can manage".
- **Hiding is a courtesy, not a control** ([`RBAC_DESIGN.md`](RBAC_DESIGN.md) § Frontend). Every check
  is re-made server-side.

**Django + Next shape.**
```tsx
type PermissionsCtx = { status: "loading" | "ready" | "error"; permissionsError: ApiError | null;
  can(c: PermissionCode): boolean; canAny(c: PermissionCode[]): boolean; canAll(c: PermissionCode[]): boolean };
<Can perm="billing.invoices.void"><VoidPanel /></Can>
```
`manage.py export_frontend_contracts` writes `src/generated/permissions.ts` (and enums, choices,
status metadata, error codes, the full nav manifest — § 10).

**Enforced by.**
- `permissions.test.tsx`: fetch failure → `can()` false for everything and `permissionsError` set;
  outside a provider → deny; tenant switch refetches.
- `tests/architecture/no-superuser-gating.test.ts`: `is_superuser` / `isSuperuser` referenced only in
  `src/core/shell/`.
- `tests/architecture/detail-pages-read-permissions-error.test.ts` (AST): every page that calls
  `usePermissions` also references `permissionsError`.
- **Affordance parity**, backend side: `test_affordance_parity.py` loads every module's exported
  `actions` manifest and asserts each `permission` equals the `required_permissions` of the route the
  `endpoint` resolves to (via `django.urls.resolve`).
- CI: `export_frontend_contracts` then `git diff --exit-code src/generated/`.

**Configurable, not hard-coded.** The catalogue is the backend's; the denied-card copy is i18n.

---

## 10. Server-built navigation that is also the route gate — **Tier 1 · Core**

**What.** The backend builds the navigation tree from `registry.navigation`, filtered by effective
permissions, flags and capabilities. The frontend renders it **and derives page access from it**.

**Why.** A real incident: a hard-coded client sidebar with its own `can()` calls became a second
source of authorization truth that drifted from the pages it linked. The fix — one manifest for both
sidebar and page gate — replaced per-page wrappers on 44 pages "so the sidebar and page access can
never disagree". Then a second incident: routes with no nav entry fell back to "any signed-in admin",
so pages reachable only by URL were ungated until someone happened to add a nav item.

**Rules.**
- `NavItem = {key, label (i18n key), href, icon (a name), permission (code | any-of list | null),
  flag?, capability?, requires_tenant?, portal, exact?, active_prefixes?, badge?, hidden?, public?,
  children[]}`. Parents with no surviving child are dropped; empty sections are dropped.
- **Icons are names, not markup.** The client owns the SVGs; a restyle must not be a backend deploy.
- **The route gate:** the portal layout flattens every `(href, permission)` pair — including
  `hidden: true` entries for URL-only pages (`/settings/danger-zone`) — sorts by href length and
  matches the pathname to the **deepest prefix**. No match → **denied** (default-deny). Lacking the
  permission → the denied card instead of `children`.
- **`public: true`** is the only way a page is reachable signed-out, and the public list is itself a
  registry, asserted in both directions ([`EXTENSIBILITY.md`](EXTENSIBILITY.md)).
- **`requires_tenant`** expresses what a permission cannot: a page that needs a tenant to resolve,
  where a superuser holds every permission and no tenant.
- The gate hook runs **before any early return** in the layout (a hooks-order crash was the real
  failure).
- **Per-role collapsible preferences:** `Role.nav_preferences` (`always_open | collapsible` per
  section key); the section catalogue is populated from registrations, so seeding, the roles screen and
  the renderer share one list.
- **Badges** register separately (`registry.nav_badges.register(key, provider, permission)`), are
  served by `GET /api/me/nav-badges/` (cached per user, polled), **each gated by its own permission**
  — a count is a disclosure — and a raising provider yields no badge, never a broken sidebar.
- **Collapsing the sidebar removes labels and nothing else** — every row keeps its height, so muscle
  memory survives; a collapsed parent opens a flyout on the opaque popover surface.
- **The command palette derives from the same filtered tree** plus `registry.palette_actions`
  (quick-create targets, plugin actions, each permission-gated). It opens on `/` or ⌘K only when focus
  is not in a text field. **Tier 2 · Core**.

**Django + Next shape.** `core/navigation.py` builds the tree; `GET /api/me/navigation/` is also
embedded in bootstrap. Frontend: `src/core/shell/nav/` (`useNav`, `useRouteGate`, `resolveRoute()` —
the one deepest-prefix function, shared by the gate and the test), `src/core/icons/registry.ts`.

**Enforced by.**
- `tests/architecture/route-manifest.test.ts` — walks `src/app/**/page.tsx` and every plugin manifest's
  `pages`, converts each file path to a route pattern (route groups stripped, `[id]` → a sample
  segment), and asserts **each resolves** via `resolveRoute()` against the exported full manifest
  (`src/generated/nav-manifest.json`). **Two-way:** every manifest `href` resolves to a real page (no
  dead links). A new page without an entry fails the build.
- `tests/architecture/icon-keys.test.ts` — every icon name in the manifest exists in the icon registry;
  and every named icon import from the icon package exists in the installed version (a removed icon
  imports as `undefined` and crashes only at render).
- Backend `test_navigation.py` — a user lacking a permission never receives the item; an item's
  permission exists in the catalogue ("every permission gates something" is checked the other way in
  [`API_PLATFORM.md`](API_PLATFORM.md)).

**Configurable, not hard-coded.** Nav is registry data; per-role preferences are rows;
`NAV_BADGE_CACHE_SECONDS` (90) server-side, `navBadges.pollMs` client-side.

---

## 11. The module UI contract — **Tier 1 · Core**

**What.** Every module is **Index / Form / Show**, built from shells. A module supplies columns,
fields and handlers; it never supplies layout.

**Why.** A real incident: unifying four copied modules into one shape found **seven live bugs**, none
visible without clicking to page 2 or selecting a row. Divergent copies hide their defects.

**Rules.**
- **Shells:** `ResourceIndex` (title row → toolbar → StatTiles? → DataTable → pager), `ResourceForm`
  (+ `FormSection`, `FormGrid`), `ResourceShow` (2:1 grid, sticky sidebar with `InfoCard`, `MetaCard`,
  `AuditCard`; `self-start` is load-bearing on the sidebar).
- **A missing shape is added to the shell, for every module** — never built locally.
- **One Form, two modes.** A record present = edit; the heading includes the record's name.
- **Create/edit/view open as modals from the index** (filters and scroll survive); main modules
  *also* keep deep-linkable `/new`, `/[id]`, `/[id]/edit` routes.
- **Fixed column order:** selection → identifier (sticky left) → status → data columns → updated-at
  (user timezone) → actions (sticky right, icon buttons with tooltip and `aria-label`). Sticky
  columns keep both the row's identity and its actions reachable at any width.
- **`sortKey` only where the API's ordering allow-list accepts it** — an arrow that does nothing is a
  lie on the screen.
- **Empty state distinguishes three cases:** nothing yet (with create CTA, if permitted); filters hid
  everything (with "Clear filters"); failed (`ListLoadError`, § 5).
- **Row count lives in the pager**, nowhere else.
- **`StatTiles`** is the only summary-tile component: clickable, applies its filter, counts come from
  the list pipeline's summary so tile and table agree; it must be a direct child of its grid.
- **Bulk results report what was skipped:** "7 archived, 2 skipped" with a details list of per-row
  reasons from the response's `skipped[] = {id, code, message}`.
- **Deep links land on the right row:** `?highlight=<id>` — the API returns the page containing that
  row under the current filters and sort; DataTable scrolls to and flashes it, then removes the param
  (replace) so a refresh does not re-flash. Hidden by filters → a toast offering "Clear filters".
- **Parity means the same vocabulary, not the same feature list.** An audit log has no actions column;
  cancel is not delete. **Every deviation from the contract carries a comment at the deviation:**
  `// ui-contract-deviation: <reason>`.
- **Portal-agnostic resource components** (§ 21): Show/Index components take a `scope` prop; portals
  compose them.

**Django + Next shape.**
```
src/plugins/billing/modules/invoices/
  Index.tsx  Form.tsx  Show.tsx       // compose shells only
  columns.tsx  fields.ts  actions.ts  // data: columns, field specs, {key, permission, endpoint}
  keys.ts  schema.ts                  // query keys, URL-state + form schemas
```
Every shell root renders `data-page="<plugin>.<resource>.<view>"` for e2e selectors (§ 26).

**Enforced by.** `tests/architecture/module-contract.test.ts`: every `Index.tsx` under a module renders
`ResourceIndex` or carries `ui-contract-deviation`; every `columns.tsx` puts identifier/status/actions
in the fixed positions; a page file over **400 lines** fails (two-way ratchet — a budget, not an
aesthetic).

**Configurable, not hard-coded.** Column visibility per user is a preference; nothing about a
module's shape is.

---

## 12. The DataTable standard — **Tier 1 · Core**

**What.** `src/core/components/data-table/` on **TanStack Table v8** (headless), server-driven, the
only list renderer.

**Why.** Every early module grows its own table with different pagination, URL behaviour and
selection semantics — and then its own bugs. A real incident: seventy list endpoints accepted a sort
parameter unguarded and fifty-two sortable headers did nothing.

**Rules.**
- **Server-side everything:** `manualPagination`, `manualSorting`, `manualFiltering`; the table
  renders what the API returned.
- **Column meta:** `sortKey?`, `hideBelow?: "sm" | "md" | "lg" | "xl"`, `sticky?: "left" | "right"`,
  `align`, `width`, `headerTooltip`.
- **The sort arrow is drawn from the ordering the API echoes back**, not from the URL input — an
  ignored sort must not draw an arrow.
- **Selection:** the checkbox is the only selection gesture; **shift-click selects the range** since
  the last click on the page; the header checkbox selects the page; a banner then offers **"Select all
  1,337 matching"**, which escalates to **query mode** — `{mode: "query", query, excludeIds}` — so the
  bulk endpoint re-runs the list's own pipeline instead of receiving a list of ids
  ([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md)). Two definitions of "the rows I see" drift, and
  the drift deletes the wrong rows.
- **Skeleton rows = page size**, so the layout does not jump when data arrives.
- **Sticky first and last columns** use `bg-inherit` and an inset shadow seam, so they match striped
  and hovered rows.
- **Accessible row labels:** `getRowLabel(row)` feeds `aria-label="Select {label}"` on the checkbox and
  "Edit {label}" on each action; a table of twenty checkboxes labelled "Select row" is unusable with a
  screen reader.
- **Filters:** the **page scope** control (e.g. which site or which tenant) sits in the header and
  scopes tiles, counts and table together; **list filters** sit in a **staged drawer** — changes stage
  and apply once — with a count on the Filter button and removable chips for active filters. Filter
  controls come from a backend **filter descriptor** (select, multiselect, date range, async select,
  boolean) where the API provides one.
- **Pager** top and bottom, truncated page list, rows-per-page up to the server max.
- **Layout:** the index is a `min-h-0` flex chain so **only the table scrolls**; headers stay put.
- **Inline editing** (`InlineEditableCell`): a single-field `PATCH` with `If-Match`; read-only without
  the update permission; revert on error; **master and reference data require an Old → New confirm**.
  **Tier 2 · Core**.
- **Development warning** when a column is `sortable` without a `sortKey`, naming the column.

**Django + Next shape.** `<DataTable columns rows selection pager sort onSortChange getRowLabel
fetching emptyState />`, with `DataTable.Skeleton`, `DataTable.BulkBar`, `DataTable.FilterDrawer`,
`DataTable.Pager` as parts.

**Enforced by.** `data-table.test.tsx` (shift-range; select-all escalates to query mode; filter change
clears selection; echoed ordering drives the arrow); `tests/architecture/sortable-has-key.test.ts`
(AST over every `columns.tsx`: `sortable` ⇒ `sortKey`, and `sortKey` ∈ the endpoint's ordering
allow-list exported by the backend — two-way ratchet); ESLint bans `<table>` outside
`src/core/components/data-table/`.

**Configurable, not hard-coded.** Page sizes from bootstrap `limits`; filter descriptors from the API;
density from the user preference (§ 16).

---

## 13. Mandatory primitives and the lint rules that make them mandatory — **Tier 1 · Core**

**What.** A short list of components every screen must use for its job, and lint rules that make the
alternative fail CI.

**Why.** A real audit: local status-badge switches disagreed with each other about what "suspended"
meant, and twenty-five hand-written currency formatters rounded differently. A half-used dialog hook
was worse — its `confirm()` returned a promise settled only by a `Dialog` component the caller also had
to render; one caller didn't, and a "Void" button silently did nothing, forever.

**The primitives.**

| Primitive | Rule |
|---|---|
| `StatusPill` | One `status → {tone, label, icon, transitional}` table. **The backend supplies it per choice** in the exported status metadata, so a plugin declares the tone of its own statuses. A decision like "suspended is warn, not error" is recorded once. `statusToneEmpty` (dashed, no hue) for not-set |
| `confirm()` + `ConfirmHost` | **Imperative**, backed by one root-mounted host: `if (await confirm({title, body, tone:"danger"})) …`. There is no hook to half-use |
| `ListLoadError` / `PanelError` | `role="status"` / `role="alert"`, "Couldn't load invoices", **"This is a display problem — nothing has changed"**, Retry, request id |
| `EmptyState` | Variants `none` / `filtered` (§ 11) |
| `SearchInput` | Owns debounce and minimum length (§ 6) |
| `DateInput` / `DateTimeInput` / `DateRangeInput` | **One** date control family, formatted from bootstrap localization |
| `Select` / `MultiSelect` / `AsyncSelect` | Custom, **searchable by default**; never a native `<select>` (styling, search and async loading are impossible there) |
| `Modal` | **One shape:** header → scrolling body → fixed footer with messages left, actions right; submit sits in the footer via `form="<id>"` |
| `FormField kind=…` | Screens declare a field's **kind**; a registry owns the control (§ 15) |
| `StatTile`, `Band`, `Meter` | The dashboard kit: domain-agnostic, colour as a token prop; each figure carries its state (`live / quiet / never / off` — [`OBSERVABILITY.md`](OBSERVABILITY.md)); each section is its own query/Suspense boundary with a skeleton, so one slow figure does not hold the page |
| `SafeLink`, `SafeHtml` | § 18 |
| `DateTime`, `Money`, `Bytes` | Render through § 14's formatters |
| Toasts | One global store (`toast()`), usable outside React |

**UI invariants (not components, still rules).** An error is shown **once**, on its field; the summary
counts, it does not repeat. A row's error is shown on that row. Required labels end with an asterisk
(and `sr-only` "required"). Toggles are always-labelled switches. **Every screen is verified at mobile,
tablet and desktop, with no horizontal page scroll — fix the cause, never `overflow-x: hidden`.** Text
sizes in `rem`, never `px`. `window`, `document` and storage are touched only in effects or through
SSR-safe helpers.

**Enforced by.** `eslint.config.mjs` (`no-restricted-syntax` / `no-restricted-imports`, each scoped to
allow only its home):
- JSX `<table>`, `<select>`, `dangerouslySetInnerHTML`
- a class string containing `fixed inset-0` (hand-rolled overlay)
- `window.confirm` / `window.alert` / `window.prompt`
- declaring a function or const named `/^format(Currency|Money|Amount|Price|Cost|Bytes|Size|FileSize|Date|DateTime|Time|Number|Percent)/`
  outside `src/core/lib/format/`
- calls to `toLocaleString`, `toLocaleDateString`, `toLocaleTimeString`, `new Intl.NumberFormat`,
  `new Intl.DateTimeFormat` outside `src/core/lib/format/`
- raw palette classes (`/\b(bg|text|border|ring|fill|stroke|from|to|via)-(white|black|(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3})\b/`)
  outside `src/core/styles/` and `src/core/lib/status-tone.ts`
- `localStorage` / `sessionStorage` outside `src/core/lib/storage/`

Plus `tests/architecture/confirm-host.test.tsx` (exactly one `ConfirmHost` in the root providers) and
a positive-control fixture per rule that must make ESLint fail (§ 26).

**Configurable, not hard-coded.** Status metadata is backend data; tones are tokens.

---

## 14. Formatters in one home — **Tier 1 · Core**

**What.** `src/core/lib/format/` is the only place a number, amount, size or date becomes text.

**Why.** Formatting spread across components hard-codes a locale and a currency into hundreds of call
sites, and a product for another market becomes a sweep. And a real trap: a date-only value parsed
with `new Date("2026-03-01")` is midnight **UTC**, which renders as 28 February west of Greenwich.

**Rules.**
- **Locale, timezone and currency come from bootstrap `localization`** (user preference → tenant
  default → platform default, resolved server-side — [`CONFIGURATION.md`](CONFIGURATION.md)). No
  formatter has a literal locale or currency default.
- **Date vs datetime are different types.** `formatDate("YYYY-MM-DD")` treats the value as a calendar
  date and never passes it through the timezone; `formatDateTime(iso)` converts UTC ISO-8601 to the
  user's zone. The API always sends datetimes as ISO-8601 UTC and dates as `YYYY-MM-DD`.
- **Always pass `timeZone` explicitly.** Formatting with the runtime's default zone makes server and
  browser disagree and produces hydration mismatches.
- **Money** arrives as a decimal string plus a currency code ([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md));
  it is never parsed into a float for arithmetic. An unknown or missing currency renders the code and
  the number and warns in development — it never throws `RangeError` and never silently assumes one.
- **Bytes:** one base, configured (`format.bytesBase: 1024 | 1000`), with matching unit labels.
- **Null/empty** renders one em dash, from one constant.
- `<DateTime value>` renders `<time dateTime>` with a tooltip showing UTC and the zone name.

**Enforced by.** The ESLint bans in § 13; `format.test.ts` run under two timezones (§ 26): date-only
values never shift; unknown currency does not throw.

**Configurable, not hard-coded.** `format.bytesBase`, `format.emptyValue`; everything locale-shaped is
bootstrap data.

---

## 15. Forms — **Tier 1 · Core**

**What.** **react-hook-form + zod** (via `@hookform/resolvers`), wrapped by `ResourceForm` and
`<FormField kind>`.

**Why one stack, and this one.** Without a standard, every page re-implements dirty state,
disabled-while-submitting and field errors, and the component guide ends up documenting a library that
is not installed. react-hook-form is uncontrolled (fast on long forms) and its `values` +
`resetOptions: { keepDirtyValues: true }` is exactly "untouched fields follow the server, touched
fields hold their own"; zod gives one schema for types and validation, and is the target of OpenAPI
generators.

**Rules.**
- **Types are always generated** from OpenAPI; **zod schemas are generated where practical** and
  extended with refinements for UX. The server remains the validator — a client schema is a courtesy.
- **`applyServerErrors(form, err)`** maps `validation` errors' `fields[].path` onto form paths
  (`lines.2.quantity` → `lines.2.quantity`). A path the form does not know becomes a **form-level**
  error — never dropped. Focus moves to the first errored field.
- **An error is shown once, on its field.** The summary shows the count and links to the fields; the
  footer holds non-field errors.
- **Dirty-gated, scoped saves.** Save is disabled until the form is dirty; settings pages save **per
  section**, with a self-dismissing success message. Leaving a dirty form asks first.
- **`PATCH` sends only dirty fields**, so two people editing different fields do not clobber each other;
  edits send `If-Match` and a `412` becomes a `conflict` (§ 3).
- **Create sends an `Idempotency-Key`**, generated once per form instance, constant across retries of
  that submission, renewed only after success or reset ([`API_PLATFORM.md`](API_PLATFORM.md)).
- **Submit is disabled while submitting.** Double-submit is the idempotency key's job to survive, not
  the user's job to avoid.
- **Required asterisk from the schema**, not hand-placed.
- **`<FormField kind="date" name="due_on" />`** — the field-kind registry. Core kinds: `text`,
  `textarea`, `number`, `money`, `email`, `password`, `select`, `multiselect`, `async-select`,
  `lookup` (admin-editable vocabularies — [`CONFIGURATION.md`](CONFIGURATION.md)), `date`, `datetime`,
  `daterange`, `switch`, `checkbox`, `radio`, `file`, `rich-text`. Plugins register more through their
  manifest. Changing how every date field works is then one file.
- **No Server Actions for data mutations.** Mutations go to DRF through the transport, so auth, CSRF,
  errors and idempotency have one path (and § 23's "never re-send").

**Django + Next shape.**
```tsx
const form = useResourceForm({ schema: invoiceSchema, values: invoice.data, idempotent: !invoice.data });
const save = useApiMutation({ mutationFn: invoicesApi.save, invalidates: [invoiceKeys.root] });
<ResourceForm form={form} onSubmit={v => save.mutateAsync(v).catch(e => applyServerErrors(form, e))}>
  <FormSection title={t("billing.invoice.details")}>
    <FormField kind="lookup" name="terms" lookup="payment_terms" />
    <FormField kind="date" name="due_on" />
  </FormSection>
</ResourceForm>
```

**Enforced by.** `apply-server-errors.test.ts` (nested and list paths; unknown path → form-level);
`resource-form.test.tsx` (save disabled until dirty; only dirty fields sent; idempotency key stable
across a retried submission); ESLint bans importing `react-hook-form` outside
`src/core/components/form/`.

**Configurable, not hard-coded.** Field kinds are a registry; the zod generator is a pending decision.

---

## 16. Design tokens — **Tier 1 · Core**

**What.** Semantic CSS variables in `src/core/styles/tokens.css`, mapped into Tailwind 4 with
`@theme inline`. Components use `bg-primary text-primary-foreground`, never a palette colour.

**Why.** Dark mode added late makes every hard-coded colour a bug. A real incident: a brand colour was
hard-coded in **242 places across 37 files**, and a hex grep undercounted it because half the uses were
palette utilities. Another: white text on a tenant's pale brand colour, measured at about 1.4:1.

**Rules.**
- **Families:** `background`, `foreground`, `card`, `popover`, `primary`, `secondary`, `muted`,
  `accent`, `destructive`, `border`, `input`, `ring`, `sidebar-*`, `chart-1…n`, and status families
  `ok | warn | err | info | neutral`, each with `dot`, `text`, `tint`, **`solid` and
  `solid-foreground`**.
- **Every fill token has a `-foreground` pair**, and a foreground token is never used as a fill.
- **Light and dark are both first-class.** Light in `:root`, dark in `[data-theme="dark"]`;
  `@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));` aligns Tailwind's `dark:`
  with the attribute. `system` is resolved by a tiny nonce'd script before paint; the choice is stored
  in a readable `dbx_theme` cookie so SSR renders the right attribute and nothing flashes.
- **Values are OKLCH.** Tenant-overridable slots are an **explicit list** (§ 17).
- **On tenant-overridable surfaces palette colours are banned outright** — `bg-primary text-white` is
  wrong because the tenant changes one and not the other.
- **Status tone recipes are spelled as literal class strings** (`"bg-ok-tint text-ok-text ring-ok-dot/30"`).
  **Tailwind emits only class names it finds whole in source**; `bg-${tone}-tint` compiles to nothing
  and renders a transparent chip with no error.
- **Per-user accent and density** are `data-accent` / `data-density` on `<html>`, overriding tokens
  (`--primary`, `--control-h`, `--row-h`). Appearance preferences are excluded from audit.
- **Page-scoped themes** set both token tiers (`--card` and `--color-card`) on the page container,
  never in the global sheet.
- **Migrating hard-coded colours:** move every site to a token **while the token still holds the old
  colour** (no visual change, grep-verifiable), then change values in one revertible commit; keep the
  grep as a regression guard.

**Django + Next shape.**
```css
@theme inline {
  --color-primary: var(--primary);   --color-primary-foreground: var(--primary-foreground);
  --color-ok-solid: var(--ok-solid); --color-ok-solid-foreground: var(--ok-solid-foreground);
}
:root { --primary: oklch(0.55 0.18 264); --primary-foreground: oklch(0.99 0 0); /* … */ }
[data-theme="dark"] { --primary: oklch(0.72 0.15 264); --primary-foreground: oklch(0.18 0 0); }
```

**Enforced by.**
- `tokens.test.ts` parses `tokens.css`: every family is declared in `@theme`, `:root` **and** the dark
  block (an undeclared variable makes Tailwind emit no class and the element renders unstyled); every
  fill has its `-foreground`.
- `tests/architecture/no-raw-colour-on-tokens.test.ts`: no class string contains `bg-primary` with
  `text-white`/`text-black`; no template literal inside a `className` interpolates a tone.
- Playwright contrast audit in both themes (§ 26).

**Configurable, not hard-coded.** Tokens are the configuration surface; accents and densities are a
curated list with matching CSS blocks.

---

## 17. Runtime branding and white-label rendering — **Tier 2 · Core**

**What.** Rendering the identity [`CONFIGURATION.md`](CONFIGURATION.md) stores (and, for per-tenant
hosts, what the white-label module in [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) stores): name,
short name, monogram, logos, favicon, colours, support and legal links.

**Why.** Real incidents: the platform logo and title flashed before the tenant's on every load; the
title reverted to the platform's after client navigation; a saved brand looked broken for five minutes
because the server cache held the old one; and — the security one — an unauthenticated,
tenant-controlled colour value like `red;background:url(https://…)` was one careless `var()` away from
exfiltrating data.

**Rules.**
- **Public identity endpoint** `GET /api/public/identity/`, resolved from the request host by the
  backend.
- **SSR-seeded so the first paint is branded.** The root layout calls `getIdentity()` (`server-only`,
  React `cache()` per request, tagged fetch, 2.5 s timeout, `redirect: "error"`, falls back to the
  platform identity on any failure — branding never blocks a render). It feeds `generateMetadata`
  (title template, icons) and writes the colour variables into the `<html style>` attribute, and seeds
  the client cache.
- **Title re-application:** the App Router re-asserts static metadata after navigation, so a client
  `TitleSync` patches `document.title` on pathname change instead of making every page dynamic just to
  compute a title.
- **Favicon swap** remembers the original and restores it when the host flips back; the provider
  undoes only what it applied.
- **Colours are stored as numbers, not CSS.** The backend stores `{l, c, h}` channels, validated by
  type and range; the frontend composes `oklch(l c h)` from **re-validated** numbers
  (`/^\d+(\.\d+)?$/`, ranges checked). A string never reaches a CSS value, so injection is impossible
  by construction rather than by regex. Anything that fails validation falls back to the stylesheet
  default for that slot.
- **Derived tokens come only from validated input** — link, nav-active, tints and every
  `-foreground` are derived on the backend by the contrast solver and sent as numbers.
- **WCAG AA contrast solver** (backend, `core/theme.py`): for a brand colour it adjusts lightness until
  **both** axes pass ≥ 4.5:1 — foreground on the fill, and the fill against the card — in light and
  dark. If it cannot within bounds it **refuses** with a `validation` error carrying the measured ratios
  and a passing suggestion. Every theme preset passes both axes in a parametrised test.
- **Save shows immediately:** after saving, the backend calls the Next route handler
  `POST /fe/revalidate/` (shared secret header, constant-time comparison), which calls
  `revalidateTag("identity:<host>", { expire: 0 })` — immediate, because the person who just saved is
  looking. A failure of that call never fails the save; the fetch's TTL bounds the staleness.
- **Host classification is exact.** Lowercase, strip the port and a trailing dot, compare for
  equality against the known-host table — **never `includes()`**, never an `endsWith()` without a dot
  boundary. A real incident: `includes()` let `not-workspace.<domain>.attacker.example` route as a
  workspace host.
- **Host-scoped public surfaces:** help centre, sitemap, `robots.txt` and similar answer 404 on
  white-label hosts unless the tenant enables them — otherwise the same content is indexed under every
  customer's domain.
- **Cookies on white-label hosts are per host** — no wildcard `Domain` — which is one more reason the
  API base is relative (§ 2).
- The web-app manifest name and icons come from identity and are served `no-cache`.

**Enforced by.** `identity.test.ts` (a string colour, an out-of-range channel and a CSS payload all fall
back; no derived token is computed from unvalidated input); `title-sync.test.tsx`; backend
`test_theme_presets.py` and `test_contrast_solver.py` (refusal carries ratios and a suggestion);
`host-match.test.ts` with suffix-smuggling cases.

**Configurable, not hard-coded.** The platform identity is a database row with env as prefill
([`CONFIGURATION.md`](CONFIGURATION.md)); `IDENTITY_CACHE_SECONDS` (300); the overridable slot list is
one exported constant shared by the solver's tests.

---

## 18. Frontend security — **Tier 1 · Core**

**What.** A per-request CSP, static security headers, the only allowed link and HTML sinks, and an SSRF
rule for server-side fetches. [`SECURITY.md`](SECURITY.md) owns the backend half.

**Why.** The CSP has to live in the Next layer: only that layer can mint a per-request nonce, and
Next needs the nonce to tag its own scripts. A real incident: the production reverse-proxy config that
was supposed to carry security headers was not in version control at all.

**Rules — CSP.**
- `src/proxy.ts` generates a nonce (`base64(randomUUID())`) per request, sets the **request**
  `Content-Security-Policy` header and `x-nonce` (Next reads the request header to auto-nonce its
  scripts), and sets the **response** header as `Content-Security-Policy-Report-Only` or
  `Content-Security-Policy` according to **`CSP_MODE=off|report_only|enforce`, read from
  `process.env` at request time** — flipping enforcement is a restart, never a rebuild, and the rollout
  is Report-Only first.
- Policy: `default-src 'self'`; `script-src 'self' 'nonce-…' 'strict-dynamic'` (+ `'unsafe-eval'` in
  development only, which React needs); `style-src 'self' 'unsafe-inline'` (a style nonce disables
  `unsafe-inline` and breaks third-party injected styles; style injection is the lower risk);
  `img-src 'self' data: blob:` + storage origins; `connect-src 'self'` + error-tracker origin;
  `object-src 'none'`; `base-uri 'self'`; `form-action 'self'`; `frame-ancestors 'none'`;
  `upgrade-insecure-requests` in production; `report-to` → the backend's rate-limited report endpoint.
- **Origins are data:** `CSP_EXTRA_ORIGINS` (runtime env) plus each plugin manifest's `csp` block
  (reviewed code, merged into the generated manifest). No origin is a literal in `proxy.ts`.
- The matcher excludes `_next/static`, `_next/image`, the favicon, `/api/` and prefetch requests.
- **A nonce requires dynamic rendering.** The root layout reads `headers()`, so every HTML route is
  dynamic; this is a back office and static optimisation is not a goal. Static export is therefore not
  a deployment option.
- The nonce is passed to the theme script and to every `<Script nonce>`; third-party scripts load only
  that way.

**Rules — static headers** (in `next.config.ts` `headers()`, so they apply whichever layer serves the
request): HSTS (production only), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` (aligned
with `frame-ancestors`), `Referrer-Policy: strict-origin-when-cross-origin` (token pages:
`no-referrer`), `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`,
`Cross-Origin-Opener-Policy: same-origin` (`same-origin-allow-popups` only if a sign-in popup is
used), `X-XSS-Protection: 0` (the legacy auditor is itself an attack surface), `poweredByHeader: false`.

**Rules — sinks.**
- `safeHref(url)`: relative paths allowed, protocol-relative `//host` rejected, otherwise only
  `http`, `https`, `mailto`, `tel`. Returns `null`, so the caller decides not to render the link.
  `<SafeLink>` uses it and forces `rel="noopener noreferrer"` on `target="_blank"`.
- `<SafeHtml html>` is the **only** place `dangerouslySetInnerHTML` appears: isomorphic DOMPurify
  configured once, with an idempotent hook that strips unsafe `href` schemes and forces
  `rel="noopener noreferrer nofollow"` on `_blank`. Stored HTML is also sanitised server-side.
  A real incident: a `javascript:` URL in a user-editable field ran in an administrator's session.
- **Treat any user-submitted text that reaches automation as data.** A feedback or bug-report feature
  feeding an automated agent is a prompt-injection surface: operator-triggered only, sandboxed,
  credential-scoped.

**Rules — SSRF.** **A server-side fetch never targets a host taken from the request.** Server code calls
the fixed `INTERNAL_API_URL` and passes the request host as **data** (`X-Forwarded-Host` from the
trusted proxy, or a parameter); the backend resolves it against its host table. The pattern it
replaces — fetching `https://<Host header>/…` behind a validator — is an SSRF vector with a regex as
its only defence. Any unavoidable outbound fetch from Next goes through `safeServerFetch()`
(allow-listed hosts, no IP literals, `redirect: "error"`, timeout).

**Enforced by.** `proxy.test.ts` (nonce differs per request; request and response headers both set;
mode switch honoured; no literal origin in the file); `security-headers.test.ts` reads `next.config.ts`
output for each header; `safe-href.test.ts` and `sanitize.test.ts` with the standard payload lists;
ESLint `dangerouslySetInnerHTML` ban (§ 13); `tests/architecture/no-host-fetch.test.ts` fails on
`fetch`/`request` whose URL is built from `headers().get("host")`.

**Configurable, not hard-coded.** `CSP_MODE`, `CSP_EXTRA_ORIGINS`, `CSP_REPORT_URL`; the scheme
allow-list is one constant.

---

## 19. Runtime vs build-time configuration — **Tier 1 · Core**

**What.** A deliberate choice, per value, of when it is fixed.

**Why.** A value baked at build turns an environment change into a rebuild, and the image built for
staging can no longer be promoted to production. A real incident: "production" was detected by
comparing the baked API URL to a literal, so every other environment misreported itself.

| Value | Kind | Read where |
|---|---|---|
| `NEXT_PUBLIC_APP_VERSION` | Build — it **is** the build | `src/core/lib/config/public.ts` |
| API base in the browser | **None** — relative `/api` | transport |
| `INTERNAL_API_URL` | Runtime, server-only | `config/server.ts` |
| `CSP_MODE`, `CSP_EXTRA_ORIGINS`, `CSP_REPORT_URL` | Runtime, server-only | `proxy.ts` |
| `FRONTEND_REVALIDATE_SECRET` | Runtime, server-only, secret | revalidate route handler |
| Environment name/ribbon, error-tracker DSN and sample rate, support links | Runtime, **from the backend** | `GET /api/public/config/` and bootstrap |
| Feature flags, capabilities, locale, currency, timezone | Runtime, backend data | bootstrap |

**Rules.**
- `NEXT_PUBLIC_*` only for truly public, build-stable values — in practice, the build id.
- `process.env.NEXT_PUBLIC_*` is read only in `config/public.ts`; server env only in `config/server.ts`
  (`import "server-only"`), validated with zod at startup — a missing required value refuses to start
  rather than rendering a broken shell ([`CONFIGURATION.md`](CONFIGURATION.md) owns the refusal
  philosophy).
- The environment is **never inferred** from a hostname, port or URL — it comes from the backend's
  `APP_ENV` via config; an unknown value renders the loudest ribbon.
- Every new key goes into `frontend/.env.example` in the same change ([`NEXTJS_STANDARDS.md`](NEXTJS_STANDARDS.md) § 6).

**Enforced by.** ESLint bans `process.env` outside `src/core/lib/config/` and `src/proxy.ts`;
`config.test.ts` (missing required key throws with the key name, not the value).

---

## 20. Error surfaces — **Tier 1 · Core**

**What.** Layered boundaries, each with a job, and copy that reassures.

**Why.** A blank white screen on a render error loses the sidebar, the user's orientation and any way
to report it; a raw digest with no request id gives support nothing to correlate.

**Rules.**
- `app/global-error.tsx` renders its own `<html>`/`<body>` with **inline styles** (global CSS is not
  included) and **imports nothing that needs a provider** — no theme, no query client, no intl. It
  shows the digest and a reload button.
- **A segment `error.tsx` per portal** keeps the shell alive: `ErrorState` shows the Next `digest`,
  the **last backend `request_id`** from the transport store, a copy button, and the message only in
  development. It offers `retry()` (re-fetch and re-render — verified in 16.3.4), not just `reset()`.
- `not-found.tsx` per portal. `forbidden()` / `unauthorized()` are experimental and not used; denial
  is the `<Can>` card (§ 9).
- **Skeleton-shaped `loading.tsx`** per segment — the shape of the page, not a spinner.
- A root `ErrorBoundary` reports client render errors with the component stack to the error tracker
  through the one scrubber ([`OBSERVABILITY.md`](OBSERVABILITY.md)).
- **Failure copy reassures:** "This is a display problem — nothing has changed." A failed fetch on a
  billing page must not read as a failed payment.
- **Trap:** a folder whose name starts with `_` is private and not routable in the App Router — a
  verification route once answered 404 for that reason alone.

**Enforced by.** `global-error.test.tsx` (renders with **no** providers mounted);
`error-state.test.tsx` (digest and request id both shown; message hidden in production mode);
`tests/architecture/global-error-imports.test.ts` (its import list is an allow-list).

---

## 21. Portals as sibling layouts — **Tier 2 · Core**

**What.** When a product has more than one audience (staff back office, customer portal, partner
portal), each is a sibling route group with its own layout, nav sections, provider scope and
`error.tsx`, composed from **portal-agnostic resource components**.

**Why.** A real incident: detail pages were cloned per portal (one of them grew to 3,600 lines); a
"force stop" fix shipped to one portal's copy only, and the other two kept the bug.

**Rules.**
- `app/(staff)/…`, `app/(customer)/…`, `app/(partner)/…`; nav items carry `portal`.
- Resource components take a **`scope` prop** that selects the API namespace and the permission set;
  portal pages only compose. **Never clone a detail page.**
- A portal that acts on its own tenant while a user browses others **pins** its tenant in module
  memory for its own requests, so switching the browsing context cannot corrupt it.
- The page-size budget (§ 11) applies — it is what makes cloning uncomfortable.

**Enforced by.** `module-contract.test.ts` (§ 11); `tests/architecture/no-cross-portal-imports.test.ts`
(portal A's page does not import portal B's page — shared code lives in the resource component).

---

## 22. Internationalisation — **Tier 1 · Core**

**What.** **next-intl**, with message catalogues per plugin from the start, even though only one locale
ships.

**Why.** Inline English is free to write and expensive to extract; the sweep happens exactly when a
product has a customer waiting. A locale plumbed from day one costs a function call per string. (This
is plumbing, not shipping translations — see ⚠️ C10.)

**Rules.**
- **No locale segment in the authenticated app's URL**; the locale comes from bootstrap (user → tenant
  → platform). Public pages may add routing later.
- Catalogues: `src/core/messages/<locale>.json` and `src/plugins/<name>/messages/<locale>.json`,
  namespaced by plugin key, merged through the generated manifest (§ 25) and loaded lazily per
  namespace.
- **ICU messages**; no string concatenation, no manual pluralisation.
- Error copy: `errors.<code>` keys generated from the backend catalogue (§ 3).
- Numbers and dates go through § 14, which uses `Intl` with the bootstrap locale.
- **Logical CSS properties** (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`) instead of left/right, so a
  right-to-left locale is a catalogue, not a rewrite.

**Enforced by.** `messages.test.ts` — **two-way:** every key referenced in code exists in `en`, and
every `en` key is referenced (orphans fail); every plugin's keys are under its namespace. ESLint
`react/jsx-no-literals` (with an allow-list for punctuation) in `src/app/**` and module components.

**Configurable, not hard-coded.** Supported locales and the default are backend data
([`CONFIGURATION.md`](CONFIGURATION.md)).

---

## 23. Offline policy and cache headers — **Tier 2 · Core**

**What.** What happens when the network fails, and what may be cached where.

**Why.** Real incidents: offline clicks did nothing and gave no feedback; and after a deploy, browsers
heuristically reused the old HTML document until a hard reload, which looked random because only some
pages set cache headers.

**Rules — offline.**
- **Retry a GET once**, when connectivity returns; show a connectivity bar meanwhile.
- **Never re-send a mutation.** Tell the user nothing was saved, keep their input on screen, and let
  them retry. Three mechanisms can violate this and all three are closed:
  1. the transport never replays a failed unsafe method (except § 8.3's step-up, which the server
     refused before executing);
  2. **TanStack Query pauses and later resumes mutations when offline** under its default network
     mode — core sets mutations to `networkMode: "always"` so they fail immediately instead;
  3. Next's `experimental.useOffline` **retries Server Actions** after reconnecting — it stays off, and
     Server Actions never mutate data (§ 15).
- **The service worker, if enabled, precaches exactly one document** (`/offline.html`, standalone, no
  external assets), serves it only when a navigation fails, never caches app HTML, RSC payloads or API
  responses, and never handles non-GET requests. A cache-everything worker reinstates the
  stale-after-deploy bug permanently.

**Rules — cache headers.**
- Authenticated HTML and RSC payloads: `Cache-Control: private, no-store`. Authenticated JSON: `no-store`
  ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 6.4).
- `/_next/static/*` stays **immutable** (hashed names). Verify both behind the reverse proxy — a proxy
  that adds caching to HTML undoes this silently.
- **Deploy skew:** bootstrap's `build` differs from the bundle's → "A new version is available — reload"
  banner. A chunk-load failure after a deploy triggers **one** automatic hard reload, guarded by a
  `sessionStorage` flag so it cannot loop.

**Enforced by.** `offline.test.ts` (a mutation offline rejects immediately and is not re-sent on
`online`; a GET is retried once); `query-client.test.ts` asserts the mutation `networkMode`;
Playwright asserts response headers for an authenticated page and a static chunk; a guard test asserts
`experimental.useOffline` is not set in `next.config.ts`.

---

## 24. Frontend contracts generated from the backend — **Tier 1 · Core**

**What.** Every constant both halves must agree on is **exported by the backend and imported by the
frontend**, never re-declared.

**Why.** A real incident: five backend call sites and the frontend each held a table of hours per
billing period, one said 720 and one 730, and quotes disagreed with invoices. Another: a hand-typed
client called endpoints that did not exist and sent query parameters the backend ignored — it
typechecked against yesterday's contract.

**Rules.** `manage.py export_frontend_contracts` writes `src/generated/`: OpenAPI types, permission
codes, enums and choices, status metadata (§ 13), the error-code catalogue, the full nav manifest,
list ordering allow-lists, public-route list. **Nothing in `src/generated/` is hand-edited.** A parity
check that **skips** when the other half is absent is a check that never runs — generation runs in CI
on the full checkout. [`API_PLATFORM.md`](API_PLATFORM.md) owns schema quality.

**Enforced by.** CI step: run the export, then `git diff --exit-code src/generated/`. Backend
`test_contracts_export.py` exports into a temp dir and diffs against the committed files.

---

## 25. Plugin frontend packages via a generated manifest — **Tier 2 · Core**

**What.** The frontend half of a plugin ([`CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md)
§ 5), mounted through one generated file and one catch-all route.

**Why.** Next has no plugin system. Hand-editing a core registry per plugin is exactly the "core knows
its plugins" coupling the architecture exists to remove.

**Rules.**
- A plugin's `frontend/index.ts` default-exports `definePlugin({...})`: `key`, `pages[]`
  (`{path, component: () => import(…), permission | public, title}`), `icons`, `fieldKinds`,
  `providers`, `messages`, `slots` ([`EXTENSIBILITY.md`](EXTENSIBILITY.md) owns slot kinds),
  `paletteActions`, `csp`.
- **Navigation is not in the frontend manifest** — it is registered on the backend (§ 10). The
  frontend declares pages; the backend declares who may reach them.
- `npm run gen:plugins` (run by `predev` and `prebuild`) writes `src/plugins/registry.generated.ts` with
  **static** `import()` specifiers (the bundler needs them literally). The file is committed and checked
  for drift, so a stale registry fails CI instead of failing at runtime.
- The catch-all `app/(plugins)/[plugin]/[[...slug]]/page.tsx` resolves the plugin page by pattern,
  calls `notFound()` for no match, and uses the page `title` in `generateMetadata`.
- **A plugin imports only `@/core/sdk`** (the versioned facade) and itself — never another plugin, never
  `src/project/`, never deep core internals.
- Plugin query-key roots, message namespaces, icon names and field kinds are all **prefixed with the
  plugin key**.

**Enforced by.** ESLint `no-restricted-imports` per plugin directory; `tests/architecture/plugin-manifest.test.ts`
(every plugin page is covered by the route-manifest test of § 10; every prefixed name carries the
plugin key; the generated registry equals a fresh generation).

---

## 26. Frontend tests — **Process**

**What.** The runner, the guard tests that encode this file, and the browser sweeps.
[`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) owns general practice and the ratchet helper.

**Rules.**
- **Vitest, non-watch by default:** `"test": "vitest run"`, `"test:watch": "vitest"`. Watch mode as the
  default hangs agents and CI.
- **Timezone pinned** (`TZ=UTC`) in the config, **plus** one CI job under a zone with a non-whole-hour
  offset (e.g. `America/St_Johns`) — date bugs hide in UTC.
- jsdom + Testing Library; `pool: "forks"`, `isolate: true`; a test `QueryClient` with `retry: false`.
- **Mock at the network, not the module:** MSW handlers, so the transport's real logic (refresh, error
  decoding, headers) runs in every component test.
- **Tests are typechecked** (`tsconfig.test.json` in the gate) — excluding them from `tsc` lets mocks
  drift from real types.
- **Source-walking guard tests** in `frontend/tests/architecture/` — each file header states the bug it
  prevents, its blind spots and "do not add an exception to silence this". Each uses a **two-way
  ratchet** allow-list and ships a **positive-control fixture** that must make it fail. The set:
  no-effect-fetch, no-false-empty, route-manifest (two-way), icon-keys, query-keys, module-contract,
  sortable-has-key, provider-order, confirm-host, no-superuser-gating,
  detail-pages-read-permissions-error, no-raw-colour-on-tokens, global-error-imports, no-host-fetch,
  plugin-manifest, messages (two-way), tokens.
- **"The linter actually runs":** `tests/lint-smoke.test.ts` runs ESLint on a fixture containing one
  violation per rule and asserts each is reported. A dependency bump that breaks the ESLint config then
  fails loudly instead of silently disabling every rule.
- **Playwright projects by intent:** `setup` (signs in once per seeded role, writes `storageState`);
  `features` (parallel); `workflows` (serial, full lifecycles); **`auth-flows` (unauthenticated —
  login, reset via fragment token, invitation, MFA gate, and the marker-cookie refresh of § 8)**;
  **`mobile-sweep`** (every route at 390 px; fails when the document is wider than the viewport and
  names the widest element); **`a11y-sweep`** (axe on every route, both themes); **contrast audit**
  (computed WCAG ratio of every text node against its effective background, both themes).
- **Sweep route lists are derived from the exported nav manifest**, with seeded ids for dynamic
  segments — never a hand-kept list. A real incident: four screens missing from a hand-kept list had
  never been visited, and one hid a 500 behind an empty state.
- **Assert a page-specific selector** (`[data-page="users.index"]`), not a word that also appears in
  the error page. And look at the screenshot: a check once passed on a page whose whole point was a
  block that never rendered.
- Traces and video on first retry, screenshots on failure; the stack runs seeded (`seed_demo`) with the
  outbound guard on ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).
- Regression tests are named for the defect they pin.

**Enforced by.** The gate gains `npm run test` and `npm run typecheck` (closing `TECH_DEBT` **DB-2**);
the Playwright sweeps run in CI on the built app.

---

## 27. ⚠️ Conflicts with existing docs

These docs were not edited. Each row is a fix for the owner to apply.

| # | Where | What it says | Why it breaks | Fix |
|---|---|---|---|---|
| C1 | `AUTH_BLUEPRINT.md` § 6.1 (token table) | `dbx_access` `Path=/api/`, `dbx_refresh` `Path=/api/auth/refresh/`, and nothing else | **Neither cookie is sent on a page navigation**, so any route guard in `proxy.ts` sees every signed-in user as signed out once the access token has expired, before the client can refresh | Add the `dbx_session` marker cookie (§ 8.2) to the token table: `Path=/`, `HttpOnly`, `Secure`, `SameSite=Lax`, no content, lifetime of the refresh cookie, set/cleared with it |
| C2 | `AUTH_BLUEPRINT.md` § 6.1 "Next.js rule"; `BUILD_ORDER.md` 1.1; `NEXTJS_STANDARDS.md` § 3 | A server component needing authenticated data "has to read the cookie via `cookies()` and forward it" | With `Path=/api/` the access cookie **never reaches** a Next page request, so there is nothing to forward — the stated escape hatch cannot work with the stated cookie path | State it without the escape hatch: **authenticated data is fetched client-side; server components fetch public data only** (§ 4). If a server-side authenticated fetch is ever required, that is an ADR that changes the cookie path |
| C3 | `AUTH_BLUEPRINT.md` § 17.5 | Apply `__Host-` to the access and CSRF cookies | `__Host-` **requires `Path=/`**; the access cookie is `Path=/api/`. The browser rejects the `Set-Cookie` and sign-in silently fails | `__Secure-` for the path-scoped cookies (access, refresh); `__Host-` only for `Path=/` cookies (CSRF, marker) |
| C4 | `AUTH_BLUEPRINT.md` § 11 | "on 401: attempt ONE refresh, replay the request, then redirect to /login" | A redirect discards unsaved form state | After a failed refresh, open the re-auth modal over the page (§ 8.3); redirect only on initial load. Replay GETs, never the failed mutation |
| C5 | `AUTH_BLUEPRINT.md` § 10.1 and § 11 | `/me` returns `permissions`; `permissions.ts` exports `isSuperuser()` | Silent on whether the list is **effective** (bypass expanded). If not, superuser/owner UI diverges from the API; `isSuperuser()` invites gating on a flag | `/me` and bootstrap return the effective set from the same function as `has_perm()`; `isSuperuser` is display-only, enforced by a guard test (§ 9) |
| C6 | `AUTH_BLUEPRINT.md` § 10.1 ("the shell's one round trip"); `API_DESIGN.md` § Authentication | `/api/auth/me/` is the shell's single call | Flags, capabilities, nav, localization, environment, limits and session expiry also have to reach the shell | `GET /api/me/bootstrap/` is the shell round trip (§ 7); `/me` remains the identity endpoint |
| C7 | `AGENTS.md` § 3 (Frontend data row) — **protected**; `NEXTJS_STANDARDS.md` §§ 1–2 | "Through `src/lib/api.ts`"; "`src/lib/api.ts` — the only module that makes HTTP calls" | One file becomes the god-file that every team edits; the plan puts platform code under `src/core/` | "Through `src/core/lib/api/`" — a directory, one module per namespace, lint-enforced. `AGENTS.md` needs the owner's confirmation to edit |
| C8 | `NEXTJS_STANDARDS.md` § 6; `DEPLOYMENT.md` § 1 (Frontend) and § 2 (Both) | `NEXT_PUBLIC_API_URL` is the backend base, baked at build | Baking the API origin makes a rebuild per environment and breaks white-label hosts | Browser uses relative `/api` on one origin; server uses runtime `INTERNAL_API_URL`; retire `NEXT_PUBLIC_API_URL` (§ 19) |
| C9 | `AUTH_BLUEPRINT.md` §§ 17.1–17.2 | Frontend and API on separate same-site hosts, with CORS configured for it | Works, but leaves the marker cookie, `Path=/api/` and per-host white-label cookies needing a shared `Domain` | Make **same-origin** (`/api` reverse-proxied) the default topology; same-site-with-CORS becomes the documented alternative (pending decision 1) |
| C10 | `VISION.md` § Non-goals | "Not multi-language or multi-region on day one" | § 22 requires i18n plumbing from day one | Reword the non-goal to "no translations shipped on day one" — plumbing is in, catalogues beyond `en` are out (pending decision 5) |
| C11 | `API_DESIGN.md` § Errors | `fields` is a flat map `{ "email": ["…"] }` | A flat map cannot address `lines[2].quantity`, so nested and list errors collapse to the form level | `fields: [{path, message, code}]` with dotted paths, plus `request_id` — [`API_PLATFORM.md`](API_PLATFORM.md) owns the envelope |
| C12 | `NEXTJS_STANDARDS.md` § 1 | "A `src/components/` directory is not yet present; add it when the second component appears" | The mandatory primitives (§ 13) are platform code from Phase 1 | `src/core/components/` exists from the first frontend module |
| C13 | `DEPLOYMENT.md` § 2 (Frontend, step 3) | "`npm run start`, or a static/edge target if the app allows it" | A per-request CSP nonce needs dynamic rendering and the Node proxy | Remove the static/edge option (§ 18) |

## Pending decisions (for the repository owner)

1. **Same-origin topology as the default** (reverse-proxied `/api`)? Recommended: yes. Everything in
   §§ 2, 8 and 17 is simpler with it, and it deletes CORS from the happy path.
2. **Tenancy** (`DATA_MODEL.md` D3) decides whether the tenant request-context contributor, tenant-keyed
   queries and the tenant switcher ship active or dormant. The seams in §§ 2, 4 and 8.4 exist either way.
3. **Headless primitive library:** Radix UI or React Aria, for dialogs, popovers, selects and menus.
   Pick one; both is the "second way of doing something" `AGENTS.md` § 3 forbids.
4. **Zod generation:** orval, openapi-zod-client, or hand-written zod over generated types. Types are
   generated regardless.
5. **i18n plumbing on day one** versus the current `VISION.md` non-goal (C10).
6. **Column order** (§ 11): actions sticky on the right, as specified, or first after the identifier.
7. **Impersonation session model:** browser-wide cookie session (as specified) or a tab-scoped design.
8. **Service worker and offline shell:** in core, or a small module.
9. **Style CSP:** `'unsafe-inline'` for styles (as specified) or style nonces with the third-party
   breakage that implies.
10. **Does the core ship a second portal skeleton** to prove § 21, or leave portals to the first product
    that needs one?

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section. Next.js facts were checked against
> `frontend/node_modules/next/dist/docs/` for the installed 16.3.4 on the same date — re-check them after
> any Next upgrade.
