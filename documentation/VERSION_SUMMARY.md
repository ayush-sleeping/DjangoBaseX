# Version Summary

**Shippable features, by version.** Coarser than [`DAILY_CHANGES.md`](DAILY_CHANGES.md): a reader
here wants to know *what this version can do*, not what was touched.

A refactor, a doc change or a fix nobody noticed does not get an entry. A capability that did not
exist before does.

---

## Unreleased

- **Sign in** (2026-10-11): email + password login into `httpOnly` cookie JWTs, rotating refresh
  tokens with reuse detection and a two-tab grace window, logout, sign-out-everywhere-else and
  `/api/auth/me/`, with a minimal `/login` page ([ADR-0009](adr/0009-jwt-in-httponly-cookies.md)).
  Password reset by email, throttling and progressive lockout followed the same day.
  TOTP two-factor (setup, recovery codes, a login code step) and re-auth for sensitive actions
  followed. Not deployable yet: no invitations or RBAC. See
  [`planning/ROADMAP.md`](planning/ROADMAP.md).
- **One-command setup** (2026-10-22): `./scripts/setup.sh` goes from a fresh clone to a signed-in
  app on PostgreSQL 16 + Redis in Docker (or `--no-docker` on SQLite). It generates every secret,
  picks free ports, names the stack after the directory, and is safe to re-run.
- **Core drift detection** (2026-10-22): `python3 scripts/core_doctor.py` names every core file a
  product has changed, against `core.manifest.json`. `core-guard.yml` fails a product PR that edits
  core without the `core-change` label, and fails a core PR that forgets to regenerate the manifest.
- **Runtime settings** (2026-10-24): settings declared in code, overridden in the database by an
  admin (`manage.py set_setting`, `PATCH /api/core/settings/<key>/`) and live on every worker at
  once. The first two: `security.reauth.actions` and `security.reauth.window_minutes`.
  - **Breaking:** `REAUTH_ACTIONS` and `REAUTH_WINDOW_MINUTES` are no longer read from env. A
    product that set them must run `manage.py set_setting security.reauth.actions <list>` once.
- **Encryption at rest with key rotation** (2026-10-24): a `FIELD_ENCRYPTION_KEYS` keyring,
  `manage.py rotate_encryption --verify`, and MFA secrets on it.
  - **Breaking:** `MFA_ENCRYPTION_KEY` is replaced by `FIELD_ENCRYPTION_KEYS` (comma-separated,
    newest first). Put the old key's value there before migrating; `users` migration 0006 reads the
    old key once to re-encrypt and refuses to run if devices exist and no key is available.
- **Money** (2026-10-24): `core.money` value objects, `allocate()`, string amounts on the wire.
- **Project identity** (2026-10-22): set `PRODUCT_NAME` (and `PRIMARY_DOMAIN`), and page titles,
  the sign-in page, the API title, the authenticator issuer, the from-address and the cookie and
  cache prefixes all follow.
  - **Breaking for an existing checkout:**
    - Unless `AUTH_COOKIE_PREFIX` is set, the auth cookies are renamed from `dbx_*` to
      `<slug>_*`. Everyone is signed out once, and the frontend's `NEXT_PUBLIC_AUTH_COOKIE_PREFIX`
      must match the backend's.
    - `DEFAULT_FROM_EMAIL` now defaults to `<name> <no-reply@<domain>>`.
    - `/api/health/` no longer returns `app`.
    - `MFA_ISSUER` now defaults to `PRODUCT_NAME`. New enrolments show the product's name, while
      devices that already enrolled keep their old label. Set `MFA_ISSUER` to keep the old one.

---

### Format

```markdown
## v0.2.0 — YYYY-MM-DD

**Added**
- Feature, described by what a user can now do.

**Changed**
- Behaviour that differs from the previous version.

**Fixed**
- A bug that was affecting people, and how it showed up.

**Breaking**
- What a product copied from an earlier version must change. Be specific; this is the section
  people read.
```
