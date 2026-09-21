# Authentication, Authorization & RBAC — The Build Blueprint

**This is the implementation spec.** [`RBAC_DESIGN.md`](RBAC_DESIGN.md) says *what the policy is and
why*; this says **exactly what to build** — every table, every column, every foreign key, every
file, every function signature, and how they connect.

**It exists so that "start coding" means opening this file at Chapter 9 and typing.** If you find
yourself designing while implementing, this document failed and should be fixed in the same PR.

> **Every non-obvious choice below states its reason.** They are collected in
> [`AUTH_FAILURE_MODES.md`](AUTH_FAILURE_MODES.md), which catalogues the failure each one defends
> against — read that first if a decision here looks arbitrary. Where a cheaper option was rejected,
> the rejection is argued rather than implied, so a future reader can reopen it on the merits.

---

## Table of contents

| Ch | Chapter | What you get |
|----|---------|--------------|
| 1 | [The decisions this encodes](#1-the-decisions-this-encodes) | Every choice, its reason, its reversal cost |
| 2 | [The three apps and why they split](#2-the-three-apps-and-why-they-split) | `core` · `users` · `rbac` |
| 3 | [The database — every table](#3-the-database--every-table) | 13 tables, every column, every FK |
| 4 | [The entity-relationship map](#4-the-entity-relationship-map) | How the FKs connect |
| 5 | [The file tree](#5-the-file-tree) | Every file, and what lives in it |
| 6 | [Authentication — the flows](#6-authentication--the-flows) | Login, refresh, logout, reset, MFA, re-auth |
| 7 | [Authorization — the engine](#7-authorization--the-engine) | Catalog, registry, backend, the two layers |
| 8 | [RBAC — roles and seeding](#8-rbac--roles-and-seeding) | Roles, grants, system roles |
| 9 | [The fail-closed machinery](#9-the-fail-closed-machinery) | **The part that is usually missing** |
| 10 | [The API surface](#10-the-api-surface) | Every endpoint, verb, permission, status |
| 11 | [The frontend contract](#11-the-frontend-contract) | `/me`, `can()`, `api.ts` |
| 12 | [Settings](#12-settings) | Every setting and env var |
| 13 | [Migration order](#13-migration-order) | The sequence that cannot be reordered |
| 14 | [The test plan](#14-the-test-plan) | What must exist before this is "done" |
| 15 | [Build sequence](#15-build-sequence) | Mapped onto `BUILD_ORDER.md` tasks |
| 16 | [Runtime dependencies](#16-runtime-dependencies) | What goes into `pyproject.toml`, and why each one |
| 17 | [The deployment contract](#17-the-deployment-contract) | Same-site, CORS, proxies, cache — what breaks this in production |
| 18 | [Outbound email](#18-outbound-email) | The two flows that cannot run without it |
| 19 | [Bootstrap and operations](#19-bootstrap-and-operations) | Account one, retention, key rotation |
| 20 | [The Django admin](#20-the-django-admin) | The second auth system nobody specified |
| — | [Appendix B — the gap review](#appendix-b--the-gap-review) | What a design review found in Ch. 1–15 |

---

## 1. The decisions this encodes

> ⚠️ **Two of these are `BUILD_ORDER` 🚧 DECISION items (`0.1`, `0.2`) and are not yet ADRs.** They
> are written here as **stated assumptions** so the rest of the book is concrete. If the owner
> decides differently, the reversal cost is in the last column — and Chapter 13 says what has to
> change.

| # | Decision | Choice | Why | Reversal cost |
|---|----------|--------|-----|---------------|
| A1 | Custom `User` model | **Yes**, `users.User` | Costs nothing today, very expensive at product three | 🔴 Catastrophic after first migration |
| A2 | Login identifier | **Email**, `USERNAME_FIELD = "email"`, no username | All 3 converged. A back office is an email world | 🔴 Data migration + every auth screen |
| A3 | User state | **Booleans** — `is_active`, `is_staff`, `is_superuser` | A free-text `status` column compared `!= "ACTIVE"` makes a typo in any writer a silent grant. A boolean has two states and no spelling | 🟡 One migration |
| A4 | Token mechanism | **JWT access + refresh, both in `httpOnly` cookies**, refresh rotated with reuse detection, **backed by a DB session row** | A separate Next.js client rules out plain sessions; a DB row is what makes revocation immediate, because a purely stateless token cannot be withdrawn | 🔴 Rewrites Ch. 6 |
| A5 | Session records in DB | **Yes**, `users_user_session` | "Sign out everywhere" and instant revocation are impossible without it. Stateless JWT cannot be revoked | 🟠 New table, new middleware |
| A6 | Permission catalog | **Declared in code**, seeded to DB | A catalog in code is reviewable in a diff and cannot drift from the code referencing it. Held as DB metadata it is unverifiable, and a mismatch denies everyone while the grant looks correct on screen | 🔴 Rewrites Ch. 7 |
| A7 | Permission naming | `<module>.<feature>.<action>` | Already settled in `RBAC_DESIGN.md`. Scoped by module, so two plugins cannot collide. Globally unique codenames would couple otherwise independent modules | 🟠 Re-seed + data migration |
| A8 | Role model | **Our own `Role`**, not `auth.Group` | `Group` carries no description, no system flag, no ordering, and drags in `auth.Permission` | 🟠 One migration |
| A9 | Django's `auth.Permission` | **Not used.** Our own `rbac.Permission` + a custom auth backend | Django's permission table is bound to content types, so permissions belonging to no model need rowless anchor models to exist at all. A custom backend answering `has_perm()` is less machinery and no content-type coupling | 🔴 Rewrites Ch. 7 |
| A10 | Per-user permission grants | **No.** Roles only | Already argued in `RBAC_DESIGN.md`: once a user can hold a permission no role grants, "what can this person do?" stops being answerable from their roles | 🟢 Additive if ever reversed |
| A11 | Explicit denies | **No.** Grant-only | All 3 converged. Denies turn authorization into a precedence puzzle | 🟢 |
| A12 | Superuser | **One `is_superuser` flag**, and it is **audited, never silent** | A bypass hides breakage from exactly the people most able to fix it, so ours leaves a trail on every use | 🟢 |
| A13 | Object-level scoping | **`visible_to(user)` mandatory on every listable model** | `DATA_MODEL.md` § 5 already requires it. Layer 2 is the layer most often skipped entirely | 🔴 If skipped, retrofitting is every view |
| A14 | Gate attachment | **Declarative `required_permissions` on the viewset**, default-deny, **verified at boot** | **The differentiator.** See Ch. 9 | — |
| A15 | External ids | **Integer PKs internally**, opaque public ids on user-facing resources | `/users/1` tells an attacker there is a user 2, and roughly how many users exist | 🟠 Serializer + URL change |
| A16 | MFA | **TOTP**, optional per user, **enforceable per role** | TOTP needs no mail deliverability to work, and a role-level requirement is what makes it enforceable rather than optional | 🟢 Additive |
| A17 | Throttling | **Per-identifier + per-IP**, plus progressive lockout | The login endpoint is the one endpoint the whole internet can reach | 🟢 Additive |
| A18 | Re-auth | **`RequiresRecentAuth`**, named actions, **off by default**, returns **`423`** | Without it, one compromised session is total takeover for as long as that session lives | 🟢 Additive |
| A19 | Cache backend | **A shared cache is required the moment more than one process serves requests** | The permission-version counter, session liveness and every throttle live in `django.core.cache`. `LocMemCache` is per process, so all three silently become per worker | 🟠 Config + a boot check |
| A20 | Client IP | **`TRUSTED_PROXY_COUNT`**, counted from the **right** of `X-Forwarded-For`; `REMOTE_ADDR` when `0` | Per-IP lockout keyed on a load balancer's address locks out every user at once, on the first attacker | 🟢 Additive |
| A21 | Where the frontend sits | **Same registrable domain as the API.** `SameSite=Lax` | `Lax` cookies are not sent on cross-**site** XHR. A different domain forces `SameSite=None`, giving up the cheapest CSRF defence there is | 🟠 Cookie + CSRF rework |
| A22 | CSRF token | **Session-bound — `HMAC(JWT_SIGNING_KEY, jti)`**, not a bare random value | A plain double-submit value can be planted by anything able to set a cookie on a parent domain | 🟢 Additive |
| A23 | Refresh rotation race | **A grace window.** A token rotated within `REFRESH_ROTATION_GRACE` replays its successor instead of tripping reuse detection | Two browser tabs are ordinary use. Without this, ordinary use logs the user out | 🟠 One column |
| A24 | Django admin | **Off unless `ADMIN_ENABLED`**, and never a writer of `rbac_*` | It is a second authentication *and* authorization system that bypasses every guard in Ch. 8 | 🟢 Config |
| A25 | The first account | **`manage.py bootstrap_admin`** — idempotent, refuses once any user exists | With `is_active` defaulting `False` and invitations the only way in, nothing else can create account one | 🟢 Additive |

**Two common patterns deliberately rejected**, both argued in
[`AUTH_FAILURE_MODES.md`](AUTH_FAILURE_MODES.md):

1. **Metadata-driven route→permission resolution** — reconstructing which permission a route needs
   from its name, its controller class, or a lookup table. It works while there are ten controllers
   and collapses at a few hundred routes, by which point the resolver is larger than the feature it
   guards. **A core is copied into products that reach the second scale.**
2. **A broad superuser bypass** covering the people most likely to test a feature. See A12 and
   Ch. 9.5.

---

## 2. The three apps and why they split

```
backend/
├── config/        composition root — settings, root urls, asgi/wsgi
├── core/          the platform: registry, base models, enforcement primitives, boot checks
├── users/         identity + authentication: who you are, and proving it
└── rbac/          authorization: what you may do
```

| App | Owns | Must never |
|-----|------|-----------|
| `core` | `Registry`, base model classes, DRF permission classes, exception handler, system checks, `Setting`, `ActivityLog` | Import `users` or `rbac` at module level |
| `users` | `User`, `UserSession`, `Invitation`, `PasswordResetToken`, `MfaDevice`, `MfaRecoveryCode`, `LoginAttempt`, all `/api/auth/` endpoints | Import `rbac` models. It may reference `rbac.Role` **by string** only |
| `rbac` | `PermissionGroup`, `Permission`, `Role`, `RolePermission`, `UserRole`, the auth backend, the seeder, the doctor | Import `users` models. Uses `settings.AUTH_USER_MODEL` **as a string** |

### Why three apps and not one

**Because identity and authorization change for different reasons.** A product swapping to SSO,
LDAP or a customer identity provider rewrites `users` and touches nothing in `rbac`. A product
adding organisation-scoped roles rewrites `rbac` and touches nothing in `users`.

### Why `core` imports neither

Put the RBAC engine in `users` and every app wanting to declare a permission must import the users
app — a dependency from every module onto identity, for no reason beyond where a file happened to
live. Moving the shared vocabulary into `core` removes it.

**We start at that arrangement rather than arriving at it.** `core` holds the *mechanism*; `users` and `rbac` hold *models*.
The seam that makes it work:

> **`core.permissions.HasPermission` calls `request.user.has_perm(code)` and nothing else.**
> `rbac` supplies the answer by registering an authentication backend. `core` never imports `rbac`;
> `rbac` never imports `core`'s permission classes. They meet at Django's own `has_perm` contract.

⚠️ **Registering each app.** Per [`DJANGO_STANDARDS.md`](DJANGO_STANDARDS.md) § 2, each of `users`
and `rbac` must be added to `INSTALLED_APPS` **and** to `known-first-party` in
`backend/pyproject.toml`. Forgetting the second makes Ruff fail on files nobody touched
(`TECH_DEBT` **DB-14**).

---

## 3. The database — every table

**14 tables.** Conventions from [`DATA_MODEL.md`](DATA_MODEL.md) § 4 apply throughout: `db_table`
set explicitly, explicit `on_delete` on every FK, never `null=True` on a text field, constraints in
the database, index everything you filter on.

**Shared column shorthand used below:**
- `created_at` — `DateTimeField(auto_now_add=True, db_index=True)`
- `updated_at` — `DateTimeField(auto_now=True)`
- `created_by` / `updated_by` — `FK(AUTH_USER_MODEL, null=True, on_delete=SET_NULL, related_name="+")`

---

### 3.1 `users_user` — identity

The single row that answers "who is this". **Nothing about permissions lives here.**

| Column | Type | Null | Default | Index | Notes |
|---|---|---|---|---|---|
| `id` | `BigAutoField` | no | auto | PK | Internal only — never in a URL (A15) |
| `public_id` | `UUIDField` | no | `uuid4` | **unique** | The id the API exposes |
| `email` | `EmailField(254)` | no | — | **unique** | `USERNAME_FIELD`. Stored **lowercased**, normalised on save |
| `password` | `CharField(128)` | no | — | — | Django-managed hash. `set_unusable_password()` for SSO-only accounts |
| `full_name` | `CharField(255)` | no | `""` | — | `blank=True`, never `null` |
| `is_active` | `BooleanField` | no | `False` | ✔ | **Defaults `False`** — see the callout below |
| `is_staff` | `BooleanField` | no | `False` | — | Django admin access only. **Not** an authorization concept |
| `is_superuser` | `BooleanField` | no | `False` | ✔ | The one bypass (A12) |
| `mfa_enforced` | `BooleanField` | no | `False` | — | Set by role policy; a user may not turn it off |
| `last_login_at` | `DateTimeField` | yes | `NULL` | — | |
| `password_changed_at` | `DateTimeField` | yes | `NULL` | — | Invalidates sessions older than it (Ch. 6.7) |
| `deactivated_at` | `DateTimeField` | yes | `NULL` | — | |
| `deactivated_reason` | `CharField(255)` | no | `""` | — | |
| `created_at` / `updated_at` | | | | ✔ | |

**`Meta.constraints`:** `CheckConstraint(email = lower(email))` — the database refuses a
mixed-case address, so "two accounts, same email" cannot happen through the admin, a shell or a
data migration.

> ⚠️ **`is_active` defaults to `False`, deliberately.** A row created by any path — the admin, a
> shell, a fixture, a half-finished service — cannot log in until something explicitly activates
> it. This posture is normally arrived at the other way round — ship open, then add approval after
> the first unwanted account — and retrofitting it means auditing every path that creates a user.
> `create_superuser()` sets it `True` explicitly.

**Why no `status` string:** the usual alternative is a free-text column compared `!= "ACTIVE"`.
Any typo in any writer silently grants access. A boolean has two states and no spelling.

---

### 3.2 `users_user_session` — what makes revocation real

**One row per issued refresh token.** This is the table that turns stateless JWT into something you
can actually revoke.

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `public_id` | `UUIDField` | no | **unique** | The id `DELETE /api/auth/sessions/<public_id>/` uses (A15) |
| `user_id` | **FK → `users_user.id`**, `on_delete=CASCADE`, `related_name="sessions"` | no | ✔ | Deleting a user removes their sessions |
| `jti` | `CharField(64)` | no | **unique** | The refresh token's JWT id. **Stored hashed** (SHA-256) |
| `family_id` | `UUIDField` | no | ✔ | Constant across one login's rotation chain — see reuse detection |
| `parent_jti` | `CharField(64)` | no (`""`) | — | The token this one replaced. The audit trail of a chain |
| `replaced_by_jti` | `CharField(64)` | no (`""`) | — | The successor. **Required by the rotation grace window** (A23) |
| `issued_at` | `DateTimeField` | no | ✔ | |
| `expires_at` | `DateTimeField` | no | ✔ | Absolute cap, independent of rotation |
| `last_seen_at` | `DateTimeField` | no | — | Sliding idle window |
| `password_confirmed_at` | `DateTimeField` | yes | — | Powers re-auth (A18) — **per session**, not per user |
| `revoked_at` | `DateTimeField` | yes | ✔ | |
| `revoked_reason` | `CharField(32)` | no (`""`) | — | `logout` · `rotated` · `reuse_detected` · `password_changed` · `admin` · `expired` |
| `ip` | `GenericIPAddressField` | yes | — | |
| `user_agent` | `CharField(255)` | no (`""`) | — | |
| `device_label` | `CharField(64)` | no (`""`) | — | Human-readable, for the sessions screen |

**Indexes:** `(user_id, revoked_at)` for the sessions list; `(family_id)` for reuse detection.

> **Refresh-token reuse detection, in one rule:** a refresh token may be used **once**. Using it
> issues a successor and sets `revoked_at` with reason `rotated`. If a token whose `revoked_at` is
> already set is presented again, **every row sharing its `family_id` is revoked immediately**
> (`reuse_detected`) and the user must log in again. That is the standard answer to a stolen
> refresh token, and it is cheap because the family is one indexed column.

> ⚠️ **And the rule that keeps it usable (A23).** Taken literally, the paragraph above logs people
> out for using the product normally. Two browser tabs share one cookie jar but not one JavaScript
> context, so the frontend's single-flight guard (Ch. 11) cannot coordinate them; a reload landing
> mid-refresh does the same thing, and so does any retried request. Both tabs present the same
> refresh token, one rotates it, and the other looks exactly like a thief.
>
> **So a rotated token is only reuse once its grace window has closed.** If a presented token is
> `rotated`, its `revoked_at` is within `REFRESH_ROTATION_GRACE` (default **15 seconds**) and its
> `replaced_by_jti` row is still live, the successor's cookies are re-issued and nothing is revoked.
> Outside that window, or when the successor is already gone, it is reuse and the family dies.
>
> **This is the difference between a design that works on paper and one that survives contact with
> a browser.** Rotation without a grace window is the most common reason refresh-token rotation
> gets ripped out again a month after it ships.

---

### 3.3 `users_login_attempt` — throttling and forensics

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `identifier` | `CharField(254)` | no | ✔ | The submitted email, **lowercased**. Not an FK — the address may not exist |
| `user_id` | **FK → `users_user.id`**, `on_delete=SET_NULL`, `null=True`, `related_name="+"` | yes | ✔ | Set only when the address matched |
| `ip` | `GenericIPAddressField` | yes | ✔ | |
| `user_agent` | `CharField(255)` | no (`""`) | — | |
| `succeeded` | `BooleanField` | no | ✔ | |
| `failure_reason` | `CharField(32)` | no (`""`) | — | `bad_password` · `unknown_user` · `inactive` · `mfa_failed` · `locked` |
| `created_at` | | no | ✔ | |

**Index:** `(identifier, created_at)` and `(ip, created_at)` — the two throttle keys.

> ⚠️ **`identifier` is not a foreign key on purpose.** The whole point is recording attempts against
> addresses that do not exist. An FK would make the most interesting attempts unstorable.
>
> **Retention:** rows older than 90 days are deleted by a scheduled job. This table grows with
> attack traffic, not user count.

---

### 3.4 `users_password_reset_token`

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `user_id` | **FK → `users_user.id`**, `on_delete=CASCADE`, `related_name="password_reset_tokens"` | no | ✔ | |
| `token_hash` | `CharField(64)` | no | **unique** | **SHA-256 of the token. The plaintext is emailed and never stored** |
| `expires_at` | `DateTimeField` | no | ✔ | 30 minutes |
| `used_at` | `DateTimeField` | yes | — | **Single use.** A reset link works once |
| `requested_ip` | `GenericIPAddressField` | yes | — | |
| `created_at` | | no | ✔ | |

**Why a table rather than Django's stateless token generator:** single-use enforcement, an audit
trail, and the ability to invalidate every outstanding token when a password changes. Without the
row, a takeover performed through the reset flow leaves no forensic trail at all.

---

### 3.5 `users_invitation`

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `public_id` | `UUIDField` | no | **unique** | The id `POST /api/users/invitations/<public_id>/revoke/` uses (A15) |
| `email` | `EmailField(254)` | no | ✔ | Lowercased |
| `role_id` | **FK → `rbac_role.id`**, `on_delete=PROTECT`, `related_name="invitations"` | no | ✔ | **`PROTECT`** — a role with pending invitations cannot be deleted out from under them |
| `token_hash` | `CharField(64)` | no | **unique** | Hashed at rest, like a password |
| `invited_by_id` | **FK → `users_user.id`**, `on_delete=SET_NULL`, `null=True`, `related_name="invitations_sent"` | yes | — | |
| `expires_at` | `DateTimeField` | no | ✔ | 7 days |
| `accepted_at` | `DateTimeField` | yes | — | |
| `accepted_user_id` | **FK → `users_user.id`**, `on_delete=SET_NULL`, `null=True`, `related_name="+"` | yes | — | The account it produced |
| `revoked_at` | `DateTimeField` | yes | — | |
| `created_at` | | no | ✔ | |

**Constraint:** partial unique on `(email)` where `accepted_at IS NULL AND revoked_at IS NULL` — one
live invitation per address.

> ⚠️ **This is the only route to a new account** in the default configuration. Combined with
> `is_active` defaulting `False`, there is no self-service signup path unless a product adds one
> deliberately. The usual alternative is open registration gated afterwards by a status field; the
> invitation is the same control, enforced earlier.

---

### 3.6 `users_mfa_device` and `users_mfa_recovery_code`

**`users_mfa_device`**

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `user_id` | **FK → `users_user.id`**, `on_delete=CASCADE`, `related_name="mfa_devices"` | no | ✔ | |
| `label` | `CharField(64)` | no (`""`) | — | "iPhone", "1Password" |
| `secret` | `BinaryField` | no | — | **Encrypted at rest** with a key from `.env`, never the raw base32 |
| `confirmed_at` | `DateTimeField` | yes | — | **Unconfirmed devices do not count.** Setup is not enrolment |
| `last_used_at` | `DateTimeField` | yes | — | |
| `last_used_timestep` | `BigIntegerField` | no (`0`) | — | **The replay guard.** A code whose time step is `<=` this is refused (Ch. 6.8) |
| `created_at` | | no | — | |

**`users_mfa_recovery_code`**

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `user_id` | **FK → `users_user.id`**, `on_delete=CASCADE`, `related_name="mfa_recovery_codes"` | no | ✔ | |
| `code_hash` | `CharField(64)` | no | **unique** | Hashed. Shown once, at generation |
| `used_at` | `DateTimeField` | yes | — | Single use |
| `created_at` | | no | — | |

---

### 3.7 `rbac_permission_group` — UI grouping only

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `code` | `CharField(64)` | no | **unique** | e.g. `users`, `settings` |
| `label` | `CharField(128)` | no | — | "Users & Access" |
| `module` | `CharField(64)` | no | ✔ | The app or plugin that registered it |
| `order` | `PositiveIntegerField` | no (`100`) | — | Display order on the roles screen |

> **Nothing in the code may branch on a group.** It exists so the roles screen groups checkboxes
> readably. `RBAC_DESIGN.md` § "The model" already says this; it is repeated here because the
> common mistake is to make the grouping **load-bearing for authorization** — keying the permission
> model on a UI concept, which then fails silently the moment the two drift apart.

---

### 3.8 `rbac_permission` — one capability

**Declared in code, seeded to this table.** The table is a projection of the code, never the source.

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `code` | `CharField(128)` | no | **unique** | `<module>.<feature>.<action>` — e.g. `users.users.view` |
| `label` | `CharField(128)` | no | — | "View users" |
| `group_id` | **FK → `rbac_permission_group.id`**, `on_delete=PROTECT`, `related_name="permissions"` | no | ✔ | |
| `module` | `CharField(64)` | no | ✔ | Denormalised from the code's first segment, for filtering |
| `is_deprecated` | `BooleanField` | no (`False`) | ✔ | A code that left the catalog but still has grants |
| `created_at` | | no | — | |

> ⚠️ **Seeding never deletes.** A permission that disappears from code is marked `is_deprecated`,
> not dropped. Dropping it would cascade away real grants; if the code returns next release, the
> grants are still there. The doctor (Ch. 9.4) reports deprecated codes that still hold grants.

---

### 3.9 `rbac_role`

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `public_id` | `UUIDField` | no | **unique** | (A15) |
| `name` | `CharField(64)` | no | **unique** | "Administrator" |
| `slug` | `SlugField(64)` | no | **unique** | `administrator` — what code refers to |
| `description` | `CharField(255)` | no (`""`) | — | |
| `is_system` | `BooleanField` | no (`False`) | ✔ | **Cannot be renamed or deleted** |
| `is_elevated` | `BooleanField` | no (`False`) | — | Only a superuser may grant it — see § 8.2 |
| `mfa_required` | `BooleanField` | no (`False`) | — | Holding this role forces `user.mfa_enforced` |
| `created_at` / `updated_at` / `created_by` / `updated_by` | | | | |

---

### 3.10 `rbac_role_permission` — the grant

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `role_id` | **FK → `rbac_role.id`**, `on_delete=CASCADE`, `related_name="role_permissions"` | no | ✔ | Deleting a role removes its grants |
| `permission_id` | **FK → `rbac_permission.id`**, `on_delete=CASCADE`, `related_name="role_permissions"` | no | ✔ | |
| `granted_at` | `DateTimeField` | no | — | |
| `granted_by_id` | **FK → `users_user.id`**, `on_delete=SET_NULL`, `null=True`, `related_name="+"` | yes | — | **Who widened this role, and when** |

**Constraint:** `UniqueConstraint(role, permission)`.

> **Why an explicit through-model rather than a plain `ManyToManyField`:** `granted_by` and
> `granted_at`. "Who gave this role the delete permission, and when" is the first question asked
> after an incident, and a bare M2M cannot answer it.

---

### 3.11 `rbac_user_role` — the assignment

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `user_id` | **FK → `users_user.id`** (`settings.AUTH_USER_MODEL`), `on_delete=CASCADE`, `related_name="user_roles"` | no | ✔ | |
| `role_id` | **FK → `rbac_role.id`**, `on_delete=PROTECT`, `related_name="user_roles"` | no | ✔ | **`PROTECT`** — you cannot delete a role people still hold |
| `assigned_at` | `DateTimeField` | no | — | |
| `assigned_by_id` | **FK → `users_user.id`**, `on_delete=SET_NULL`, `null=True`, `related_name="+"` | yes | — | |

**Constraint:** `UniqueConstraint(user, role)`. **A user may hold several roles; their permissions
are the union** (`RBAC_DESIGN.md` § "The model").

> **Why `PROTECT` on `role` here but `CASCADE` on `role` in `rbac_role_permission`:** deleting a
> role should remove *what it granted*, but must never silently remove *someone's access*. The
> delete fails loudly and the admin reassigns first.

---

### 3.12 `core_activity_log` — append-only audit

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `actor_id` | **FK → `users_user.id`**, `on_delete=SET_NULL`, `null=True`, `related_name="+"` | yes | ✔ | Null for system and for failed logins |
| `impersonator_id` | **FK → `users_user.id`**, `on_delete=SET_NULL`, `null=True`, `related_name="+"` | yes | — | The real operator, when impersonating |
| `verb` | `CharField(64)` | no | ✔ | `auth.login` · `auth.login_failed` · `rbac.role.updated` · … |
| `target_type_id` | **FK → `django_content_type.id`**, `on_delete=SET_NULL`, `null=True` | yes | ✔ | Generic FK |
| `target_id` | `PositiveBigIntegerField` | yes | ✔ | |
| `description` | `CharField(255)` | no (`""`) | — | Human-readable |
| `meta` | `JSONField` | no (`dict`) | — | IP, user agent, changed fields |
| `ip` | `GenericIPAddressField` | yes | — | |
| `created_at` | | no | ✔ | |

> ⚠️ **Append-only. Never updated, never deleted** (`DATA_MODEL.md` § 3, D5). The model overrides
> `save()` to refuse updates and `delete()` to raise. **And every write is wrapped in try/except** —
> **Logging must never break the auth action it observes.**

**Events that must be logged:** `auth.login`, `auth.login_failed`,
`auth.logout`, `auth.token_reuse_detected`, `auth.password_reset`, `auth.password_changed`,
`auth.mfa_enabled`, **`auth.mfa_disabled`**, `auth.reauth_confirmed`, `authz.superuser_bypass`,
`rbac.role.created|updated|deleted`, `rbac.grant.added|removed`, `rbac.user_role.assigned|revoked`,
`users.user.activated|deactivated`.

---

### 3.13 `core_setting`

| Column | Type | Null | Index | Notes |
|---|---|---|---|---|
| `id` | `BigAutoField` | no | PK | |
| `key` | `CharField(128)` | no | **unique** | `security.reauth.window_minutes` |
| `value` | `TextField` | no (`""`) | — | Serialised by `value_type` |
| `value_type` | `CharField(16)` | no | — | `str` · `int` · `bool` · `json` |
| `is_public` | `BooleanField` | no (`False`) | — | Exposed to the frontend bootstrap |
| `updated_at` / `updated_by` | | | | |

Runtime security settings live here (re-auth per action, lockout thresholds) so an operator can
change them without a deploy. **Nothing that grants access lives here** — only thresholds.

---

## 4. The entity-relationship map

```
                          ┌───────────────────────────┐
                          │       users_user          │
                          │  id (PK), public_id       │
                          │  email UQ, password       │
                          │  is_active, is_staff,     │
                          │  is_superuser             │
                          └─────────────┬─────────────┘
                                        │
      ┌──────────────────┬──────────────┼──────────────┬─────────────────┐
      │ CASCADE          │ CASCADE      │ CASCADE      │ CASCADE         │ SET_NULL
      ▼                  ▼              ▼              ▼                 ▼
┌───────────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────────┐ ┌────────────────┐
│users_user_    │ │users_password│ │users_mfa_│ │users_mfa_    │ │users_login_    │
│session        │ │_reset_token  │ │device    │ │recovery_code │ │attempt         │
│ user_id FK    │ │ user_id FK   │ │user_id FK│ │ user_id FK   │ │ user_id FK NULL│
│ jti UQ(hash)  │ │ token_hash UQ│ │secret 🔒 │ │ code_hash UQ │ │ identifier     │
│ family_id ────┼─┐│ expires_at  │ │confirmed │ │ used_at      │ │ ip, succeeded  │
│ revoked_at    │ ││ used_at     │ └──────────┘ └──────────────┘ └────────────────┘
│ password_     │ │└──────────────┘
│  confirmed_at │ │
└───────────────┘ └── self-referencing by value (not FK): every row sharing family_id
                      is revoked together on reuse detection

                          ┌───────────────────────────┐
                          │       users_user          │
                          └──────┬──────────────┬─────┘
                        CASCADE  │              │  SET_NULL (assigned_by, granted_by,
                                 │              │            invited_by, actor, …)
                                 ▼              ▼
                       ┌──────────────────┐   (audit columns on many tables)
                       │  rbac_user_role  │
                       │  user_id    FK   │
                       │  role_id    FK ──┼──── PROTECT ──┐
                       │  assigned_by FK  │               │
                       │  UQ(user, role)  │               │
                       └──────────────────┘               ▼
                                                 ┌──────────────────┐
                       ┌──────────────────┐      │    rbac_role     │
                       │users_invitation  │      │  id (PK)         │
                       │ role_id FK ──────┼─────▶│  slug UQ         │
                       │   PROTECT        │      │  is_system       │
                       │ token_hash UQ    │      │  is_elevated     │
                       └──────────────────┘      │  mfa_required    │
                                                 └────────┬─────────┘
                                                          │ CASCADE
                                                          ▼
                                             ┌────────────────────────┐
                                             │  rbac_role_permission  │
                                             │   role_id       FK     │
                                             │   permission_id FK ────┼──┐
                                             │   granted_by    FK     │  │ CASCADE
                                             │   UQ(role, permission) │  │
                                             └────────────────────────┘  │
                                                                         ▼
                                                            ┌────────────────────┐
                                                            │  rbac_permission   │
                                                            │   id (PK)          │
                                                            │   code UQ          │
                                                            │   is_deprecated    │
                                                            │   group_id FK ─────┼──┐
                                                            └────────────────────┘  │ PROTECT
                                                                                    ▼
                                                            ┌──────────────────────────┐
                                                            │ rbac_permission_group    │
                                                            │  code UQ, label, order   │
                                                            │  (display only)          │
                                                            └──────────────────────────┘

┌──────────────────────┐        ┌────────────────────┐
│  core_activity_log   │        │   core_setting     │
│   actor_id       FK ─┼──▶user │    key UQ          │
│   impersonator_id FK─┼──▶user │    value_type      │
│   target (generic FK)│        │    is_public       │
│   verb, meta, ip     │        └────────────────────┘
│   APPEND-ONLY        │
└──────────────────────┘
```

### The one path that answers every authorization question

```
users_user → rbac_user_role → rbac_role → rbac_role_permission → rbac_permission.code
```

Four joins, one direction, no branches. **There is no second path.** No per-user grants (A10), no
denies (A11), no group-based shortcut. That is what makes "what can this person do?" answerable by
one query, and it is the property lost the moment a second resolution path — route metadata, say —
is added alongside the first.

### `on_delete` summary — the table to get right

| FK | `on_delete` | Consequence if wrong |
|----|-------------|---------------------|
| `user_session.user` | `CASCADE` | Orphan sessions would authenticate a deleted user |
| `user_role.user` | `CASCADE` | Same |
| `user_role.role` | **`PROTECT`** | `CASCADE` would silently strip access from every holder |
| `invitation.role` | **`PROTECT`** | A pending invite would point at nothing and fail on accept |
| `role_permission.role` | `CASCADE` | Deleting a role should remove what it granted |
| `role_permission.permission` | `CASCADE` | A dropped permission's grants go with it |
| `permission.group` | **`PROTECT`** | Deleting a group would delete permissions, and with them, grants |
| every `*_by` audit column | **`SET_NULL`** | `CASCADE` deletes history when a person leaves |
| `activity_log.actor` | **`SET_NULL`** | The audit trail must survive the actor |

> ⚠️ `DATA_MODEL.md` § 2 states it plainly and it is worth repeating: **getting `on_delete` wrong
> here is silent, catastrophic data loss.** Every one of the nine rows above is a deliberate answer,
> not a default.

---

## 5. The file tree

Every file that this design creates. **Nothing in here is optional** — a file listed without a
purpose is a file that should not exist.

```
backend/
├── config/
│   ├── settings.py                    + AUTH_USER_MODEL, AUTHENTICATION_BACKENDS, REST_FRAMEWORK,
│   │                                    JWT keys, CACHES, cookie names, throttles  (Ch. 12, 16)
│   └── urls.py                        + include("users.urls"), include("rbac.urls")
│
├── core/
│   ├── models.py                      Setting, ActivityLog
│   ├── mixins.py                      TimeStampedModel, AuthoredModel, SoftDeletableModel
│   │                                    (DATA_MODEL § 2 — this is where they land)
│   ├── registry.py                    ⭐ Registry: permissions, navigation, settings, health
│   ├── permissions.py                 ⭐ DefaultDeny, HasPermission, HasAnyPermission,
│   │                                    RequiresRecentAuth, IsSuperuser
│   ├── api/
│   │   ├── viewsets.py                ⭐ BaseViewSet — the declarative gate (Ch. 9.1)
│   │   ├── views.py                   ⭐ BaseAPIView — the same gate for non-viewset endpoints
│   │   ├── pagination.py              PageNumberPagination, capped page_size
│   │   └── exceptions.py              custom exception handler → the one error shape
│   ├── checks.py                      ⭐ Django system checks (Ch. 9.2) — W001..E004
│   ├── audit.py                       log_activity(verb, actor, target, **meta)
│   ├── crypto.py                      hash_token(), encrypt_secret(), decrypt_secret()
│   ├── http.py                        ⭐ client_ip(request) — the trusted-proxy rule (Ch. 17.3)
│   ├── routes.py                      ⭐ PUBLIC_ROUTES — the exemption ledger, a reason per entry
│   ├── querysets.py                   VisibleToQuerySet base — the Layer 2 contract
│   ├── management/commands/
│   │   └── auth_cleanup.py            retention: sessions, attempts, tokens, log (Ch. 19.2)
│   └── apps.py                        ready(): connect checks, register core permissions
│
├── users/
│   ├── models/
│   │   ├── user.py                    User, UserManager
│   │   ├── session.py                 UserSession (+ queryset: active(), for_user())
│   │   ├── invitation.py              Invitation
│   │   ├── password_reset.py          PasswordResetToken
│   │   ├── mfa.py                     MfaDevice, MfaRecoveryCode
│   │   └── login_attempt.py           LoginAttempt
│   ├── permissions.py                 the users module's PERMISSION GROUP declaration
│   ├── authentication.py              ⭐ CookieJWTAuthentication (DRF auth class)
│   ├── tokens.py                      issue_pair(), rotate(), decode(), revoke_family()
│   ├── services/
│   │   ├── auth.py                    login(), logout(), refresh(), confirm_password()
│   │   ├── passwords.py               request_reset(), perform_reset(), change_password()
│   │   ├── mfa.py                     begin_setup(), confirm_setup(), verify(), disable()
│   │   ├── invitations.py             invite(), accept(), revoke()
│   │   ├── sessions.py                list_for(), revoke(), revoke_all_except()
│   │   └── lockout.py                 is_locked(), record_attempt(), reset()
│   ├── serializers.py                 Login, Me, Session, Invitation, PasswordReset, Mfa
│   ├── views.py                       thin — parse, delegate, respond
│   ├── throttles.py                   LoginThrottle, PasswordResetThrottle
│   ├── urls.py                        /api/auth/… and /api/users/…
│   ├── admin.py                       UserAdmin (no raw password field)
│   ├── apps.py                        ready(): register permissions, connect signals
│   ├── signals.py                     password_changed → revoke sessions
│   ├── emails.py                      send_password_reset(), send_invitation()  (Ch. 18)
│   ├── templates/users/email/         one .txt + .html pair per message
│   └── migrations/0001_initial.py     ⚠️ MUST be the first migration in the project
│
├── rbac/
│   ├── models.py                      PermissionGroup, Permission, Role, RolePermission, UserRole
│   ├── catalog.py                     ⭐ PermissionGroupSpec / PermissionSpec — the code catalog
│   ├── backends.py                    ⭐ RBACBackend.has_perm() + the per-request cache
│   ├── services.py                    create_role(), set_grants(), assign_role(), revoke_role()
│   ├── selectors.py                   permission_codes_for(user), roles_for(user)
│   ├── seeding.py                     sync_catalog() — idempotent, never deletes
│   ├── serializers.py                 Role, Permission, PermissionGroup, UserRoleAssignment
│   ├── views.py                       RoleViewSet, PermissionListView
│   ├── urls.py                        /api/rbac/…
│   ├── management/commands/
│   │   ├── seed_permissions.py        runs sync_catalog()
│   │   ├── seed_roles.py              the two system roles
│   │   ├── bootstrap_admin.py         ⭐ account one (Ch. 19.1) — refuses if any user exists
│   │   └── permissions_doctor.py      ⭐ the doctor (Ch. 9.4)
│   ├── apps.py                        ready(): register rbac's own permissions
│   └── migrations/
│
└── tests/
    ├── conftest.py                    fixtures: user_factory, role_factory, api_client
    ├── architecture/
    │   ├── test_route_enforcement.py  ⭐ every route, unauthenticated → 401/403, 404 is a FAILURE
    │   ├── test_permission_codes.py   every referenced code exists in the catalog
    │   ├── test_migrations.py         one head per app; every model has a table
    │   └── test_layering.py           views contain no business logic imports
    ├── users/                         login, refresh, rotation, reuse, lockout, reset, mfa, invite
    └── rbac/                          grants, union, seeding idempotency, elevated-role guard
```

**Frontend:**

```
frontend/src/
├── lib/
│   ├── api.ts                         the ONLY place fetch() is called (AGENTS § 3)
│   ├── auth.ts                        login(), logout(), refresh-on-401 interceptor
│   └── permissions.ts                 can(code), canAny(codes), isSuperuser()
├── hooks/
│   └── use-permissions.ts             usePermissions() → { can, canAny, isSuperuser }
├── components/auth/
│   ├── RequirePermission.tsx          renders children only when can(code)
│   └── SessionExpiryWarning.tsx       the idle warning, ~120s before expiry
└── app/(auth)/login/page.tsx          the one unauthenticated route
```

---

## 6. Authentication — the flows

### 6.1 The token model (A4)

| Token | Lifetime | Where it lives | Cookie flags |
|---|---|---|---|
| **Access** | **10 minutes** | `httpOnly` cookie `dbx_access` | `HttpOnly, Secure, SameSite=Lax, Path=/api/` |
| **Refresh** | **14 days** absolute, **7 days** idle | `httpOnly` cookie `dbx_refresh` | `HttpOnly, Secure, SameSite=Lax, Path=/api/auth/refresh/` |
| **CSRF** | matches refresh | **readable** cookie `dbx_csrf` | `Secure, SameSite=Lax` — **not** `HttpOnly` |

**Three properties this buys, each of them commonly missing:**

1. **No token in `localStorage`** — an XSS cannot read `httpOnly`
2. **Revocation is immediate** — every access token is checked against `users_user_session`
3. **The refresh cookie is path-scoped** — it is not sent on ordinary API calls, so the blast radius
   of any single request is one 10-minute access token

> ⚠️ **Cookies mean CSRF applies.** Because authentication rides a cookie the browser attaches
> automatically, every unsafe method (`POST`/`PUT`/`PATCH`/`DELETE`) must carry the `dbx_csrf` value
> in an `X-CSRF-Token` header, compared against the cookie (**double-submit**). The frontend's
> `api.ts` adds it once, centrally. **A request without it is rejected before the view runs.**

> ⚠️ **Next.js rule, write this into `NEXTJS_STANDARDS.md` in the same PR** (`BUILD_ORDER` task
> `1.1` requires it): an `httpOnly` cookie is **not** attached automatically to a `fetch()` made
> from a **server component** — the server component is not the browser. Authenticated data is
> fetched **client-side** by default. A server component that must fetch authenticated data has to
> read the cookie via `cookies()` from `next/headers` and forward it explicitly. **Getting this
> backwards fails silently**: the request succeeds, unauthenticated, and renders the empty state.

### 6.2 Login — `POST /api/auth/login/`

```
1.  Throttle       LoginThrottle: 5/min per (identifier, ip) — both, together
2.  Lockout        lockout.is_locked(identifier, ip)?  → 429, generic message
3.  Normalise      email = email.strip().lower()
4.  Authenticate   django.contrib.auth.authenticate(email=…, password=…)
                   ⚠️ ALWAYS run the password hasher, even when the user does not exist
                      (timing parity — otherwise the endpoint is a user oracle).
                      ModelBackend already does this; do not "optimise" it away by
                      checking for the row first.
                   ⚠️ The backend must be AllowAllUsersModelBackend — see the callout below
5.  Gate           user.is_active?          → generic failure, reason="inactive"
6.  MFA            user.mfa_enforced or has confirmed device?
                      → 200 {"mfa_required": true, "mfa_token": <short-lived, 5 min>}
                      → flow continues at POST /api/auth/mfa/verify/
7.  Issue          tokens.issue_pair(user, request) → creates users_user_session row
8.  Record         LoginAttempt(succeeded=True); lockout.reset(identifier)
9.  Audit          log_activity("auth.login", actor=user, ip=…, meta={user_agent})
10. Respond        204, three Set-Cookie headers. NO token in the body.
```

**Failure response — one shape, always:**

```jsonc
{ "error": { "code": "invalid_credentials",
             "message": "Email or password is incorrect." } }
```

> ⚠️ **Wrong password, unknown address, and inactive account return this identical body and status.**
> The distinct `failure_reason` is recorded in `users_login_attempt`, never returned. Anything else
> makes the endpoint a user-enumeration oracle — `API_DESIGN.md` § Authentication already requires
> this. The usual leak is not the status code but a differently-worded message on one branch.

> ⚠️ **Step 5 is unreachable under the stock backend, and this is not a detail.**
> `ModelBackend.authenticate()` calls `user_can_authenticate()`, which returns `False` for
> `is_active=False` — so `authenticate()` returns `None` and an inactive account is
> indistinguishable from a wrong password *at the service layer*. The response is supposed to be
> identical; **the audit row is not.** With `is_active` defaulting to `False` (§ 3.1), every
> invited-but-not-yet-activated person's login would be filed as `bad_password`, and the one column
> that exists to tell those two apart would be wrong exactly when someone is trying to work out why
> a new joiner cannot get in.
>
> **Authenticate with `django.contrib.auth.backends.AllowAllUsersModelBackend`** (which overrides
> `user_can_authenticate` to return `True`) and make the `is_active` decision yourself in step 5,
> where it can be recorded. The user-visible response does not change. Put that backend in
> `AUTHENTICATION_BACKENDS` **in place of** `ModelBackend`, not alongside it.

### 6.3 Refresh — `POST /api/auth/refresh/`

```
1.  Read dbx_refresh cookie → decode → jti, family_id
2.  Look up users_user_session by hash(jti)
       missing            → 401, clear cookies
       revoked_at is NOT NULL and reason == "rotated"
           within REFRESH_ROTATION_GRACE, successor still live
                          → ✅ RACE, NOT THEFT (A23)
                            re-issue the successor's cookies, revoke nothing
                            → 204
           otherwise      → ⚠️ REUSE DETECTED
                            revoke_family(family_id, reason="reuse_detected")
                            log_activity("auth.token_reuse_detected", actor=user)
                            → 401, clear cookies
       expired            → 401
       user.is_active is False
                          → 401  ← this is what makes deactivation immediate
       issued before user.password_changed_at
                          → 401
3.  Rotate: new jti, same family_id, parent_jti = old jti
            old row: revoked_at = now, reason = "rotated", replaced_by_jti = new jti
4.  Issue new access + refresh; update last_seen_at
5.  204 + new cookies
```

⚠️ **Steps 2–3 must be one atomic read-modify-write**, or two simultaneous refreshes both read a
live row and both rotate it. Take a row lock (`select_for_update()`) on the session row.
**SQLite has no row locks** — it serialises writes at the database level instead, which happens to
produce the right answer locally while proving nothing about Postgres. Write the lock anyway, and
treat the grace window (A23) as the mechanism that actually has to hold.
```
```

> **Why rotation with a family, rather than a long-lived refresh token:** a stolen refresh token is
> indistinguishable from the real one — until both are used. Rotation guarantees a second use, and
> the family is what lets that second use revoke the whole chain. This is the single highest-value
> mechanism in this chapter, and it is the one most often left out.

### 6.4 Every authenticated request

`users.authentication.CookieJWTAuthentication`:

```
1. Read dbx_access cookie (fall back to Authorization: Bearer for machine callers)
2. Decode + verify signature and expiry            → 401 on failure
3. Load user; reject if not is_active              → 401
4. Confirm the session row is live (cached 60s):
     - revoked_at IS NULL
     - not expired
     - issued_at >= user.password_changed_at
5. Attach request.user and request.auth_session
```

⚠️ **Step 4 is what makes revocation real**, and it is the step that costs a query. Mitigation: the
session-liveness answer is cached for **60 seconds** per `jti`. **A revoked session therefore stops
working within 60 seconds, not instantly** — that is the deliberate trade, and it is written here
so nobody "optimises" the check away later believing it was free.

⚠️ **And the cache has to be shared** (A19). On `LocMemCache` the 60-second window is *per worker*,
so a four-worker deployment revokes a session in one of them and keeps honouring it in the other
three. See Ch. 17.4.

**Every authenticated response carries `Cache-Control: no-store`.** `/api/auth/me/` returns an
identity and a permission list; a shared proxy, a CDN or a browser's back-forward cache holding
that and handing it to the next person is a real leak and a cheap one to prevent. Set it once, in
middleware, for any response produced by an authenticated request.

### 6.5 Logout — `POST /api/auth/logout/`

Revokes **the current session row only** (`reason="logout"`), clears all three cookies, audits.
`POST /api/auth/sessions/revoke-all/` revokes every row for the user except the current one — the
"sign out everywhere" the `Session` table exists for.

### 6.6 Password reset — two endpoints

`POST /api/auth/password/forgot/` — **always answers `204`**, whether or not the address exists.
Throttled at **3/hour per identifier**. When the address exists and the account is active: create a
`PasswordResetToken` (30 min), email the plaintext token.

`POST /api/auth/password/reset/` — validates hash, expiry and `used_at IS NULL`; sets the password;
marks the token used; **invalidates every other outstanding token for that user**; and triggers 6.7.

### 6.7 Password change cascades

On any password change — reset, self-service, or admin:

```
user.password_changed_at = now()
sessions.revoke_all(user, reason="password_changed")   # every session, including the current one
log_activity("auth.password_changed", actor=user)
```

> **A password change that leaves old sessions alive has not ended the compromise it was performed
> to end.** This is the most commonly missed cascade in auth systems, which is why it is its own
> section rather than a bullet.

### 6.8 MFA (A16)

| Endpoint | Does |
|---|---|
| `POST /api/auth/mfa/setup/` | Creates an **unconfirmed** `MfaDevice`, returns the provisioning URI + QR payload |
| `POST /api/auth/mfa/confirm/` | Verifies a TOTP code, sets `confirmed_at`, returns **10 recovery codes, shown once** |
| `POST /api/auth/mfa/verify/` | Exchanges the login flow's `mfa_token` + code for a real token pair |
| `POST /api/auth/mfa/disable/` | **Requires recent re-auth** (Ch. 6.9). Audited as `auth.mfa_disabled` |

Only `confirmed_at IS NOT NULL` devices count. A role with `mfa_required=True` sets
`user.mfa_enforced`, and an enforced user with no confirmed device is routed to setup and **cannot
reach any other endpoint** until enrolled — every other endpoint answers `403` with
`code: "mfa_enrollment_required"`, which the frontend routes on. The enrolment endpoints and
`logout` are the only exceptions, or the user is locked out of fixing it.

**`mfa_token`, specified.** A signed token, **not** a session: payload `(user_id, purpose="mfa",
nonce)`, 5-minute expiry, single use (the nonce is burned in the cache on verify), returned in the
**body** rather than a cookie because it authorises exactly one call and nothing else. It grants no
access to any other endpoint. Holding one is not being logged in.

**Verification rules — a 6-digit code is only 10⁶ wide, so these are the control:**

| Rule | Why |
|---|---|
| Accept **±1 time step** only (30s steps → a 90s window) | Wider is a real weakening; narrower fails on ordinary clock drift |
| A code whose time step `<= device.last_used_timestep` is **refused** | Otherwise a code is replayable for the rest of its window — the shoulder-surf and the intercepted-SMS-style case |
| On success, set `last_used_timestep` to the accepted step | This is what makes the rule above monotonic |
| **Its own throttle**, `mfa_verify`, at `5/min` keyed on the `mfa_token` | The shared `10/min` across four MFA endpoints is not a brute-force control |
| A failed verify writes `LoginAttempt(succeeded=False, failure_reason="mfa_failed")` and counts toward lockout | The column already lists that reason; nothing was writing it |
| Recovery codes go through the **same** throttle and lockout | They are longer, but they are still guessable and they are single-use |

> **Disabling MFA is the security-relevant half of the pair** — it is what an attacker does after
> taking an account over. It is gated behind re-auth and shouted in the audit log.

### 6.9 Re-authentication (A18)

```python
class RequiresRecentAuth(BasePermission):
    """Sensitive action: the password must have been confirmed recently."""
    action_key: str            # e.g. "mfa_disable", "role_grant", "user_delete"
```

- **Off by default.** `core_setting` key `security.reauth.<action_key>`, default `False`. Installing
  this changes no behaviour until an operator opts a specific action in — *"a security control that
  breaks flows on install gets reverted."*
- Window from `security.reauth.window_minutes`, default **15**
- Reads `users_user_session.password_confirmed_at` — **per session**, so confirming on a laptop does
  not unlock the action on a phone
- **Returns `423 Locked`**, not 401 or 403. The client must distinguish *not authenticated* from
  *not permitted* from **re-confirm and retry**
- `POST /api/auth/password/confirm/` sets `password_confirmed_at`

---

## 7. Authorization — the engine

### 7.1 The catalog is code (A6)

`rbac/catalog.py` defines the shape; **each app declares its own**:

```python
# rbac/catalog.py
@dataclass(frozen=True)
class PermissionSpec:
    code: str        # "<module>.<feature>.<action>"
    label: str

@dataclass(frozen=True)
class PermissionGroupSpec:
    code: str
    label: str
    module: str
    order: int = 100
    permissions: tuple[PermissionSpec, ...] = ()
```

```python
# users/permissions.py — a module's declaration
GROUP = PermissionGroupSpec(
    code="users", label="Users & Access", module="users", order=10,
    permissions=(
        PermissionSpec("users.users.view",       "View users"),
        PermissionSpec("users.users.create",     "Create users"),
        PermissionSpec("users.users.update",     "Update users"),
        PermissionSpec("users.users.deactivate", "Activate / deactivate users"),
        PermissionSpec("users.users.export",     "Export users"),
        PermissionSpec("users.invitations.send", "Invite users"),
        PermissionSpec("users.sessions.revoke",  "Revoke another user's sessions"),
    ),
)
```

**The action vocabulary.** Narrow actions on purpose: `status` must not imply `update`, and `export`
is its own right because data egress is its own risk:

| Action | Means | Does **not** mean |
|---|---|---|
| `view` | Read the list and detail | — |
| `create` | Add a row | — |
| `update` | Edit fields | Change active state |
| `delete` | Remove a row | — |
| `deactivate` | Toggle active state | Edit anything else |
| `export` | Download / print | `view` implies this |
| `manage` | Broad admin right on a non-CRUD tool | Anything outside that tool |

### 7.2 Registration — by discovery, not enumeration

```python
# users/apps.py
class UsersConfig(AppConfig):
    name = "users"

    def ready(self) -> None:
        from core.registry import registry
        from .permissions import GROUP
        registry.permissions.register(GROUP)
```

`core/registry.py` — boot-time, one-way, **read-only after `ready()` completes**:

```python
class PermissionRegistry:
    def register(self, group: PermissionGroupSpec) -> None: ...
    def groups(self) -> tuple[PermissionGroupSpec, ...]: ...
    def codes(self) -> frozenset[str]: ...
    def seal(self) -> None: ...      # called after app loading; later register() raises
```

> ⚠️ **`seal()` has no obvious caller, and this is a real implementation question, not a detail.**
> Django has no "all apps are ready" hook — the last `AppConfig.ready()` to run is only the last by
> accident of `INSTALLED_APPS` ordering, and a plugin appended at the end (Phase 3 does exactly
> that) changes which one it is.
>
> **Seal lazily on first read.** The first call to `codes()` or `groups()` freezes the catalog and
> every later `register()` raises. Nothing has to know when boot finished, and the system checks —
> which run after `django.setup()` and read the catalog — are what force the seal in practice on
> every `manage.py` invocation.

> ⚠️ **Duplicate codes are a hard error at boot**, not a last-write-wins merge. Because codes are
> module-scoped (A7), a collision means two modules claimed the same module name — which is a real
> conflict. Requiring codenames to be **globally unique across all apps** would couple otherwise
> independent plugins; module scoping removes that coupling.
>
> ⚠️ **A plugin that fails to import contributes no permissions and is reported** — it does not take
> the boot down. But **only `ImportError` is swallowed**; any
> other exception inside a present module propagates, so real bugs are not masked.

### 7.3 Seeding — `rbac/seeding.py`

```python
def sync_catalog() -> SyncReport:
    """Project the code catalog onto the database. Idempotent. NEVER deletes."""
```

| Case | Action |
|---|---|
| Code in catalog, not in DB | Create `Permission` (+ `PermissionGroup` if needed) |
| Code in both | Update `label`, `group`, `order`; clear `is_deprecated` |
| Code in DB, not in catalog | **Mark `is_deprecated=True`.** Never delete — it would cascade away real grants |
| Group empty after sync | Left alone; the doctor reports it |

Runs via `manage.py seed_permissions`, and in a `post_migrate` signal so a fresh database is usable
immediately. **Running it twice changes nothing** — asserted by a test (Ch. 14).

### 7.4 The backend — how `has_perm` gets answered (A9)

```python
# rbac/backends.py
class RBACBackend(BaseBackend):
    def has_perm(self, user, perm, obj=None) -> bool:
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser:
            audit.superuser_bypass(user, perm)     # ⭐ never silent (A12)
            return True
        return perm in self.get_permission_codes(user)

    def get_permission_codes(self, user) -> frozenset[str]:
        """Union of the user's roles' permissions. Cached per request, then per user."""
```

> ⚠️ **That audit line never runs unless `User` overrides `has_perm`, and A12 is worthless without
> it.** `PermissionsMixin.has_perm` — which a custom user model inherits — begins:
>
> ```python
> # django/contrib/auth/models.py
> def has_perm(self, perm, obj=None):
>     # Active superusers have all permissions.
>     if self.is_active and self.is_superuser:
>         return True
>     return _user_has_perm(self, perm, obj)
> ```
>
> **An active superuser is answered `True` before a single backend is consulted.** So
> `RBACBackend.has_perm` is dead code for precisely the one class of user whose bypass we promised
> to record, and `authz.superuser_bypass` (§ 3.12) would never be written — while Ch. 9.5 claims it
> always is. A guarantee that is silently false is worse than one never made, because the empty
> audit log reads as "no bypasses happened".
>
> **`users.User` therefore overrides `has_perm` to delegate straight to the backends**, and
> `RBACBackend` owns the superuser decision *and* its audit row:
>
> ```python
> # users/models/user.py
> class User(AbstractBaseUser, PermissionsMixin):
>     def has_perm(self, perm, obj=None):
>         # NOT super(): PermissionsMixin short-circuits superusers before any backend
>         # runs, which would make the A12 audit trail permanently empty.
>         from django.contrib.auth.models import _user_has_perm
>         return _user_has_perm(self, perm, obj)
> ```
>
> A test asserts it: **a superuser hitting a gated endpoint writes exactly one
> `authz.superuser_bypass` row.** Without that test the override is one refactor away from being
> "simplified" back to `super()`.

**Caching, because this is the hottest path in the system:**

| Layer | Key | TTL | Invalidated by |
|---|---|---|---|
| Request-local | `request._perm_cache` | one request | — |
| Shared cache | `rbac:perms:<user_id>:<version>` | 10 min | version bump |

`version` is a counter in the cache, bumped by `rbac.services` on **any** grant change, role edit or
assignment change. **Bumping the version invalidates every user at once**, which is correct: a role
edit changes many users' effective permissions, and enumerating them is slower and easy to get
wrong.

> ⚠️ **A permission change must never require a deploy or a restart to take effect.** If you find
> yourself caching without an invalidation path, you have built exactly the bug the doctor exists to
> find.

### 7.4a `AUTHENTICATION_BACKENDS` — two jobs, and only one grant path

```python
AUTHENTICATION_BACKENDS = [
    "rbac.backends.RBACBackend",                                 # answers has_perm, grants nothing else
    "django.contrib.auth.backends.AllowAllUsersModelBackend",    # authenticates credentials (Ch. 6.2)
]
```

> ⚠️ **`user.has_perm` returns `True` if *any* backend says yes.** `AllowAllUsersModelBackend`
> inherits `ModelBackend`'s permission machinery, so it will happily grant anything written into
> `auth_permission` / `auth_group` — tables we never use, but which the Django admin offers a full
> editing UI for (Ch. 20). Today they are empty and nothing asserts that they stay empty.
>
> **`dbx.E006` asserts it at boot**: no backend other than `RBACBackend` may contribute permissions.
> Satisfy it by subclassing the authentication backend with `get_all_permissions` returning
> `set()`. One grant path (§ 4) is a property worth a boot check, not a hope.

### 7.5 Layer 1 — entity permission

```python
# core/permissions.py
class HasPermission(BasePermission):
    """Requires every code in the view's required_permissions for this action."""
```

Attached **declaratively** on the viewset, never as a call inside the method (Ch. 9.1). It calls
`request.user.has_perm(code)` and nothing else — `core` stays ignorant of `rbac`.

### 7.6 Layer 2 — object scoping (A13)

**Mandatory on every listable model**, per [`DATA_MODEL.md`](DATA_MODEL.md) § 5:

```python
# core/querysets.py
class VisibleToQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Rows this user may see. MUST fail closed: unknown → self.none()."""
        raise NotImplementedError(
            f"{self.model.__name__} must implement visible_to(). "
            "Returning .all() is a decision; make it explicitly."
        )
```

```python
# the only correct shape for get_queryset
def get_queryset(self):
    return User.objects.visible_to(self.request.user)
```

| Rule | Consequence |
|---|---|
| A queryset with no `visible_to` raises `NotImplementedError` at first use | You cannot forget by omission |
| No rule for this user → `.none()`, **never** `.all()` | Default-deny, always |
| Detail routes resolve **through the scoped queryset**, never by bare `pk` | An invisible row 404s, which is correct (`API_DESIGN.md`) |

**`User.visible_to` — the one this core has to ship**, because § 10.2 lists `GET /api/users/` and
`UserQuerySet` is the first thing `dbx.E003` will look at:

```python
# users/models/user.py
class UserQuerySet(VisibleToQuerySet):
    def visible_to(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_superuser or user.has_perm("users.users.view"):
            return self.all()
        return self.filter(pk=user.pk)          # you can always see yourself
```

The last line is the part worth arguing: `/api/auth/me/` and the account screen must work for
someone holding no permissions at all, and routing them through a *different* queryset would be a
second path (§ 4). One rule, and the weakest case is the default.

> ⚠️ **Layer 1 alone is the classic RBAC bug.** `users.users.update` says a user may edit *users*;
> it does not say they may edit *this* user. **Shipping only Layer 1 is the common shape** — and a
> scaffolded object-permission layer that nobody ever implements is worse than none, because it
> reads as though the check exists.

---

## 8. RBAC — roles and seeding

### 8.1 The two system roles, and only two

| Slug | Name | Holds | `is_system` | `is_elevated` |
|---|---|---|---|---|
| `administrator` | Administrator | **Every** permission in the catalog, recomputed on each seed | ✔ | ✔ |
| `staff` | Staff | **Nothing.** The safe default for a new account | ✔ | ✗ |

**Products add their own.** `RBAC_DESIGN.md` § "Seeded roles" already argues this: a core role a
product does not want is a role they have to explain to their users.

> ⚠️ **Two naming traps, both already half-sprung.**
> **The slug is `administrator`, not `admin`** — `RBAC_DESIGN.md` said `admin` and this said
> `administrator`, which is one seeder and two specifications. `administrator` wins, and
> `RBAC_DESIGN.md` has been corrected; `admin` also reads as "the Django admin", which is a
> different thing entirely (Ch. 20).
> **The `staff` role is not `User.is_staff`.** The role grants nothing. The boolean grants Django
> admin access, which is *full trust*. They will be confused for each other on sight, so § 3.1's
> "Django admin access only, **not** an authorization concept" is load-bearing and the roles screen
> never displays `is_staff`.
> **And `staff` holds nothing, not "read everything".** `RBAC_DESIGN.md` said the latter; a default
> role that can read every row in the system is not a safe default, it is the object-scoping bug
> with a friendly name.

- `is_system` roles **cannot be renamed or deleted** — enforced in `rbac.services`, and asserted by
  a test
- **`administrator` is recomputed on every seed**, so a new plugin's permissions reach the admin
  role automatically
- `staff` grants nothing. An invited user can log in and see the shell, and nothing else, until
  someone grants them a role

### 8.2 The elevated-role guard

> **Only a superuser may grant or revoke a role marked `is_elevated`.**

Without it, anyone holding `rbac.roles.assign` can grant themselves `administrator` — a one-step
privilege escalation that looks like ordinary use. Enforced in `rbac.services.assign_role()`, not in
the view, so the management command and the admin cannot bypass it.

### 8.3 Last-superuser guard

`rbac.services` refuses to remove the last `is_superuser` account, and `users.services` refuses to
deactivate it. **A system with no superuser cannot grant anyone the right to fix it.** This guard
is normally written the day after someone has already locked themselves out.

### 8.4 Service signatures — every mutation goes through one of these

```python
# rbac/services.py  — the ONLY writers to rbac_* tables
def create_role(*, actor, name, slug, description="", permission_codes) -> Role
def update_role(*, actor, role, **fields) -> Role                 # refuses is_system rename
def delete_role(*, actor, role) -> None                           # refuses is_system; PROTECT does the rest
def set_grants(*, actor, role, permission_codes) -> GrantDiff     # returns added/removed, audits both
def assign_role(*, actor, user, role) -> UserRole                 # elevated guard
def revoke_role(*, actor, user, role) -> None                     # last-superuser guard
```

Every one: `@transaction.atomic`, bumps the permission cache version, writes an `ActivityLog` row.
**`set_grants` returns a diff rather than a bare success**, because "role widened" is the event
worth auditing, not "role saved".

### 8.5 Two cascades the service layer owns

**`mfa_enforced` is derived, so it has to be recomputed.** § 6.8 says a role with
`mfa_required=True` sets `user.mfa_enforced`, and then nothing says what un-sets it. Revoke that
role and the user stays locked into MFA forever with no way to explain why; toggle `mfa_required`
on a role held by 200 people and none of them change. It is a derived value being written as
though it were stored state.

```python
def recompute_mfa_enforcement(user) -> None:
    """MUST run in assign_role, revoke_role and update_role. Derived, never assumed."""
    user.mfa_enforced = user.user_roles.filter(role__mfa_required=True).exists()
```

**Deactivating a user must revoke their sessions**, the same way a password change does (§ 6.7).
Without it the rows keep `revoked_at IS NULL`, so the sessions screen shows live sessions for a
disabled account and "revoke all" and "deactivate" mean different things for no reason a user could
guess. Access already stops — the refresh path 401s and the liveness cache expires within 60s — but
*the record is wrong*, and the record is what an incident is reconstructed from.

```python
# users/services/users.py
def deactivate(*, actor, user, reason) -> None:
    # ... last-superuser guard (§ 8.3) ...
    sessions.revoke_all(user, reason="admin")
    log_activity("users.user.deactivated", actor=actor, target=user, meta={"reason": reason})
```

---

## 9. The fail-closed machinery

**⭐ This chapter is what holds the rest of the design up.**

**The failure this chapter exists to make impossible:**

> An endpoint whose author forgot to attach a permission is reachable by any authenticated user,
> and neither review nor test coverage reliably catches it.

It escapes notice because it is not *visible*: the code reads exactly like working code, and the
symptom only appears when someone who should not have access goes looking. The asymmetry is what
makes it durable — a gate that wrongly **denies** is reported by the blocked user within days; a
gate that is **missing** is reported by nobody.

Four mechanisms, each catching it at a different moment. **All four are cheap only because the
route→permission link is explicit** (A14). Where that link is reconstructed from names or metadata,
none of them is available, and the best available substitute is a runtime auditor that has to guess
the same way the resolver does.

### 9.1 At write time — the declarative gate

```python
# core/api/viewsets.py
class BaseViewSet(viewsets.GenericViewSet):
    """Every API viewset inherits this. There is no other base."""

    required_permissions: ClassVar[dict[str, list[str]] | None] = None
    permission_classes = [IsAuthenticated, HasPermission]

    # A public endpoint must say so, in one obvious place:
    public: ClassVar[bool] = False
```

```python
class UserViewSet(BaseViewSet, mixins.ListModelMixin, ...):
    required_permissions = {
        "list":       ["users.users.view"],
        "retrieve":   ["users.users.view"],
        "create":     ["users.users.create"],
        "partial_update": ["users.users.update"],
        "deactivate": ["users.users.deactivate"],
    }

    def get_queryset(self):
        return User.objects.visible_to(self.request.user)
```

| Property | Effect |
|---|---|
| `required_permissions` is `None` **and** `public` is `False` | `HasPermission` **denies everyone** |
| An action missing from the dict | Denies — not "falls back to the default" |
| `public = True` | Allowed, and **the boot check requires a `# public: <reason>` comment** |

**And the same gate for endpoints that are not viewsets.** Every endpoint in § 10.1 — `login`,
`logout`, `refresh`, `me`, `password/*`, `mfa/*` — is an `APIView`, not a viewset. They have no
`action`, so they cannot carry a `required_permissions` **dict**, and a gate that only reaches
viewsets would leave the entire authentication surface undeclared and invisible to `dbx.E001`:

```python
# core/api/views.py
class BaseAPIView(APIView):
    """Every non-viewset API endpoint inherits this. There is no other base."""

    required_permissions: ClassVar[list[str] | None] = None   # flat: no actions to key on
    public: ClassVar[bool] = False
    permission_classes = [IsAuthenticated, HasPermission]
```

Same rule, same default: `None` and not `public` denies. `dbx.E001` accepts either base and
recognises the two shapes.

**`BaseViewSet` also carries the allow-lists, empty.** `API_DESIGN.md` § Filtering requires that
ordering and filter fields be allow-listed, and `SECURITY.md` gives the canonical example —
`?ordering=password`, or a filter traversing a relation into rows the caller cannot see. A rule
stated in a document is enforced by whoever remembers it; a rule that is an empty tuple on the base
class is enforced by the default:

```python
    filterset_fields: ClassVar[tuple[str, ...]] = ()     # opt in, per field
    ordering_fields:  ClassVar[tuple[str, ...]] = ()     # empty = no client-controlled ordering
    max_page_size:    ClassVar[int] = 100
```

Same inversion as `required_permissions`: **forgetting closes the door rather than opening it.**

> **Compare the usual shape:** `require(request, "server", "update")` called as the first line of
> the handler. Omit the line and the view serves. Here, omission is denial. **The failure mode is
> inverted** — and that is the whole point of A14.

### 9.2 At boot — Django system checks (`core/checks.py`)

These run in `manage.py check`, which is **already in the `AGENTS.md` § 2 gate** — so they fail
before any test executes, on every developer's machine, on every run.

| Id | Level | Check |
|---|---|---|
| `dbx.E001` | **Error** | Every route under `/api/` resolves to a view that is either `public=True` or declares `required_permissions` for every action it exposes |
| `dbx.E002` | **Error** | Every code in every `required_permissions` **exists in the registry catalog**. A typo is a boot failure, not a silent permanent denial |
| `dbx.E003` | **Error** | Every model reachable from a list endpoint implements `visible_to()` |
| `dbx.E004` | **Error** | `DEFAULT_PERMISSION_CLASSES` still contains the default-deny class — nobody loosened the global default |
| `dbx.E005` | **Error** | The cache backend is per-process (`LocMem`/`Dummy`) while `DEBUG=False` — A19, Ch. 17.4 |
| `dbx.E006` | **Error** | A backend other than `RBACBackend` can contribute permissions — § 7.4a |
| `dbx.E007` | **Error** | A `PUBLIC_ROUTES` entry names a route that no longer exists, or carries no reason |
| `dbx.E008` | **Error** | `DEBUG=False` with `AUTH_COOKIE_SECURE=False`, or no `SameSite` on the auth cookies |
| `dbx.W001` | Warning | A permission in the catalog is granted to no role |
| `dbx.W002` | Warning | A `PermissionGroup` has no permissions |
| `dbx.W003` | Warning | `SECURE_PROXY_SSL_HEADER` is set while `TRUSTED_PROXY_COUNT` is `0` — A20 says these disagree |

**`dbx.E007` needs somewhere to look, so `PUBLIC_ROUTES` is a file, not a convention.**

```python
# core/routes.py — the exemption ledger. dbx.E001 and the route test read THIS.
PUBLIC_ROUTES: dict[str, str] = {
    "health":              "Liveness probe. Returns no data and reads nothing.",
    "schema":              "OpenAPI document. Served only when DEBUG or SCHEMA_PUBLIC.",
    "swagger-ui":          "Docs UI. Same condition as the schema.",
    "users:login":         "The front door. Throttled and lockout-guarded (Ch. 6.2).",
    "users:refresh":       "Authenticates by refresh cookie, not by access token.",
    "users:password-forgot": "Pre-authentication by definition. Always answers 204.",
    "users:password-reset":  "Authenticates by the reset token itself.",
    "users:invitation-accept": "Authenticates by the invitation token itself.",
}
```

Keys are URL **names**, so a renamed route fails the check instead of quietly losing its exemption.
Every value is a sentence a reviewer can disagree with. **The list only shrinks by argument** — an
addition is a PR that has to justify opening something to the internet, which is the whole point of
keeping it in one file rather than as an `AllowAny` scattered across eight views.

> ⚠️ `/api/schema/` and `/api/docs/` exist in `config/urls.py` **today** and are not viewsets. They
> are the first thing `dbx.E001` will fail on, and the reflex — an `AllowAny` on each — is exactly
> the pattern the check exists to prevent. They go in the ledger.

> **`dbx.E002` catches the most expensive failure in this whole area:** a route referencing a
> permission **that does not exist**. It denies everyone, permanently, while the grant looks correct
> on the roles screen — so the time is lost hunting a permissions bug that is really a typo. Here it
> cannot reach a deploy, because it cannot reach a passing `manage.py check`.

### 9.3 At test time — `tests/architecture/test_route_enforcement.py`

Already specified as `BUILD_ORDER` task `2.2`:

```
Walk Django's URL resolver for EVERY route under /api/.
Call each one unauthenticated.
Fail on anything that is not 401 or 403.
⚠️ A 404 counts as a FAILURE — it means the handler ran a lookup before checking who was asking.
Exempt: the routes listed in PUBLIC_ROUTES, each with a written reason.
```

Plus `test_permission_codes.py`: every code referenced anywhere ↔ the catalog, both directions.

> **In a metadata-resolved model this test cannot be written**, because "every route resolves to a
> real permission" is not true there and cannot be made true — some routes legitimately resolve
> through a fallback. The assertion has to be narrowed until it proves almost nothing. **In an
> explicit model the clean assertion is simply available.** That is the argument for A14.

### 9.4 At runtime — `manage.py permissions_doctor`

Four checks that fail the command, three that only advise:

| Check | Severity |
|---|---|
| A `required_permissions` code missing from the catalog | **Failure** |
| A catalog code with no `Permission` row (seed never ran) | **Failure** |
| A `Permission` row marked `is_deprecated` that still holds grants | **Failure** |
| An `/api/` route with neither `required_permissions` nor `public` | **Failure** |
| A permission granted to no role | Advisory (`--all`) |
| A role holding no permissions | Advisory (`--all`) |
| An empty permission group | Advisory (`--all`) |

**Four rules for the command itself.** Each is a lesson about tooling, and each is easy to get
wrong in a way that makes the tool worse than useless:

1. **Delegate to the real enforcement code; never re-model it.** The doctor asks `HasPermission`
   and the registry the same question the request path asks. A doctor that models resolution a
   second time will eventually disagree with the first — and then it reports "healthy" over routes
   that are dead.
2. **Hard failures separate from advisory findings.** Failing a build over untidy-but-harmless
   configuration is how a check gets switched off, and a switched-off check protects nothing.
3. **Never report health over a known backlog.** If a `KNOWN_BROKEN` ledger is ever introduced, the
   command reports how many entries remain instead of "healthy" — **and the list may only shrink.**
   Adding an entry means shipping a broken route.
4. **Detect the ledger's own rot.** Report entries that are fixed or gone; otherwise the list
   silently becomes decoration and its count stops meaning anything.

**Error messages name the fix, not just the fault:** *"Route `users.list` requires permission
`users.users.view`, which is not in the catalog. Add it to the module's `PERMISSION GROUP`, or
correct the code on the viewset."*

### 9.5 The bypass is audited, never silent (A12)

Every `is_superuser` short-circuit writes `authz.superuser_bypass` with the permission code and the
route.

> **Why this matters more than it looks.** Picture a route that is misconfigured and denies every
> ordinary role. The one person who checks it before release is senior, holds the bypass, and sails
> straight through. The feature ships "working", and the breakage surfaces weeks later, reported by
> someone junior enough to hit the real path.
>
> **A bypass held by the people most likely to test a feature hides breakage from the people most
> able to fix it.** We keep one superuser flag — but it leaves a trail, so "it works for me" is
> checkable against what the log says was actually bypassed.

---

## 10. The API surface

All under `/api/`, trailing slash, per [`API_DESIGN.md`](API_DESIGN.md).

### 10.1 Authentication — `/api/auth/`

| Method | Path | Auth | Permission | Success | Throttle |
|---|---|---|---|---|---|
| `POST` | `login/` | ✗ public | — | `204` + cookies | 5/min per id+ip |
| `POST` | `logout/` | ✔ | — | `204` | — |
| `POST` | `refresh/` | cookie | — | `204` + cookies | 60/min |
| `GET` | `me/` | ✔ | — | `200` user + **permission codes** | — |
| `POST` | `password/forgot/` | ✗ public | — | **always `204`** | 3/hour |
| `POST` | `password/reset/` | ✗ public | — | `204` | 5/hour |
| `POST` | `password/change/` | ✔ | — | `204` | — |
| `POST` | `password/confirm/` | ✔ | — | `204` (sets re-auth) | 5/min |
| `GET` | `sessions/` | ✔ | — | `200` own sessions | — |
| `DELETE` | `sessions/<public_id>/` | ✔ | — | `204` | — |
| `POST` | `sessions/revoke-all/` | ✔ | — | `204` | — |
| `POST` | `mfa/setup/` · `mfa/confirm/` · `mfa/verify/` · `mfa/disable/` | mixed | `mfa/disable` needs **re-auth** | — | 10/min |
| `POST` | `invitations/accept/` | ✗ public | — | `204` + cookies | 10/hour |

**`GET /api/auth/me/` — the shell's one round trip:**

```jsonc
{
  "id": "0f8c…",                       // public_id, never the integer PK
  "email": "person@example.com",
  "full_name": "Person Name",
  "is_superuser": false,
  "mfa_enabled": true,
  "roles": [{ "slug": "staff", "name": "Staff" }],
  "permissions": ["users.users.view", "rbac.roles.view"],
  "session": { "expires_at": "…", "password_confirmed_at": null }
}
```

⚠️ **`permissions` is for hiding UI only.** `RBAC_DESIGN.md` § Frontend: *hiding a button is a
courtesy, not a control.* Every one of these codes is re-checked server-side on every call.

### 10.2 Users — `/api/users/`

| Method | Path | Permission |
|---|---|---|
| `GET` | `users/` | `users.users.view` |
| `POST` | `users/` | `users.users.create` |
| `GET` `PATCH` | `users/<public_id>/` | `users.users.view` / `users.users.update` |
| `POST` | `users/<public_id>/deactivate/` | `users.users.deactivate` |
| `POST` | `users/<public_id>/sessions/revoke/` | `users.sessions.revoke` |
| `GET` `POST` | `invitations/` | `users.invitations.send` |
| `POST` | `invitations/<public_id>/revoke/` | `users.invitations.send` |

### 10.3 RBAC — `/api/rbac/`

| Method | Path | Permission |
|---|---|---|
| `GET` | `permissions/` | `rbac.permissions.view` — the catalog, grouped, for the roles screen |
| `GET` `POST` | `roles/` | `rbac.roles.view` / `rbac.roles.create` |
| `GET` `PATCH` `DELETE` | `roles/<public_id>/` | `rbac.roles.view` / `.update` / `.delete` |
| `PUT` | `roles/<public_id>/permissions/` | `rbac.roles.update` — **full replacement**, returns the diff |
| `POST` `DELETE` | `users/<public_id>/roles/` | `rbac.roles.assign` — **+ superuser for elevated roles** |

---

## 11. The frontend contract

```ts
// src/lib/api.ts — the ONLY place fetch() is called (AGENTS.md § 3)
//  · credentials: "include" on every request
//  · X-CSRF-Token header read from the dbx_csrf cookie on unsafe methods
//  · on 401: attempt ONE refresh, replay the request, then redirect to /login
//  · on 423: raise ReauthRequired — the caller shows the confirm-password modal
//  · normalises the { error: { code, message, fields } } shape into a typed error
```

```ts
// src/lib/permissions.ts
export function can(code: string): boolean
export function canAny(codes: string[]): boolean
export function isSuperuser(): boolean
```

```tsx
// usage
const { can } = usePermissions();
{can("users.users.create") && <CreateUserButton />}
```

**The affordance-parity rule.** The bug it prevents: row actions all gated on one blunt
"can manage" flag, so an add-only operator is shown Edit and Delete buttons that can only 403, while
an update-only operator is refused an edit they are entitled to make.

> **A UI affordance must be gated on exactly the permission its own endpoint enforces.** Not a
> broader "can manage" flag. A test asserts this pairing for every gated affordance.

**Single-flight refresh:** concurrent 401s must trigger **one** refresh, not one per request — a
dashboard firing six parallel calls would otherwise rotate the token six times and trip its own
reuse detection, logging the user out. `api.ts` holds a module-level promise.

---

## 12. Settings

```python
# config/settings.py
AUTH_USER_MODEL = "users.User"                       # ⚠️ before the first migration

AUTHENTICATION_BACKENDS = [
    "rbac.backends.RBACBackend",                     # answers has_perm
    "django.contrib.auth.backends.ModelBackend",     # authenticates credentials
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["users.authentication.CookieJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["core.permissions.DefaultDeny"],   # ⚠️ dbx.E004 guards this
    "DEFAULT_PAGINATION_CLASS": "core.api.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "core.api.exceptions.handler",
    "DEFAULT_THROTTLE_RATES": {
        "login": "5/min", "password_reset": "3/hour", "mfa": "10/min",
        "mfa_verify": "5/min", "refresh": "60/min",
    },
}

# ⚠️ Correctness, not performance (A19, Ch. 17.4). Every throttle above, the permission-version
# counter and the session-liveness window live here. LocMem makes all three per-worker.
CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://")}

# ⚠️ Ch. 17.3. 0 = trust REMOTE_ADDR. Anything else counts from the RIGHT of X-Forwarded-For.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)

# ⚠️ Ch. 20. The admin is a second auth system; it is not mounted unless this is on.
ADMIN_ENABLED = env.bool("ADMIN_ENABLED", default=DEBUG)

# ⚠️ Ch. 18. Console in dev so a missing SMTP config is not a silent failure.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@example.com")
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:3000")

# Argon2 first. Django's default is PBKDF2; Argon2 is the better answer and costs one dependency.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
```

| Env var | Default | Purpose |
|---|---|---|
| `JWT_SIGNING_KEY` | — | **Separate from `SECRET_KEY`.** Rotating one must not invalidate the other |
| `ACCESS_TOKEN_LIFETIME` | `600` | Seconds |
| `REFRESH_TOKEN_LIFETIME` | `1209600` | 14 days absolute |
| `REFRESH_IDLE_LIFETIME` | `604800` | 7 days since `last_seen_at` |
| `AUTH_COOKIE_DOMAIN` | `""` | |
| `AUTH_COOKIE_SECURE` | `not DEBUG` | ⚠️ Never hard-code `False` |
| `MFA_ENCRYPTION_KEY` | — | Encrypts `MfaDevice.secret` |
| `LOCKOUT_THRESHOLD` / `LOCKOUT_WINDOW` / `LOCKOUT_DURATION` | `10` / `900` / `900` | Progressive lockout |
| `SESSION_LIVENESS_CACHE_TTL` | `60` | ⚠️ The revocation-latency trade (Ch. 6.4) |
| `JWT_SIGNING_KEY_FALLBACKS` | `[]` | **Verify-only.** The overlap window that makes key rotation possible (Ch. 19.3) |
| `REFRESH_ROTATION_GRACE` | `15` | Seconds. ⚠️ The two-tab fix (A23). `0` disables it and will log people out |
| `CACHE_URL` | `locmemcache://` | ⚠️ **Must be shared in production** — `dbx.E005` (Ch. 17.4) |
| `TRUSTED_PROXY_COUNT` | `0` | ⚠️ Proxies in front of the app. Wrong ⇒ per-IP lockout is global (Ch. 17.3) |
| `ADMIN_ENABLED` | `DEBUG` | ⚠️ Mounts `/admin/` — a second auth system (Ch. 20) |
| `EMAIL_BACKEND` / `DEFAULT_FROM_EMAIL` | console / — | Reset and invitation delivery (Ch. 18) |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Where emailed links point. **Never taken from the `Host` header** |
| `MAX_SESSIONS_PER_USER` | `10` | Oldest is revoked past the cap (Ch. 19.2) |
| `LOGIN_ATTEMPT_RETENTION_DAYS` | `90` | Used by `auth_cleanup` |

**Per-product cookie names** — `dbx_access` derives from a slug setting, so two products on sibling
subdomains do not overwrite each other's cookies. It is exactly the kind of detail a boilerplate
must get right, because a product built in a hurry never will.

> ⚠️ `settings.py` is a **protected file** (`AGENTS.md`). Every value above comes from `.env` via
> `django-environ` — **never a hard-coded key, host or URL.**

---

## 13. Migration order

**This sequence cannot be reordered.** Getting it wrong means resetting the database.

| # | Migration | Why here |
|---|---|---|
| 1 | `users/0001_initial` — `User` **only** | ⚠️ **`AUTH_USER_MODEL` must exist before anything references it.** Swapping later is one of Django's genuinely painful migrations (`TECH_DEBT` **DB-10**) |
| 2 | `rbac/0001_initial` — `PermissionGroup`, `Permission`, `Role`, `RolePermission`, `UserRole` | References `AUTH_USER_MODEL`, so it follows |
| 3 | `users/0002` — `UserSession`, `PasswordResetToken`, `MfaDevice`, `MfaRecoveryCode`, `LoginAttempt` | |
| 4 | `users/0003` — `Invitation` | FK → `rbac.Role`, so `rbac` must exist first |
| 5 | `core/0001_initial` — `Setting`, `ActivityLog` | `ActivityLog.actor` → user |
| 6 | `rbac/0002_seed_system_roles` — `RunPython`, idempotent, **reversible**. Creates the two **role rows only** | Data, after the schema |

> ⚠️ **Migration 6 cannot grant `administrator` its permissions, and the obvious version of it
> silently doesn't.** § 7.3 runs `sync_catalog()` from a `post_migrate` signal, which fires **after
> every migration has run**. At the moment the `RunPython` executes, `rbac_permission` is empty —
> so an `administrator` seeded "with every permission" is seeded with none, and stays that way
> until somebody notices the admin role is empty and re-runs a command by hand.
>
> **Split it.** The migration creates the role rows. The grant recomputation lives in the same
> `post_migrate` handler as `sync_catalog()`, **ordered after it**:
>
> ```python
> def on_post_migrate(sender, **kwargs):
>     report = sync_catalog()          # catalog → rbac_permission
>     ensure_system_roles()            # idempotent; rows may already exist from migration 6
>     recompute_administrator()        # only now is there anything to grant
> ```
>
> This also gets the property § 8.1 promises for free: a newly installed plugin's permissions reach
> `administrator` on the next `migrate`, with nobody remembering to do anything.

> ⚠️ **If decision A1 or A2 is reversed, stop and restart from migration 1.** There is no cheap
> path from "Django's user" to a custom one, or from username to email, once step 2 exists. This is
> why `BUILD_ORDER` puts both 🚧 decisions in Phase 0.

**After any model change:** `uv run python manage.py makemigrations --check --dry-run`
(`AGENTS.md` § 2 — *not optional*).

---

## 14. The test plan

Nothing here is done until these pass. Grouped by what they protect.

**Architecture — the ones most suites omit**

| Test | Asserts |
|---|---|
| `test_route_enforcement.py` | Every `/api/` route, unauthenticated → 401/403. **404 is a failure.** |
| `test_permission_codes.py` | Referenced codes ↔ catalog, both directions |
| `test_default_deny.py` | A viewset with no `required_permissions` denies a fully-permissioned non-superuser |
| `test_visible_to_required.py` | Every listable model implements `visible_to` |
| `test_public_routes.py` | Every `PUBLIC_ROUTES` key resolves; every entry has a reason; **the list has not grown** |
| `test_single_grant_path.py` | No backend but `RBACBackend` returns a permission (§ 7.4a) |

**Authentication**

Login round trip (anon 401 → login → recognised → logout → 401) · **wrong password, unknown address
and inactive account are byte-identical** · timing parity on unknown address · refresh rotates ·
**reused refresh revokes the whole family** · deactivation kills access within the cache TTL ·
password change revokes all sessions · reset token is single-use · lockout after N failures · MFA
required blocks every other endpoint until enrolled · re-auth returns **423** and expires.

**The ones added by the Ch. 16–20 review** — each is a defect the spec had, so each gets a test
that would have caught it:

| Test | Would have caught |
|---|---|
| A superuser hitting a gated route writes **exactly one** `authz.superuser_bypass` row | `PermissionsMixin.has_perm` short-circuiting every backend (§ 7.4) |
| An inactive user's failed login records `failure_reason="inactive"`, and the **response body is byte-identical** to a wrong password | `ModelBackend` collapsing both into `None` (§ 6.2) |
| **Two concurrent refreshes with the same token both succeed**, and the family survives | The two-tab logout (A23) |
| A refresh replayed **after** the grace window revokes the family | The grace window swallowing real theft |
| A TOTP code accepted once is refused the second time, inside the same 30s step | TOTP replay (§ 6.8) |
| `client_ip()` ignores `X-Forwarded-For` when `TRUSTED_PROXY_COUNT=0`, and takes the Nth-from-right when it is not | A spoofed header evading per-IP lockout (Ch. 17.3) |
| `migrate` on an empty database leaves `administrator` holding **every** catalog permission | The seed-ordering bug (Ch. 13) |
| `bootstrap_admin` twice creates one account and exits non-zero the second time | Ch. 19.1 |

**Authorization**

A role with zero permissions is refused by **every** gated endpoint (the single test `RBAC_DESIGN.md`
says catches most accidental openness) · permissions are the **union** of several roles · a code
absent from the catalog is denied **and logged** · `visible_to` with no rule returns `.none()` · a
detail route for an invisible row returns **404, not 403** · superuser bypass writes an audit row.

**RBAC service rules**

`sync_catalog()` twice changes nothing · a removed code becomes `is_deprecated`, not deleted · a
system role cannot be renamed or deleted · a non-superuser cannot grant an elevated role · the last
superuser cannot be demoted or deactivated · `set_grants` returns an accurate diff and audits both
sides.

**Frontend**

`can()` reflects `/me` · affordance-parity for every gated control · concurrent 401s trigger
**exactly one** refresh.

---

## 15. Build sequence

Mapped onto [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). **Each row is one PR.**

| Task | Chapters | Deliverable |
|---|---|---|
| `0.1` 🚧 | Ch. 1 A1–A3 | ADR: custom user, email identity, boolean states |
| `0.2` 🚧 | Ch. 1 A4–A5, Ch. 6 | ADR: cookie JWT + rotation + DB sessions |
| **`1.0`** | Ch. 16, 17 | ⚠️ **New, and it comes first.** Dependencies into `pyproject.toml`; `CACHES`, `TRUSTED_PROXY_COUNT`, `client_ip()`, the CORS/same-site settings. Nothing below builds without it |
| **`1.1a`** | Ch. 3.1, 5, 13 #1 | `users` app, `User` + manager, **migration 1**, admin |
| **`1.1b`** | Ch. 3.2–3.4, 6.1–6.5 | Tokens, `UserSession`, login/logout/refresh/me, cookies, CSRF |
| **`1.1c`** | Ch. 3.3, 6.6–6.7, A17 | Password reset, change cascade, throttling, lockout |
| **`1.1d`** | Ch. 3.5–3.6, 6.8–6.9 | Invitations, MFA, re-auth |
| **`1.2a`** | Ch. 7.1–7.3, 3.7–3.8 | Catalog, registry, `Permission`(+group), seeding |
| **`1.2b`** | Ch. 7.4–7.5, 3.9–3.11 | `RBACBackend`, cache, `HasPermission`, `Role`, grants |
| **`1.2c`** | Ch. 7.6 | `visible_to` contract + first implementation |
| **`1.3`** | Ch. 7.2 | The full registry seam (nav, settings, health) |
| **`1.4`** | Ch. 8, 10.3 | Roles API, system-role seeding, guards, roles screen **last** |
| **`1.5`** | Ch. 10.2, 11 | Users CRUD — the reference module |
| **`1.5b`** | Ch. 18, 19.1 | Email templates + delivery, `bootstrap_admin`. **`1.1c` cannot be demonstrated without this** |
| **`1.6`** | — | `core/` vs `project/` split |
| **`1.7`** | Ch. 19.2–19.3, 20 | `auth_cleanup`, key-rotation fallbacks, the admin decision |
| **`2.1`–`2.3`** | Ch. 9.2–9.4, 14 | ⚠️ **Pull `2.1` forward** — the checks and tests below are the deliverable, and they need a runner |

> ⚠️ **The Chapter 9 machinery is not a later hardening pass.** `BaseViewSet` (9.1) lands with
> `1.1a` — the first viewset must already inherit it, because retrofitting default-deny onto
> existing views means auditing every one of them. The system checks (9.2) land with `1.2a`, as soon
> as there is a catalog to check against. Only the doctor (9.4) can wait.

---

## 16. Runtime dependencies

**Chapters 1–15 specify a system that cannot currently be imported.** Verified against the
installed tree on 2026-09-21: there is no JWT library, no TOTP library, no encryption library, no
Argon2 and no cache client. `backend/pyproject.toml` lists five runtime dependencies and none of
them is in this chapter. A build spec that does not say what to install stalls on the first
`import`, so here it is — with the reason for each, because a dependency added without one is a
dependency nobody dares remove.

| Package | For | Why this one |
|---|---|---|
| `pyjwt>=2.10` | Encoding and verifying the access and refresh tokens | **Not** a JWT *framework*. Ch. 6 already owns rotation, families, revocation and the DB session row; a framework that also owns them means two implementations of the same rule, and the one that loses is whichever we forget we configured |
| `pyotp>=2.9` | TOTP verification (§ 6.8) | The reference implementation of RFC 6238. Writing this by hand is how the ±1-step window ends up as ±5 |
| `cryptography>=44` | Fernet encryption of `MfaDevice.secret` (§ 3.6) | § 3.6 says "encrypted at rest with a key from `.env`". This is the library that does it |
| `argon2-cffi>=23` | Password hashing | Django defaults to PBKDF2 and supports Argon2 the moment this is installed. One dependency, a materially better hash, and Django re-hashes on next login automatically |
| `redis>=5` | The shared cache (A19, Ch. 17.4) | Django 5.2 ships its own `RedisCache` backend, so this is the **client only** — no `django-redis`. Verified: `django/core/cache/backends/redis.py` exists in the installed tree |

**Deliberately not added:**

| Rejected | Instead |
|---|---|
| `djangorestframework-simplejwt` | Its value is the parts Ch. 6 replaces — its own rotation, its own blacklist app, its own settings surface. Keeping it would mean two session stores disagreeing about what "revoked" means |
| `qrcode` / `pillow` | `POST /api/auth/mfa/setup/` returns the `otpauth://` URI and the **frontend** renders the QR. Server-side image generation adds two dependencies and an image-handling attack surface to avoid one `npm` package |
| `django-redis` | Redundant since Django 4.0 |
| `django-ratelimit` | DRF's throttling is already configured and already in § 12. A second rate limiter is a second set of rules to reconcile |

> ⚠️ **`pyproject.toml` is a protected file** (`AGENTS.md`). These go in under explicit approval,
> and each new Django app also goes into `known-first-party` in the same edit — `TECH_DEBT` **DB-14**
> is exactly this being forgotten.

---

## 17. The deployment contract

**Four environment facts this design depends on and never stated.** Each one is invisible in
development and each one breaks the system in production — which is the worst combination, because
the failure arrives after the code has been declared finished.

### 17.1 The frontend and the API must be same-**site** (A21)

`SameSite=Lax` cookies are **not attached to cross-site XHR**. They are attached on same-site
requests and on top-level cross-site *navigations*, and that is all. So:

| Frontend | API | Same site? | Cookie auth works? |
|---|---|---|---|
| `localhost:3000` | `localhost:8000` | **yes** — ports are not part of a site | ✅ |
| `app.example.com` | `api.example.com` | **yes** — same registrable domain | ✅ |
| `app.example.com` | `api.example.net` | **no** | ❌ **silently** — every call is anonymous |

> ⚠️ **The dev/prod trap, precisely.** Development is two ports on `localhost`, which is same-site,
> so the whole scheme works perfectly on every developer's machine. Split the two halves across
> registrable domains at deploy time and every authenticated request arrives without a cookie,
> answers `401`, and the frontend renders its logged-out state. Nothing errors. Nothing logs.
>
> **This is a deployment constraint, not a preference:** ship both halves under one registrable
> domain. If a product genuinely cannot, the cookies must become `SameSite=None; Secure` — which
> gives up the cheapest CSRF defence there is and makes § 17.5's session-bound token the only thing
> standing between the product and cross-site request forgery. Record it as an ADR in that product,
> not as a quiet settings change.

### 17.2 CORS, exactly

`django-cors-headers` is installed and `config/settings.py` already sets `CORS_ALLOW_CREDENTIALS = True`.
With credentials in play the rules are stricter than the defaults suggest:

```python
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")   # exact origins, scheme included
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [*default_headers, "x-csrf-token"]   # § 6.1's header must be allowed through
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")
```

- **`CORS_ALLOW_ALL_ORIGINS = True` with credentials is not a loose setting, it is an open door.**
  The browser refuses `Access-Control-Allow-Origin: *` alongside credentials, so the library
  reflects the caller's origin instead — which means *every* site can make authenticated calls.
  `dbx.E008`'s sibling check refuses the combination outright.
- The response must `Vary: Origin`, or a shared cache serves one origin's CORS headers to another.
  The library does this; **do not cache `/api/` responses in front of it** (§ 6.4's `no-store`).
- `x-csrf-token` must be in the allow-list or every unsafe method fails preflight — and the symptom
  is a CORS error in the console, which reads like a configuration problem rather than the auth
  problem it is.

### 17.3 Client IP — `REMOTE_ADDR` is the proxy (A20)

§ 6.2 throttles per IP and A17 locks out per IP. Behind a load balancer, an ingress or a CDN,
`REMOTE_ADDR` is that device's address, identically for every user.

> ⚠️ **The failure is not a degraded control, it is an outage.** Every request shares one throttle
> key, so ten failed logins from one attacker crosses `LOCKOUT_THRESHOLD` for the whole install and
> **nobody can sign in for fifteen minutes.** The attacker repeats. Meanwhile the `ip` column on
> every `LoginAttempt` and every `ActivityLog` row records the proxy, so the forensic trail that was
> supposed to identify them says nothing.

```python
# core/http.py
def client_ip(request) -> str | None:
    """The caller's address, or None. NEVER trusts a header we have not been told to trust."""
    n = settings.TRUSTED_PROXY_COUNT
    if n <= 0:
        return request.META.get("REMOTE_ADDR")
    chain = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
    # Count from the RIGHT. The left of the chain is whatever the client wrote there.
    return chain[-n] if len(chain) >= n else request.META.get("REMOTE_ADDR")
```

**Counting from the right is the whole point.** `X-Forwarded-For` is append-only and
client-controlled at its head: a caller sending `X-Forwarded-For: 1.2.3.4` gets one free extra entry
on the left. Taking `chain[0]` — the version in most snippets — lets an attacker pick a new identity
per request and evade both throttling and lockout entirely. Taking the Nth from the right yields the
address your own outermost trusted proxy observed, which is the only entry in the chain you have any
reason to believe.

**Default `0`.** A core must be safe when nobody configured it, and trusting a header by default is
how this goes wrong everywhere it goes wrong. `dbx.W003` flags the configuration that says the app
is behind a proxy (`SECURE_PROXY_SSL_HEADER`) while `TRUSTED_PROXY_COUNT` still says it is not.

### 17.4 The cache is part of the security model (A19)

Three things in this design are correctness-critical and all three live in `django.core.cache`:

| What | Where | On `LocMemCache` with N workers |
|---|---|---|
| Permission version counter (§ 7.4) | `rbac:perms:*` | A revoked grant is invalidated in **one** worker. The others keep serving it for up to 10 minutes |
| Session liveness (§ 6.4) | per `jti`, 60s | "Revocation is immediate" becomes "immediate in 1 of N workers" |
| Every throttle and the lockout (§ 12, A17) | DRF throttle keys | `5/min` becomes `5N/min`; lockout counts never reach the threshold |

**Django's default cache is `LocMemCache`, which is per process.** Nothing in chapters 1–15 said
otherwise, so the honest reading of the spec as written is that all three controls quietly stop
working the moment the app is deployed the way anything is deployed.

`dbx.E005` refuses to boot with a per-process cache while `DEBUG=False`. **Redis therefore moves
into Phase 1**, where `BUILD_ORDER` currently has it in Phase 2 alongside Docker Compose — that
sequencing was written before anything depended on it for correctness.

### 17.5 Cookie hardening — prefixes, and a CSRF token that is bound to something (A22)

§ 6.1 specifies double-submit: a readable `dbx_csrf` cookie echoed in `X-CSRF-Token`. **Plain
double-submit assumes nobody else can set a cookie on your domain**, and on a shared parent domain
that assumption does not hold — anything on `other.example.com` can write a cookie scoped to
`.example.com`, then forge a request whose header matches the value it just planted.

Two changes, both cheap:

```
dbx_csrf   = base64( HMAC-SHA256(JWT_SIGNING_KEY, session.jti) )
```

1. **Bind the token to the session.** The server recomputes it from the `jti` in the access token and
   compares. A value an attacker planted does not match the *victim's* session, so planting it
   achieves nothing.
2. **Use the `__Host-` prefix** on all three cookies when no `AUTH_COOKIE_DOMAIN` is set —
   `__Host-dbx_access`, and so on. The browser then refuses any `Set-Cookie` for that name that
   carries a `Domain` attribute or a non-`/` path, which forecloses subdomain injection at the
   browser rather than in our code. It is incompatible with a shared cookie domain, so the setting
   picks the prefix: domain set ⇒ plain names, domain empty ⇒ `__Host-`.

> The refresh cookie's `Path=/api/auth/refresh/` (§ 6.1) is incompatible with `__Host-`, which
> requires `Path=/`. Keep the path scoping — it is the stronger control of the two for that cookie,
> because it bounds the blast radius of every other request — and apply `__Host-` to the access and
> CSRF cookies only. Stating the conflict here so the next reader does not "fix" one by deleting the
> other.

---

## 18. Outbound email

**Two flows in Ch. 6 send mail and nothing in chapters 1–15 configures any way to send it.**
Password reset (§ 6.6) and invitations (§ 3.5) are not optional extras — invitations are *the only
route to a new account*. As specified, neither can run.

| Setting | Dev | Production |
|---|---|---|
| `EMAIL_BACKEND` | `console.EmailBackend` | SMTP or a provider backend |
| `DEFAULT_FROM_EMAIL` | `no-reply@example.com` | the product's address |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | the product's frontend |

**Console in dev, deliberately.** A developer who never sees the token cannot test the flow, and the
alternative — a silently dropped mail — is the failure that gets diagnosed as "the reset endpoint is
broken".

> ⚠️ **`FRONTEND_BASE_URL` comes from settings and never from the request.** Building a reset link
> from the `Host` header is host-header injection: an attacker sends `Host: evil.example`, the victim
> receives a genuine email from the genuine product containing a genuine single-use token pointed at
> the attacker's server, and clicking it hands over the account. `ALLOWED_HOSTS` reduces this but the
> link builder must not depend on that being configured correctly.

**Two rules for the send itself:**

1. **The send is not in the transaction.** Create and commit the token row, then send via
   `transaction.on_commit()`. Sending inside the transaction means a rollback after a successful
   send leaves a live link to a token that does not exist; committing first at least fails safe.
2. **A delivery failure never changes the response.** § 6.6 says `POST /api/auth/password/forgot/`
   **always** answers `204`. A `500` on an SMTP error turns the endpoint back into the user-enumeration
   oracle the `204` exists to prevent — the address that errors is the address that exists. Catch,
   log, and answer `204`.

Templates live in `users/templates/users/email/`, one `.txt` and one `.html` per message. **The
plaintext part is not optional**: it is what a security-conscious recipient's client renders, and it
is what appears in the logs when someone is working out what was actually sent.

---

## 19. Bootstrap and operations

### 19.1 Account one (A25)

§ 3.1 defaults `is_active` to `False`. § 3.5 says invitations are "the only route to a new account",
and an invitation needs an `invited_by` and a `role_id`. **Read together, chapters 1–15 describe a
system that cannot produce its first user.** `createsuperuser` is mentioned once, in an aside, and
it creates an account holding no role.

```
manage.py bootstrap_admin --email <address>       # password prompted, never an argument
```

| Rule | Why |
|---|---|
| **Refuses if any user row exists**, exit code 1 | Otherwise it is a permanent unauthenticated-escalation tool sitting in every product copied from this core |
| Creates `is_active=True`, `is_superuser=True`, `is_staff=True` | Account one must be able to fix everything, including itself |
| Assigns the `administrator` role as well as the flag | So the role path is exercised from the first day rather than hidden behind the bypass until someone else joins |
| Runs `sync_catalog()` first if the catalog is empty | It cannot assign a role holding permissions that were never seeded |
| Writes `ActivityLog` with `actor=NULL`, verb `users.user.bootstrapped` | The one account nobody created still has a creation record |
| **Never takes the password as an argument** | A password in `--password` is in the shell history, the process list and the CI log |

`scripts/setup.sh` (`BUILD_ORDER` 4.1) calls it after `migrate`.

### 19.2 Retention — four tables that grow forever

§ 3.3 says login attempts are "deleted by a scheduled job" and there is no scheduler; Celery is
Phase 2 and this is needed in Phase 1. So it is a management command, run by cron, and the
scheduler question stays open without blocking anything.

```
manage.py auth_cleanup [--dry-run]
```

| Table | Rule | If it never runs |
|---|---|---|
| `users_login_attempt` | Delete older than `LOGIN_ATTEMPT_RETENTION_DAYS` (90) | Grows with **attack traffic**, not user count — the one table an attacker controls the size of |
| `users_user_session` | Delete revoked or expired rows older than 30 days | The sessions screen slows down and then becomes unreadable |
| `users_password_reset_token` | Delete used or expired rows older than 7 days | Minor, but they are credentials-shaped and should not linger |
| `core_activity_log` | **Never deleted here.** Append-only (§ 3.12) | Archival is a product decision. A core that silently truncates an audit trail is a core that cannot be trusted with one |

**Plus a live-session cap.** `MAX_SESSIONS_PER_USER` (default 10): issuing session 11 revokes the
oldest live one with `reason="expired"`. Without a cap, one integration looping a login is an
unbounded write to a table on the authentication hot path.

### 19.3 Rotating `JWT_SIGNING_KEY`

§ 12 correctly separates it from `SECRET_KEY`. It does not say how to change it — and as specified,
changing it invalidates **every** access and refresh token at once, signing out every user in the
product simultaneously. That is not a rotation procedure; it is an outage you schedule.

```python
JWT_SIGNING_KEY           = env("JWT_SIGNING_KEY")            # signs; also verifies
JWT_SIGNING_KEY_FALLBACKS = env.list("JWT_SIGNING_KEY_FALLBACKS", default=[])   # verify ONLY
```

Tokens carry a `kid` header naming the key that signed them. Verification tries `kid` first and
falls back to the list. Rotation is then: add the new key as primary, move the old one to
fallbacks, wait out `REFRESH_TOKEN_LIFETIME`, drop it.

> **Fallbacks verify and never sign.** A compromised key left in the list still accepts tokens an
> attacker minted with it, so the list is an overlap window and not a place to accumulate history.
> Same shape as Django's own `SECRET_KEY_FALLBACKS`, for the same reason.

---

## 20. The Django admin

**`/admin/` is mounted in `config/urls.py` today, and chapters 1–15 never mention it.** It is not a
detail. It is a complete second authentication and authorization system running in the same process
as the one this document specifies, and it disagrees with it on every point:

| | This design | `/admin/` |
|---|---|---|
| Authentication | `CookieJWTAuthentication`, JWT + DB session (§ 6.4) | Django's session cookie. **None of Ch. 6 applies** — no rotation, no family, no `UserSession` row, no revocation |
| Authorization | `rbac_permission` via `RBACBackend` (§ 7.4) | `is_staff` plus `auth_permission` — **a different table**, which § 7.4a is otherwise trying to keep empty |
| Boot enforcement | `dbx.E001` walks `/api/` | **Not under `/api/`.** Never seen |
| Test enforcement | `test_route_enforcement.py` | Same. Never seen |
| Guards | Elevated-role (§ 8.2), last-superuser (§ 8.3), all in `rbac.services` | **Bypassed.** The admin writes model rows directly |
| Audit | Every mutation writes `ActivityLog` (§ 3.12) | `django_admin_log`, a separate trail nothing else reads |

> ⚠️ **Concretely: register `Role`, `RolePermission` and `UserRole` in the admin the ordinary way,
> and any `is_staff` user with the right `auth_permission` can grant themselves `administrator`
> through a web form** — past the elevated-role guard that § 8.2 exists to enforce, writing no
> `ActivityLog` row. Chapter 9 spends four mechanisms making a forgotten gate impossible on `/api/`,
> and this is a door beside it with none of them.

**The decision (A24), three parts:**

1. **`ADMIN_ENABLED`, defaulting to `DEBUG`.** `config/urls.py` mounts `/admin/` only when it is
   true. It is genuinely useful locally; it is a liability in production, and "we'll remember to
   turn it off" is not a control.
2. **`rbac` models are not registered at all.** Every mutation in § 8.4 goes through `rbac.services`
   — that is the sentence that makes the guards and the audit trail true, and an admin registration
   is a second writer that makes it false. `users.User` is registered read-mostly: no raw password
   field (§ 5 already says so), and `is_superuser`, `is_staff` and role assignment are not editable
   there.
3. **`is_staff` is documented as full trust and granted like it.** It is not "can see the admin";
   it is "can act outside the authorization system". Setting it is gated behind the elevated-role
   guard and audited as `users.user.staff_granted`.

> **Why not simply delete the admin?** Because it is the thing you need at 2am when the API is the
> broken component, and a core that removes it forces every product to re-add it under pressure and
> without these three rules. Keep it, off by default, with the sharp edges taken off.

---

## Appendix A — what this deliberately does not do

| Not here | Why | When |
|---|---|---|
| Multi-tenancy / organisation scoping | `DATA_MODEL.md` 🚧 **D3** is open. `visible_to()` is the seam that makes it one method per model later | If a product needs it |
| Impersonation | Worth having, but it is an operator feature rather than part of the auth core — and it needs its own escalation guards | Phase 2 |
| SSO / OAuth / SAML | A core must not assume an identity provider. Single-company deployments converge on one, and no two products copied from this core will agree on which | Plugin |
| Per-user permission grants | A10 — deliberate, argued, and the majority position | Never |
| Explicit denies | A11 | Never |
| `/api/v1/` | `API_DESIGN.md` — a version added before it is needed is decoration | First external consumer |
| Machine-caller credentials | `API_DESIGN.md` § Machine callers specifies them; they reuse **this** RBAC layer rather than a second one | Phase 2 |

---

## Appendix B — the gap review

**A design review of chapters 1–15, run 2026-09-21 before any code was written.** It found 28 gaps.
This is the record of them, because the value of a review is lost if the reader cannot tell which
parts of the document were rewritten under pressure and why.

**Four were defects that make the spec unbuildable as written**, each verified against the installed
Django 5.2.17 source rather than argued from memory:

| # | Defect | Verified at | Fixed in |
|---|---|---|---|
| 1 | `PermissionsMixin.has_perm` returns `True` for an active superuser **before any backend runs**, so A12's audited bypass is unreachable and `authz.superuser_bypass` is never written | `django/contrib/auth/models.py:77-78` | § 7.4 |
| 2 | `ModelBackend` rejects inactive users inside `authenticate()`, so `failure_reason="inactive"` can never be recorded — and with `is_active` defaulting `False`, every invited user's first login is misfiled as `bad_password` | `django/contrib/auth/backends.py:91-96` | § 6.2 |
| 3 | `rbac/0002_seed_system_roles` runs before `post_migrate`, so `administrator` is seeded holding **no** permissions | § 7.3 vs § 13 | § 13 |
| 4 | `DELETE /api/auth/sessions/<public_id>/` and the invitation revoke route address a `public_id` column neither table has | § 3.2, § 3.5 vs § 10 | § 3.2, § 3.5 |

**Eleven were missing pieces without which the system does not work end to end:** no dependency list
at all (Ch. 16); the refresh-rotation race that logs a two-tab user out (A23); no cache
configuration, with three security controls silently per-worker (§ 17.4); client IP taken from
`REMOTE_ADDR`, making per-IP lockout a self-inflicted outage behind any proxy (§ 17.3); no
same-site or CORS statement, so the cookie scheme works in dev and fails silently in production
(§ 17.1–17.2); CSRF double-submit forgeable from a sibling subdomain (§ 17.5); TOTP with no replay
guard, no window and no dedicated throttle, and `mfa_token` never specified (§ 6.8); no email
configuration for the two flows that send mail (Ch. 18); no way to create the first account
(§ 19.1); the Django admin as an unmentioned second auth system (Ch. 20); and `BaseViewSet` not
reaching the `APIView`s that make up the entire authentication surface (§ 9.1).

**The remainder were smaller but real:** `PUBLIC_ROUTES` referenced and never defined (§ 9.2);
`registry.seal()` with no caller; `User.visible_to()` mandated and never written (§ 7.6);
deactivation not revoking sessions; `mfa_enforced` never recomputed on role change; four tables with
no retention (§ 19.2); no `JWT_SIGNING_KEY` rotation path (§ 19.3); no `Cache-Control: no-store`
(§ 6.4); ordering and filter allow-lists required by `API_DESIGN.md` but not carried by the base
class; the `mfa_failed` attempt never written; `administrator` vs `admin` and two different
definitions of `staff` across two documents (§ 8.1); and residual sentences recording where a
pattern came from rather than what it does, which `AGENTS.md` rule 5a forbids.

> **The pattern worth keeping.** Almost every one of these is invisible in development and appears
> only in production, or appears as something else entirely — a CORS error that is really a missing
> header allow-list, a "flaky" logout that is really rotation without a grace window, an empty audit
> log that reads as good news. That is the same asymmetry [`AUTH_FAILURE_MODES.md`](AUTH_FAILURE_MODES.md)
> § 1 identifies for authorization bugs, and it is the argument for reviewing a design on paper
> while paper is still what it costs to change.

