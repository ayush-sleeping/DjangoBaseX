# Enquiries: frontend half

Mounted at `/enquiries` by `scripts/plugins.py link enquiries`, which symlinks this directory to
`frontend/src/plugins/enquiries` and regenerates `frontend/src/plugins/registry.generated.ts`.

- `index.ts` default-exports `{ name, pages }`; `""` is `/enquiries` itself.
- `enquiries.ts` is the plugin's API module (its `src/core/lib` equivalent). Pages call it, never
  `fetch()`. `permissions.ts` declares the five permission codes.
- `enquiries-page.tsx` is a client component: the data is authenticated, and the session is an
  httpOnly cookie. It offers one button per `allowed_transitions` entry; moving to `lost`, or from
  `lost` back to `new`, asks for a reason (the backend answers `reason_required` without one).
- The currency is a free text field with no default: no currency code is hard-coded anywhere.
- Its copy is in `messages/en.json` (the source) under the one key `enquiries`, typed by `i18n.ts`
  and read with `useT("enquiries")`. Other languages are optional and fall back to English.
