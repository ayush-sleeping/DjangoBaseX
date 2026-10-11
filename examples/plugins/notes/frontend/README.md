# Notes: frontend half

Mounted at `/notes` by `scripts/plugins.py link notes`, which symlinks this directory to
`frontend/src/plugins/notes` and regenerates `frontend/src/plugins/registry.generated.ts`.

- `index.ts` default-exports `{ name, pages }`; `""` is `/notes` itself.
- `notes.ts` is the plugin's API module (its `src/core/lib` equivalent). Pages call it, never
  `fetch()`.
- `notes-page.tsx` is a client component: the data is authenticated, and the session is an
  httpOnly cookie.
