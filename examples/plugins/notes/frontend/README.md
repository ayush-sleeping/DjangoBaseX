# Notes: frontend half

Mounted at `/notes` by `scripts/plugins.py link notes`, which symlinks this directory to
`frontend/src/plugins/notes` and regenerates `frontend/src/plugins/registry.generated.ts`.

- `index.ts` default-exports `{ name, pages }`; `""` is `/notes` itself.
- `notes.ts` is the plugin's API module (its `src/core/lib` equivalent). Pages call it, never
  `fetch()`.
- `notes-page.tsx` is a client component: the data is authenticated, and the session is an
  httpOnly cookie.
- Its copy is in `messages/en.json` (the source) under the one key `notes`, typed by `i18n.ts`
  and read with `useT("notes")`. `messages/de.json` is deliberately partial: a German reader sees
  its two keys and the English source for every other one, key by key (BUILD_ORDER 8.4d).
