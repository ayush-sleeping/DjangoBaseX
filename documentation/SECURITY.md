# DjangoBaseX — security

> **Status:** Hub — checked 2026-11-14 · built: cookie-JWT auth with DB sessions, RBAC, route enforcement, scrubber, encryption service, secret-env guard, safe outbound HTTP and the non-production guard (BUILD_ORDER 7.4).

A hub, not a spec. **The deep spec** is [`system-design/SECURITY.md`](system-design/SECURITY.md) (threat model, rules by area, production checklist). Detail: [`AUTH_BLUEPRINT.md`](system-design/AUTH_BLUEPRINT.md), [`AUTH_FAILURE_MODES.md`](system-design/AUTH_FAILURE_MODES.md), [`RBAC_DESIGN.md`](system-design/RBAC_DESIGN.md). Testing side: [`TESTING.md`](TESTING.md). Siblings: [`INVARIANTS.md`](INVARIANTS.md), [`system-design/TRAPS.md`](system-design/TRAPS.md).

## Where to read

| Need | Section |
|---|---|
| Threat model, what is and is not guaranteed | the deep spec, "Threat model" and "What the core guarantees" |
| Login, refresh, sessions, MFA flows | `AUTH_BLUEPRINT.md` § 6 |
| Authorization engine; fail-closed machinery | `AUTH_BLUEPRINT.md` § 7, § 9; `RBAC_DESIGN.md` "Fail closed, everywhere" |
| Public-route ledger; test plan | `AUTH_BLUEPRINT.md` § 14 |
| How auth fails silently (catalogue + checklist) | `AUTH_FAILURE_MODES.md` § 2, § 3 |
| Production hardening | the deep spec, "Production checklist" |

## Rules

| # | Rule | Gold standard | Anti-pattern | Check |
|---|---|---|---|---|
| 1 | **Auth is JWT in `httpOnly` cookies backed by a DB session row** ([ADR-0009](adr/0009-jwt-in-httponly-cookies.md)); revocation is real; JS never sees the credential | `backend/users/cookies.py`, `backend/users/authentication.py`, `backend/users/tests/test_auth_flow.py` | Token in `localStorage`; "valid until it expires" as logout | `uv run pytest users/tests` |
| 2 | **Every route declares a permission**; `required_permissions` per action; default is deny | `backend/users/views.py` (`required_permissions` map), `backend/core/permissions.py` (`DefaultDeny`, `HasPermission`) | A view with no permission, or one reachable anonymously without a ledger entry | `backend/tests/architecture/test_route_enforcement.py` (anonymous → 401/403, **404 fails**); `test_public_routes.py` pins the public set; `test_permission_codes.py` |
| 3 | **Object layer too**: detail routes resolve through the scoped queryset, so an invisible row is **404, not 403** (derived from `User.objects.visible_to(...)` in `UserViewSet.get_queryset`; spec: `AUTH_BLUEPRINT.md` § 7, § 14) | `backend/users/views.py::get_queryset` | `Model.objects.get(pk=...)` after only an entity-level check | Write a test with two users and assert the other's row is 404. *No dedicated 404 test found in `users/tests/test_users_api.py` — add one when touching scoping.* |
| 4 | **Fail closed**: an unresolvable permission, setting or input is an error, never a default-allow | `DefaultDeny` in `core/permissions.py`; `RBAC_DESIGN.md` "Fail closed" | `try/except: pass` around an authorization check | `test_permission_codes.py` (undeclared code denies everyone — caught in CI) |
| 5 | **Nothing credential-shaped reaches a log, audit diff or report unscrubbed**: one scrubber, `core.observability.scrub.scrub()` (never mutates, never raises) | `backend/core/observability/scrub.py`; `backend/core/observability/logging.py` | A second ad-hoc redaction; `logger.info(request.headers)` | `backend/tests/test_scrub.py`, `test_scrub_entropy.py`, `test_audit_record.py`; `test_audit_rules.py` forces writes through `core.audit.record()` |
| 6 | **Encrypt at rest only via `core.crypto`** (`encrypt`/`decrypt`/`mask`, per-purpose keys, `FIELD_ENCRYPTION_KEYS` newest first); decrypt is an explicit service call, never on attribute access | `backend/core/crypto.py`; `backend/tests/test_crypto.py` | Own Fernet in a model; a property that calls `decrypt()` | `test_encrypted_columns_are_registered.py`, `test_no_decrypt_on_access.py` |
| 7 | **Secrets only via env, read only in settings.** Key names only in docs and output; every new key goes into `backend/.env.example` (or `frontend/.env.example`) with a placeholder in the same change. `NEXT_PUBLIC_*` is never a secret | `backend/config/settings.py`; `backend/.env.example` | `os.environ["STRIPE_SECRET_KEY"]` in a module; a real value in an example file | `test_secret_env_reads.py`, `test_env_example.py` (placeholders must be refused by `weak_reason()`), `test_secret_policy.py`, `test_production_boot.py` |
| 8 | **The repo is public** (`AGENTS.md` § 1 rule 5): no real credentials, customer data, internal URLs or other codebase names; demo credentials obviously fake | `backend/.env.example` | Pasting a working token "just for the example" | Before any push: `git status`, then `git diff --cached \| grep -iE "secret\|password\|token\|api[_-]?key"` and read every hit |
| 9 | **Every outbound call goes through `core.http.client(purpose)`; outside production the guard is on** — private ranges refused inside the connect, HTTP outside `OUTBOUND_ALLOWLIST` gets a synthetic 423, mail goes only to `NONPROD_TEST_RECIPIENT`; no setting disables it | `backend/core/http/vetting.py`, `backend/core/http/guard.py`, `backend/core/mail/backends.py` | `httpx`/`requests` called directly; trusting a hostname validated once, then resolved again by the library (DNS rebinding) | `backend/tests/core/http/test_ssrf.py`, `test_guard_http.py`, `backend/tests/core/test_outbound_guard.py`, `backend/tests/architecture/test_outbound_http_goes_through_core_http.py` |
| 10 | **The page CSP is per-request and its mode is a runtime variable** (`CSP_MODE`, read in `proxy.ts` at request time; Report-Only by default; no origin literal in code) | `frontend/src/proxy.ts`, `frontend/src/core/lib/security/csp.ts` | Reading the mode at module load or from `NEXT_PUBLIC_*`; the nonce only on the response | `src/proxy.test.ts`, `csp.test.ts` |
| 11 | **Static response headers come from one tested list** (`securityHeaders()`; HSTS in production only); the nonce CSP stays in `proxy.ts` | `frontend/src/core/lib/security/headers.ts` | an inline header list in `next.config.ts`; HSTS on localhost | `security-headers.test.ts`; wiring pending (DB-93) |
| 12 | **Server-to-server routes authenticate with a shared secret, constant time, fail closed** (`/fe/revalidate/`, `REVALIDATE_SECRET`): unset refuses everything; the secret is never logged | `frontend/src/app/fe/revalidate/route.ts` | `===` on the secret; an unset secret that lets requests through | `route.test.ts` |
| 13 | **Inbound webhooks are verified over the raw body first, fail closed on a missing secret, and are deduplicated only after the signature is proven**; invalid signature is one `InvalidSignature` answering 400 `invalid_signature`; the route is in the public ledger | `backend/core/webhooks/inbound.py`, `backend/tests/core/webhooks/test_inbound.py` | A signature over re-serialised JSON; verification passing when the secret is empty; claiming the delivery id before verifying | `uv run pytest tests/core/webhooks/test_inbound.py`; `test_public_routes.py` |
| 14 | **A machine call passes only if the token's scope AND its consumer's service role (live) grant the code; a token is never a user, never a superuser, never reaches a `human_only` or session-only view, and the cookie authenticator is untouched** (`credential_kinds`, default `{"session"}`; digest compared with `hmac.compare_digest`; plaintext once, `no-store`) | `backend/core/api_tokens/auth.py`, `backend/core/permissions.py` (`CredentialKindAllowed`), `backend/core/api/views.py` | a scope-only check keeps working after the role lost the permission; a token on a session view skips the scope gate; both look like ordinary 200/403 |

## Before merging anything security-sensitive

- [ ] Every new/changed route has a declared permission and a **403 test** for a session lacking it; `test_route_enforcement.py` and `test_public_routes.py` green (a new public route is justified in the diff).
- [ ] Detail lookups go through the scoped queryset; ownership (`user`, `owner`) comes from `request.user`, never the payload.
- [ ] No secret, token or `.env` value in the diff, logs, docs or test output; new env keys are in `.env.example` with placeholders; the pre-push grep above was read.
- [ ] New sensitive data is encrypted via `core.crypto` and registered; new log/audit paths go through `scrub()`.
- [ ] Skim the matching entry in `AUTH_FAILURE_MODES.md` § 2 and the checklist in § 3.
- [ ] Gate green ([`TESTING.md`](TESTING.md) § 1), including Postgres-only tests if locking or constraints are involved.
- [ ] Asked for approval before commit or push (`AGENTS.md` § 1 rule 1).
