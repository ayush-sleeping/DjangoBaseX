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
| `src/lib/` | Everything that is not a route or a component — API client, helpers, types |
| `src/lib/api.ts` | **The only module that makes HTTP calls** |
| `public/` | Static assets, served from `/` |

🔜 A `src/components/` directory is not yet present; add it when the second component appears, not
before.

---

## 2. The API boundary — the one rule that matters most

**All backend calls go through `src/lib/api.ts`. Never `fetch()` inside a component.**

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

**Type every response.** An untyped API response is an `any` that spreads through the component tree.

🔜 Generating types from the backend's `/api/schema/` is planned (`TECH_DEBT` **DB-4**). Until then
response types are hand-written in `src/lib/`, and they can silently drift from the API — which is
exactly why the generation is worth doing.

---

## 3. Server and client components

- **Server by default.** Add `"use client"` only when the component needs state, an effect, an event
  handler, or a browser API
- Push `"use client"` **as far down the tree as possible.** A `"use client"` on a layout makes
  everything beneath it a client component
- **Authenticated requests are client-side for now** — there is no server-side session forwarding
  implemented. When auth lands this needs a deliberate decision, not an accident
- Never put business logic in a page or a component (`AGENTS.md` § 3). It goes in `src/lib/`

---

## 4. TypeScript

- **`strict` is on.** Keep it on
- **No `any`.** `unknown` plus a narrow, if you genuinely don't know
- **No `@ts-ignore`** without a comment saying why and what would remove it
- Type props explicitly; do not rely on inference across a module boundary
- `npx tsc --noEmit` must pass. There is no `typecheck` script yet (`TECH_DEBT` **DB-2**)

---

## 5. Styling

- **Tailwind 4**, utility-first. Tailwind 4 is configured through CSS, not `tailwind.config.js` —
  check `postcss.config.mjs` and the global stylesheet before looking for a config file that isn't
  there
- No inline `style={{}}` except for genuinely dynamic values (a computed width, a chart colour)
- Extract a component when a class list repeats, not a `@apply` rule — `@apply` hides the styles from
  the place they are used

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

---

## 7. Before you say it's done

```bash
cd frontend
npm run lint
npx tsc --noEmit
```

⚠️ **`npm run build` is not part of the routine gate** — it is slow and it writes `.next/`, which the
running dev server is also using. Run it deliberately, with the dev server stopped, when you have
changed something only a production build exercises.

There are **no frontend tests**. These two commands are the whole safety net; report their real
output (`AGENTS.md` § 1, rule 9).
