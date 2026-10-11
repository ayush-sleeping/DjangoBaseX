# ADR-0009: Browser auth is JWT in `httpOnly` cookies, backed by a database session row

**Status:** Accepted
**Date:** 2026-10-11

## Context

`config/settings.py` configures DRF `SessionAuthentication`, while the roadmap planned SimpleJWT.
The two have different CSRF, CORS, storage and refresh rules. Whichever the first authenticated
endpoint used would have settled the question by accident (`TECH_DEBT` DB-1, `BUILD_ORDER` 0.2).
[`AUTH_RND.md`](../planning/AUTH_RND.md) set out the options and asked four questions. The owner
answered them on 2026-10-11:

1. **Will non-browser clients call the API?** Yes, likely: mobile apps or third-party integrations.
2. **Must logout and deactivation take effect straight away?** Yes.
3. **One server or several?** Several, from day one.
4. **Who writes the frontend auth layer?** It lives in this repository. That makes it the core's
   job, written once in `src/lib/api.ts`.

## Decision

The browser authenticates with a **JWT access token (10 minutes) and a refresh token (14 days
absolute, 7 days idle), both in `httpOnly`, `Secure`, `SameSite=Lax` cookies**. The refresh cookie
is scoped to the refresh path. Each refresh token is **rotated on use with reuse detection**, and
each refresh token is a **`users_user_session` row**, so signing out, signing out everywhere, a
password change or deactivation revokes the row and the access token stops working. Writes carry a
session-bound CSRF token (double-submit). Tokens are encoded with `pyjwt`, not a JWT framework.
Everything else is specified in `AUTH_BLUEPRINT.md` decisions A4, A5, A21–A23 and Ch. 6, which is
the build spec.

**Machine callers** (integrations, other systems) do not use these cookies. They use the opaque,
hashed, revocable API tokens of `API_PLATFORM.md` §§ 7–8, checked by the same RBAC layer.

## Consequences

- An XSS bug cannot read the tokens, which removes the biggest weakness of a token kept in browser
  storage.
- Revocation is real, but **not instantaneous across servers by default**. Each server caches the
  "is this session live" answer for `SESSION_LIVENESS_CACHE_TTL` (60 seconds), so a revoked session
  can work for up to a minute. Setting it to `0` makes revocation immediate at the cost of one
  database read per request. The default is a deliberate trade, and products can change it.
- **Several servers require a shared cache (Redis) from day one.** Session liveness, the permission
  version and every throttle live in Django's cache, and the per-process `LocMemCache` would make
  them per worker (A19). This is `BUILD_ORDER` 1.0, and it moves Redis forward from 4.4.
- **Authenticated data is fetched client-side.** Server components do not attach `httpOnly` cookies
  to their own `fetch()`. One that needs authenticated data must forward the cookie explicitly, and
  getting this wrong fails silently with the empty state. The rule goes into `NEXTJS_STANDARDS.md`
  with `BUILD_ORDER` 1.1.
- The frontend and API must share a registrable domain for `SameSite=Lax` to work (A21). A
  different domain would force `SameSite=None` and a CSRF rework.
- **Costs.** We own rotation, reuse detection, the two-tab grace window (A23), the CSRF token and
  the client's refresh-and-retry. That is much more code than sessions, and a mistake in rotation
  is a silent security bug. `AUTH_BLUEPRINT.md` Ch. 14 specifies the tests that must exist.
- **A first-party mobile app is not decided here.** It cannot use these cookies comfortably, and
  `API_PLATFORM.md` § 21 (row 2) removes the blueprint's `Authorization: Bearer` fallback from the
  cookie authenticator. When a mobile app is real, how it authenticates gets its own ADR.
- `SessionAuthentication` stays in `settings.py` until `CookieJWTAuthentication` replaces it in
  `BUILD_ORDER` 1.1b. No endpoint authenticates yet, so nothing depends on it.

## Alternatives considered

| Option | Why not |
|--------|---------|
| A — Django sessions | Simplest, already configured, and revocation is instant. But with non-browser clients likely and several servers, it means running two mechanisms anyway, with sessions as the browser-only one, and building a second token system later |
| B — JWT in JavaScript-readable storage | Any XSS can steal the token. This trades away the one protection that matters most |
| C without a DB session row (pure stateless JWT) | A token cannot be withdrawn before it expires, which fails the "logout must take effect" requirement |
| SimpleJWT as the implementation | It brings its own rotation, blacklist and settings, which would duplicate Ch. 6's session rows and disagree with them about what "revoked" means (`AUTH_BLUEPRINT.md` Ch. 16) |
