# Configuration — nothing hard-coded

**Where every value a product depends on lives, how it is declared, validated, resolved and changed —
and the tests that make "nothing hard-coded" a property of the build rather than a hope.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

## Scope — read first

**Owns:** the configuration ladder (which kind of value goes where) · settings modules and the
environment · `APP_ENV` classification · boot refusal at settings import · the env validator ·
project identity derivation · installation identity and branding *data* · the typed settings
registry · the admission test for settings · feature flags · capabilities · guard modes ·
admin-editable lookups · locale, currency, timezone and format settings · runtime configuration in
the database with env as prefill · the configuration half of restore safety · the anti-hard-coding
tests.

**Does not own:**

| Topic | Owner |
|---|---|
| The registry mechanism itself, plugin discovery, soft-disable, "every core literal is a registry" | [`EXTENSIBILITY.md`](EXTENSIBILITY.md) |
| Encrypted integration credentials, the encryption service and key rotation, the non-production outbound guard, job state | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| Rendering of theme and white-label branding, the bootstrap client, design tokens, i18n rendering, `proxy.ts` | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) |
| Data-plane checks, health endpoints, the system-health page, doctors as a family | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
| Backups, the restore procedure, environments, release images, the first-run wizard, `setup.sh` | [`OPERATIONS.md`](OPERATIONS.md) |
| Money as a type, number sequences, business calendars | [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) |
| Tenancy and per-tenant white-label | [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) |
| Files, uploads and presigned URLs | [`API_PLATFORM.md`](API_PLATFORM.md) |
| The ratchet-baseline mechanism for architecture tests, CI | [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) |
| Auth settings, cookies, `dbx.E00x` system checks, the deployment contract | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) Ch. 9.2, 12, 17 — extended here, not replaced |

---

## 0. The rules in one screen

1. **No hard-coded *values*; few behavioural *knobs*.** A deployment, tenant or business fact is
   never a literal. A behaviour is a knob only if it passes the admission test. → [§ 1](#1-the-principle--no-hard-coded-values-few-knobs--process), [§ 10](#10-the-admission-test--what-earns-a-setting--process)
2. **Every value has exactly one rung on the ladder** — constant, env, derived, registry setting,
   guard mode, flag, capability, lookup, credential, singleton row, design token. Never two. → [§ 2](#2-the-configuration-ladder--tier-1--core)
3. **Only `config/settings/` reads the environment.** Not core, not a plugin, not a management
   command. → [§ 3](#3-settings-modules-and-the-environment--tier-1--core)
4. **Unknown `APP_ENV` is production.** One predicate, `is_production_like()`, decides everywhere;
   `DEBUG` is never an environment test. → [§ 4](#4-app_env--fail-closed-classification--tier-1--core)
5. **A production-like process refuses to import its settings** while any problem stands — every
   problem listed at once, names only, never values. System checks are not the guard. → [§ 5](#5-boot-refusal-at-settings-import--tier-1--core)
6. **The shipped `.env.example` must be unbootable in production**, and CI proves it. → [§ 5](#5-boot-refusal-at-settings-import--tier-1--core)
7. **Every secret is distinct from every other secret.** → [§ 5](#5-boot-refusal-at-settings-import--tier-1--core)
8. **One product name derives the rest** — OTP issuer, from-address, cookie and cache prefixes, API
   title. Shipped defaults announce themselves. → [§ 7](#7-project-identity--one-name-derives-the-rest--tier-1--core)
9. **Settings are declared in code, never invented at a call site.** A read of an undeclared key is a
   bug that fails a test before merge. → [§ 9](#9-the-typed-settings-registry--tier-1--core)
10. **A reader never raises and never falls open.** Unreadable ⇒ the declared default, and the
    declared default is the safe one. → [§ 9.6](#96-resolution-never-raises-and-defaults-safe)
11. **A setting nothing reads is a defect.** A test fails on it. → [§ 9.11](#911-a-setting-nothing-reads-is-a-defect)
12. **Nothing that grants access is a setting or a flag.** Access is a permission. → [§ 10](#10-the-admission-test--what-earns-a-setting--process)
13. **Unknown flag ⇒ off. Disabled ⇒ off for everyone, targets included. Targeting narrows; it never
    enables.** → [§ 11](#11-feature-flags--tier-1--core)
14. **Every release flag has an owner and an expiry; a flag past expiry fails CI.** → [§ 11](#11-feature-flags--tier-1--core)
15. **A guard added to live traffic ships `off` or `log_only`,** and a test proves shipping it
    changed nothing. → [§ 13](#13-guard-modes--offlog_onlyenforce--tier-1--core)
16. **Admin-editable lists have a stable key admins cannot reach and a label they can;** membership
    is validated from the table at request time; values are deactivated, never deleted. → [§ 14](#14-admin-editable-lookups--tier-1--core)
17. **Store UTC, return ISO-8601, format once, in one place, in the viewer's locale and timezone.**
    No currency, zone or locale literal outside the settings layer. → [§ 15](#15-locale-currency-timezone-and-formats--tier-1--core)
18. **Anything an operator changes after start lives in the database; env only prefills it.** → [§ 16](#16-runtime-configuration-in-the-database--env-as-prefill--tier-2--core)
19. **A restored database never brings its source's connections, schedules or credentials with it,**
    and each environment has its own encryption keys. → [§ 17](#17-restore-and-environment-separation--tier-2--core)
20. **Every rule above has a test that can fail.** → [§ 18](#18-the-anti-hard-coding-tests--tier-1--core--process)

---

## 1. The principle — no hard-coded values, few knobs — **Process**

**What.** Two different things get called "configurable", and confusing them produces either a
college project (everything a literal) or an unusable one (everything a switch).

| | A **value** | A **knob** |
|---|---|---|
| Is | A fact about *this* deployment, tenant or business | A choice between two behaviours of the software |
| Examples | Product name, domain, currency, timezone, SMTP host, a tax jurisdiction, a lead-source list, the retention period this company's policy requires | "Should sign-in require MFA for admins?", "Is the new pricing screen on?" |
| Rule | **Never hard-coded.** Always read from the right rung of the ladder | **Few.** Each one must pass the admission test (§ 10) |
| Cost of getting it wrong | A grep project across hundreds of call sites the day the second product has a different answer | A branch someone must maintain, test and document forever |

**Why.** [`../VISION.md`](../VISION.md) lists *"Not maximal configurability"* as a non-goal, and the
owner's requirement is *"nothing should be hard-coded"*. **They do not conflict — they are about
different things.** The vision forbids *knobs* nobody asked for; the requirement forbids *values*
written as literals. A base that hard-codes one market's currency, timezone or company name is not
opinionated, it is single-tenant by accident: a real codebase accumulated nearly three hundred
literal occurrences of one currency code and a couple of dozen of one timezone before anyone tried
to sell to a second market, and retrofitting it became a sweep of every formatter, every default and
every test fixture.

**Rules.**
- **A value is never a literal.** If a second product could reasonably have a different answer, the
  answer comes from a rung on the ladder — not from a constant, not from a default argument, not from
  a test fixture that production code silently relies on.
- **A knob must earn its place** (§ 10). "It is a magic number" and "it could be configurable" are
  not reasons. The alternative to a knob is a **named constant with a comment saying why it is not
  configurable** — that is not hard-coding, it is a decision recorded where it is made.
- **Opinionated defaults stay.** A setting's code default is the answer most products want and the
  safe one. Configurability never means "no default" — except for facts the core cannot know
  (currency, country), which have no default and are asked for at first run (§ 15).
- **Formatting is not translation.** Locale-driven *formatting* (dates, numbers, money) is day-one
  core, because it is cheap now and a grep project later. Shipping a *second language* stays out
  of scope per [`../VISION.md`](../VISION.md) *"Not multi-language … on day one"* — but, as that
  non-goal now says, copy goes through the translation layer from day one even while only one
  catalogue exists ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) owns the mechanism), so the
  second language is data, not a sweep.

**Django + Next shape.** This section is a rule; the mechanisms are §§ 2–17.

**Enforced by.** § 18 — the literal scans, the "unread setting" test and the flag-expiry test are
what turn this principle into something that goes red.

**Configurable, not hard-coded.** Not applicable — this is the rule the rest of the file applies.

---

## 2. The configuration ladder — **Tier 1 · Core**

**What.** One decision table for *where a value lives*. Every value has exactly one rung.

| # | Rung | Holds | Examples | Changed by | Takes effect | Spec |
|---|---|---|---|---|---|---|
| 0 | **Code constant** | Contract properties, invariants, protocol facts, floors | API prefix, a key-derivation info string, the weak-placeholder list, `MINIMUM_RETENTION_DAYS = 1` | A PR | Deploy | here, per module |
| 1 | **Environment** | Bootstrap facts needed before the DB is reachable, or that an in-app admin must not be able to change | `APP_ENV`, `SECRET_KEY`, `DATABASE_URL`, `CACHE_URL`, encryption keys, allowed hosts and origins, `TRUSTED_PROXY_COUNT`, `PRODUCT_NAME`, `ADMIN_ENABLED` | The operator | Restart | § 3 |
| 2 | **Derived setting** | Anything computable from rung 1 | OTP issuer, from-address, cookie names, cache key prefix, API title | Its source | With its source | § 7 |
| 3 | **Registry setting** | An operator-tunable policy scalar that passes § 10, at platform, tenant or user scope | Lockout threshold, re-auth window, retention days, quiet hours, a user's timezone | An admin with the permission | Immediately | § 9 |
| 4 | **Guard mode** | A registry setting of one fixed shape: `off \| log_only \| enforce` | Privilege-escalation guard, CSP mode | An admin | Immediately | § 13 |
| 5 | **Feature flag** | A **temporary** gate on a code path, with an owner and an expiry | `billing.new_invoice_screen` | An admin | Immediately | § 11 |
| 6 | **Capability** | Whether a product surface is *available* here (installed, configured, allowed) | "payments available", "self sign-up open" | Derived | Immediately | § 12 |
| 7 | **Lookup** | A list-shaped vocabulary admins edit | Lead sources, cancellation reasons, document categories | An admin | Immediately | § 14 |
| 8 | **Integration credential** | A secret for a third party | SMTP password, an API token, an OAuth client secret | An admin, audited | Immediately | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| 9 | **Installation singleton row** | A cohesive group of runtime config, NULL = env fallback | Identity and branding, the object-storage connection | An admin | Immediately | §§ 8, 16 |
| 10 | **Design token** | Presentational values | Spacing, radii, the colour scale | A PR (or the branding row for brand colour) | Deploy | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) |
| — | **Permission / role** | Access. **Never** any rung above | `billing.invoices.create` | RBAC | Immediately | [`RBAC_DESIGN.md`](RBAC_DESIGN.md) |
| — | **Job state** | Machine memory. **Not configuration** | A sync cursor, a last-processed id | The job | — | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |

**Ask in this order — the first "yes" is the answer:**

1. Does it decide **who may do what**? → a permission. Never a setting, never a flag.
2. Is it a **secret for a third party**? → the credential store.
3. Is it needed **before the database is reachable**, or must an in-app admin be **unable** to change
   it? → environment.
4. Can it be **computed** from something already configured? → derive it; do not ask twice.
5. Does it exist only to **de-risk a launch**? → a feature flag, with an expiry.
6. Is it a **new refusal** being introduced to live traffic? → a guard mode.
7. Is it **list-shaped**? → a lookup.
8. Is it **presentational**? → a design token, or the branding row if it is identity.
9. Does it pass the **admission test** (§ 10)? → a registry setting at the lowest scope with a real
   owner.
10. **None of the above** → a named code constant, with a comment saying why it is not configurable.

**Why.** Without one table, every store grows its own copy of every kind of value. A real codebase
ended with four parallel settings tables built by four modules, a fifth proposed by a security plan,
and around ten per-feature singleton tables each with a `get_or_create` service copied from the
previous one. Separately, its feature flags lived in environment files the running application could
not see, so a hand-maintained file existed purely to record *what production actually had on* — and
went stale the first time someone flipped a flag without editing it.

**Rules.**
- **Never a fifth store.** A new kind of value is a new *row* in this table, argued in an ADR — not a
  new model someone builds because the existing rungs were inconvenient.
- **Never the same fact on two rungs.** If a value moves from env to the registry, the env read is
  deleted in the same change and a test bans it from returning (§ 9.14).
- **Machine state is not configuration.** A job's cursor never goes in the settings table: it has no
  label, no admin, no audit meaning, and a config table that grows a column every time a job needs a
  bookmark stops being readable.

**Django + Next shape.** The table above is the index; each rung's shape is in its section.

**Enforced by.** § 18 — the env-read scan (rung 1 stays in `config/settings/`), the literal scans
(rung 0 is not smuggling values), the role-name scan (the access row).

**Configurable, not hard-coded.** The ladder itself is a convention recorded here. Adding a rung
requires an ADR.

---

## 3. Settings modules and the environment — **Tier 1 · Core**

**What.** How the process reads its bootstrap configuration: split settings modules, one env reader,
no defaults for secrets, and a deliberate choice of build-time versus runtime for every frontend
value.

**Why.** Three failures this prevents. A single settings file with every domain's configuration grew
to over a thousand lines in one codebase, and nobody could tell which keys a given process role
needed. A separate "staging settings" module drifted from production until staging stopped proving
anything about a deploy. And a frontend value baked in at build time had to be rebuilt per
environment, while a security rollout switch that *should* have been flippable in seconds needed a
rebuild too.

**Rules.**
- **Split by what differs, not by environment name.**

  ```
  backend/config/settings/
  ├── __init__.py   empty — DJANGO_SETTINGS_MODULE always names a leaf
  ├── base.py       everything; reads env; derives identity (§ 7)
  ├── dev.py        from .base import *  — DEBUG default on, console email, SQLite allowed
  ├── prod.py       from .base import *  — HSTS, SSL redirect, secure cookies, manifest static
  └── test.py       from .base import *  — fast hasher, isolated cache and storage, NO .env read
  ```

- **There is no `staging.py`.** Staging runs `prod.py` with `APP_ENV=staging`. A staging that runs
  different settings code cannot prove anything about production.
- **Server entrypoints default to `prod`.** `wsgi.py`, `asgi.py` and the Celery app default
  `DJANGO_SETTINGS_MODULE` to `config.settings.prod`; a server process is production unless told
  otherwise. `manage.py` defaults to `dev` for ergonomics — and `dev.py` **refuses to load** when
  `APP_ENV` is production-like (§ 5, `cfg.E001`), so running a production `migrate` with the wrong
  module fails loudly instead of running with `DEBUG` on.
- **Every process role uses the same settings module and therefore the same boot audit** — web,
  worker, beat, shell, every management command. A second ASGI app or a second worker entrypoint that
  builds its own configuration is how one real system ran two of eight startup validators on its
  second entrypoint, and 500'd every request there for want of an initialisation step the first
  entrypoint performed.
- **Only `config/settings/` reads the environment** — the current `settings.py` docstring already
  says so; § 18 makes it a test. Everything else imports `django.conf.settings`.
- **A plugin never reads the environment.** Env belongs to whoever operates the whole product.
  Plugin configuration is a registry setting (§ 9) or an integration credential; a plugin that needs
  env has a hidden deployment requirement nothing can validate.
- **Secrets have no defaults.** `SECRET_KEY = env("SECRET_KEY")` with no fallback fails fast at import.
  A default secret is a secret shared by every deployment that forgot to set one.
- **`.env` is read only if present;** containers inject the environment directly. A `.env` file
  present in a production-like process is a warning (`cfg.W006`) — the deployment checklist line
  *"no `.env` file is in the image"* ([`DEPLOYMENT.md`](DEPLOYMENT.md) § 4) becomes an assertion.
- **`test.py` never reads the developer's `.env`.** A test run that inherits a developer's local kill
  switch or cache URL is a test of that laptop. Every value a host environment could override is
  pinned in `test.py`.
- **List-valued env vars are parsed once, in settings** (`env.list`), never split at the call site.

**Frontend — build-time versus runtime, chosen per value.**

| Value | When read | Why |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | **Build time** — inlined into the bundle | Public, stable per environment. Changing it is a rebuild; [`DEPLOYMENT.md`](DEPLOYMENT.md) § 2 already warns |
| Environment label, identity, locale defaults, public flags | **Runtime** — fetched from `/api/public/config/` by a server component | A rename or a flag flip must not need a rebuild |
| CSP mode and other request-time switches | **Runtime** — `process.env` read per request in `proxy.ts` | A security rollout must be reversible with a restart, not a build. Next 16 renamed `middleware.ts` to `proxy.ts` (verified: `frontend/node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md`) |
| Anything secret | **Server only**, never `NEXT_PUBLIC_*` | [`NEXTJS_STANDARDS.md`](NEXTJS_STANDARDS.md) § 6 |

- **`NEXT_PUBLIC_*` is for truly public, build-stable values only.** Everything environment-varying
  comes from the runtime endpoint or from server env read during dynamic rendering (Next 16:
  `await connection()` before reading `process.env` in a server component).
- **`process.env` is read in exactly two places:** `frontend/src/core/config/server.ts`
  (`import "server-only"`) and `next.config.ts`. § 18 scans for it.
- **Environment detection never compares URLs.** `isProduction = API_URL === "<the prod URL>"` is the
  frontend's version of the `DEBUG` mistake; the environment comes from the runtime config payload.

**Django + Next shape.** `config/settings/{base,dev,prod,test}.py`; `core/env.py` (§ 4);
`core/config_audit.py` (§ 5); `core/env_schema.py` (§ 6);
`frontend/src/core/config/{server,public}.ts`; `GET /api/public/config/` (public, cached, returns only
fields declared public).

**Enforced by.**
- `tests/architecture/test_env_reads.py` (§ 18) — `os.environ`, `os.getenv`, `environ.Env`,
  `process.env` outside their allowed homes fail.
- `tests/core/test_settings_modules.py` — `wsgi.py`, `asgi.py` and the Celery app default to
  `config.settings.prod`; every leaf module ends with the audit call (§ 5); `test.py` does not call
  `read_env`.

**Configurable, not hard-coded.** `DJANGO_SETTINGS_MODULE` per process; every env key declared in
`core/env_schema.py` (§ 6).

---

## 4. `APP_ENV` — fail-closed classification — **Tier 1 · Core**

**What.** One explicit environment identity, classified by an **allow-list of non-production values**.
Anything else — a typo, a capital letter, a new label, an empty string — is production-like.

**Why.** Operators deployed with `ENVIRONMENT=Production` (capital P) and with `staging`, and both
bypassed every security check written as `== "production"`. Allow-listing the safe values fails
closed; deny-listing production fails open on every label nobody anticipated. The same codebase then
fixed the predicate in one place and left two security features keyed on the old literal comparison
— **two predicates drift**, which is why there must be exactly one.

**Rules.**
- **`APP_ENV` is required and has no default.** Unset is production-like. `.env.example` ships
  `APP_ENV=development` so a fresh checkout works, and a server that forgot to set it refuses to run
  with development secrets — the fail-closed direction.
- **Non-production allow-list:** `development`, `local`, `test`, `ci`. Compared after `strip().lower()`.
  **Everything else is production-like, including `staging`** — staging holds real-shaped data and
  real credentials and gets production's refusals.
- **One predicate.** `core.env.is_production_like()` is the only environment test in the codebase.
  Never `settings.DEBUG`, never `APP_ENV == "…"`, never hostname, port, or API URL. § 18 bans the
  alternatives.
- **`DEBUG` is not an environment.** It is a switch that production refuses (`cfg.E002`). "Secure
  cookies when not `DEBUG`" is the wrong question — the right one is "secure cookies when production
  -like", and in production `DEBUG` is already refused. See ⚠️ Conflicts #4.
- **Classification and labelling are different functions.** Security asks `is_production_like()`.
  The *environment ribbon* asks `environment_label()`, which returns:

  | `APP_ENV` | Ribbon | Tone |
  |---|---|---|
  | exactly `production` | none | — |
  | `staging` | "Staging" | staging |
  | `development`, `local` | "Development" | dev |
  | `test`, `ci` | "Test" | dev |
  | **anything else** | **"Unknown environment: set APP_ENV"** | **the loudest** |

  **An unknown value is secured like production and labelled louder than anything** — not knowing
  which environment you are on is exactly when a warning is worth most. Staging reached by IP, or a
  colleague's stack, still labels itself.
- **The ribbon is never inferred.** No hostname sniffing, no "localhost means dev".
- **Non-production also prefixes the document title** (`[Staging] …`), so a tab in a row of tabs is
  identifiable without looking at the page.

**Django + Next shape.**

```python
# core/env.py — imports nothing from Django apps; safe to import from settings
NON_PRODUCTION = frozenset({"development", "local", "test", "ci"})

def normalise(app_env: str | None) -> str:
    return (app_env or "").strip().lower()

def is_production_like(app_env: str | None = None) -> bool:
    if app_env is None:
        from django.conf import settings
        app_env = settings.APP_ENV
    return normalise(app_env) not in NON_PRODUCTION
```

`environment_label()` lives beside it and is exposed as `environment: {label, tone}` in
`/api/public/config/` and `/api/auth/me/`. Next renders `<EnvironmentRibbon>` in the root layout from
the server-fetched public config, so it appears on the sign-in page too.

**Enforced by.**
- `tests/core/test_env.py` — `Production`, ` prod `, `staging`, `qa`, `""` and `None` are all
  production-like; only the four allow-listed values are not; the ribbon for an unknown value is the
  loud tone and for exactly `production` is none.
- `tests/architecture/test_environment_predicate.py` (§ 18) — no `settings.DEBUG` used in a
  conditional outside `config/settings/`, no `APP_ENV` comparison outside `core/env.py`.
- Frontend: `EnvironmentRibbon.test.tsx` — unknown renders the loud tone; production renders nothing.

**Configurable, not hard-coded.** `APP_ENV` (env). The allow-list is a code constant on purpose: a
new *non*-production label is a reviewed decision, not an env value that could weaken every check.

---

## 5. Boot refusal at settings import — **Tier 1 · Core**

**What.** `core/config_audit.py` inspects the fully built settings namespace **at the end of settings
import** and, in a production-like environment, raises `ImproperlyConfigured` listing **every**
problem at once, each naming its fix. It closes [`TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-7**.

**Why system checks are not enough.** Django system checks run on `manage.py` commands and
`runserver`. **They do not run when gunicorn or uvicorn serves the app, and they do not run when a
Celery worker starts** — and `--deploy` checks run only under `check --deploy`. The `dbx.E00x` checks
in [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.2 are good gates for developers and CI; they are not a
boot guard. Settings import is the one thing every process role does before serving anything.

**Why all at once.** An operator fixing one problem per restart meets six restarts. One report with
six numbered lines is one fix. And **prose about configuration drifts from configuration; an
assertion cannot** — a real deployment document listed five blockers that the code had already fixed,
while a docstring claimed "the boot validator already requires X" for a validator that did not exist.
The only defence turned out to be a runtime error that surfaced as fleet-wide monitoring loss rather
than as a config error.

**Rules.**
- **Every settings leaf ends with the same call.** `enforce(globals())` is the last line of `dev.py`,
  `prod.py` and `test.py`. A test asserts it.
- **`core/config_audit.py` imports nothing that needs the app registry** — it runs before Django is
  set up. Anything needing the database or installed apps (required rows, lookups, identity rows) is
  a data-plane check in [`OBSERVABILITY.md`](OBSERVABILITY.md), not the audit.
- **Findings name keys, never values** (`AGENTS.md` rule 6). "`SECRET_KEY` contains a known
  placeholder", never the key. A test pushes a canary secret through every rule and asserts it never
  appears in the output.
- **Two tiers.** *Problems* refuse boot in production-like environments and are printed as warnings
  elsewhere. *Warnings* are legitimate-but-notable choices, printed at every boot and surfaced on the
  system-health page.
- **The valid production configuration is tested first.** A validator that rejects everything is
  trivially "safe" and useless; the first test asserts a correct production namespace boots.
- **Rules are independent.** Each has a test that violates *only* that rule and expects *only* that
  finding. That discipline is how one real audit found that its placeholder rule used equality, so
  `"changeme" * 4` passed.

**The rules.** Codes are `cfg.*`, a separate namespace from `dbx.*` system checks.

| Code | Tier | Refuses / warns when |
|---|---|---|
| `cfg.E001` | Problem | `dev.py` or `test.py` loaded while `APP_ENV` is production-like |
| `cfg.E002` | Problem | `DEBUG=True` |
| `cfg.E003` | Problem | A secret fails the strength rules below (`SECRET_KEY`, `JWT_SIGNING_KEY`, each encryption key, each fallback key) |
| `cfg.E004` | Problem | **Two secrets are equal** — any pair among `SECRET_KEY`, `JWT_SIGNING_KEY`, every encryption key, every setup token. Rotating one must never brick another; one key doing two jobs turns a signing leak into a decryption leak |
| `cfg.E005` | Problem | `ALLOWED_HOSTS` empty or containing `*` |
| `cfg.E006` | Problem | A CORS or CSRF trusted origin is `*`, `http://`, `localhost` or a loopback address while credentials are allowed |
| `cfg.E007` | Problem | `AUTH_COOKIE_SECURE` false, or an auth cookie without `SameSite` (the import-time twin of `dbx.E008`) |
| `cfg.E008` | Problem | Email backend is console, file, locmem or dummy — **reset links would be written to logs** — or SMTP with no host |
| `cfg.E009` | Problem | Cache backend is per-process (the import-time twin of `dbx.E005`) |
| `cfg.E010` | Problem | `DATABASE_URL` unset or SQLite ([ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md)) |
| `cfg.E011` | Problem | `FRONTEND_BASE_URL` not `https://`, or a loopback host |
| `cfg.E012` | Problem | Throttling disabled (`DEFAULT_THROTTLE_CLASSES` empty) |
| `cfg.E013` | Problem | A required encryption key is missing or does not parse as a key |
| `cfg.E014` | Problem | `APP_ENV` unset (it has no default — § 4) |
| `cfg.W001` | Warning | HSTS off |
| `cfg.W002` | Warning | `TRUSTED_PROXY_COUNT=0` with `SECURE_PROXY_SSL_HEADER` set (twin of `dbx.W003`) |
| `cfg.W003` | Warning | An identity value (§ 7) still equals the shipped default |
| `cfg.W004` | Warning | `ADMIN_ENABLED` on ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) Ch. 20) |
| `cfg.W005` | Warning | A verify-only fallback key list is non-empty — a rotation is in progress; finish it |
| `cfg.W006` | Warning | A `.env` file was read in a production-like process |
| `cfg.W007` | Warning | The OpenAPI schema is public outside development |

**Secret strength.** Substring matching for distinctive placeholders, exact matching for short
generic words (substring on `"test"` would reject honest random keys), a length floor, and a
distinct-character floor that catches repetition.

```python
DISTINCTIVE = ("changeme", "change-me", "change_me", "replace", "placeholder", "your-", "example",
               "insecure", "dummy", "notsecret", "xxxxxxxx", "secret-key", "django-insecure")
GENERIC = frozenset({"secret", "password", "test", "dev", "key", "admin", "default", "none"})
```

```python
def weak_reason(value: str | None, *, min_length: int) -> str | None:
    """Why this secret is unacceptable, or None. Never returns or logs the value."""
    v = (value or "").strip()
    if not v:
        return "is empty"
    if v.lower() in GENERIC:
        return "is a generic placeholder word"
    if any(p in v.lower() for p in DISTINCTIVE):
        return "contains a known placeholder"
    if len(v) < min_length:
        return f"is shorter than {min_length} characters"
    if len(set(v)) < 12:
        return "has fewer than 12 distinct characters"
    return None
```

`min_length` is 50 for `SECRET_KEY` (matching [`DEPLOYMENT.md`](DEPLOYMENT.md) § 1) and the
signing-key length for JWT keys; encryption keys are validated by parsing them, not by length.

**Django + Next shape.**

```python
# core/config_audit.py
def enforce(ns: Mapping[str, Any]) -> None:
    problems, warnings = audit(ns)              # lists of Finding(code, key, message, fix)
    if is_production_like(ns.get("APP_ENV")):
        if problems:
            raise ImproperlyConfigured(render("Refusing to start", problems, warnings))
        emit_warnings(warnings)                 # one structured log line each
    else:
        emit_warnings(problems + warnings)      # a developer sees them, nothing refuses
```

- `python -m core.config_audit` prints the same report without raising — the pre-deploy step in
  the release image, run against the target environment, before the swap.
- Frontend: `next.config.ts` asserts, for a production build, that `NEXT_PUBLIC_API_URL` is `https://`
  and not a loopback host, and fails the build otherwise.
- Compose uses `${VAR:?}` for required secrets so `docker compose up` fails before Python starts
  ([`OPERATIONS.md`](OPERATIONS.md)).

**Enforced by.**
- `tests/core/test_config_audit.py`: `test_valid_production_config_boots` **first**; one parametrised
  case per rule violating only that rule; `test_all_problems_reported_together`;
  `test_no_value_in_any_message` (canary); `test_dev_module_refuses_production_env`.
- `tests/core/test_env_example.py` — **every secret placeholder in `backend/.env.example` is refused by
  `weak_reason`**, so the shipped example can never boot in production.
- **CI step "Production config must refuse development defaults":** import settings with
  `APP_ENV=production` and the values from `.env.example`; the step **passes only if the import
  fails** with `ImproperlyConfigured`. It is proven to go red by running it once with a valid
  production namespace.

**Configurable, not hard-coded.** The rules and floors are code constants — making them env values
would let the environment being audited weaken its own audit.

---

## 6. `validate_env` — the release-image environment validator — **Tier 1 · Core**

**What.** A command that compares the environment a release will run with against the declared
schema, **inside the new image, before it takes traffic**: unknown keys, missing required keys, keys
missing from `.env.example`, and retired keys still set.

**Why.** A typo in an env file is silent: `SECURE_HSTS_SECOND=31536000` sets nothing and nothing
complains. A key moved into the database keeps being set in env files for years, and the next person
edits the env value and wonders why nothing changes. Running the validator inside the *new* image
catches both before the swap, when a failure costs a retry instead of an incident.

**Rules.**
- **One schema.** `core/env_schema.py` declares every key: name, which environments require it,
  whether it is secret, a one-line description, and the placeholder `.env.example` carries.
- **Unknown key ⇒ error** in production-like runs, with a did-you-mean suggestion from the schema.
- **Retired keys are declared, not deleted**: `EnvKey("LOCKOUT_THRESHOLD", retired=True,
  moved_to="setting security.lockout.threshold")`. The validator says where the value went instead of
  just "unknown".
- **Shadowed prefill keys are reported:** an env key that only prefills a DB value (§ 16) and is set
  while the DB row is already populated prints "`X` is set but ignored — the database value wins" —
  key names only.
- **The schema, the settings modules and `.env.example` cannot drift:** a test reads the literal
  names passed to `env(...)` in `config/settings/` and compares all three sets.

**Django + Next shape.**

```python
# core/env_schema.py
KEYS = [
    EnvKey("APP_ENV", required=ALL, description="Environment identity — § 4"),
    EnvKey("SECRET_KEY", required=ALL, secret=True, placeholder="change-me-generate-a-real-one"),
    EnvKey("PRODUCT_NAME", required=PRODUCTION, description="Drives identity — § 7"),
    EnvKey("LOCKOUT_THRESHOLD", retired=True, moved_to="setting security.lockout.threshold"),
]
```

`manage.py validate_env [--env-file PATH] [--strict]` exits non-zero on any error; `--strict` also
fails on warnings. The release pipeline runs it in the new image before migrations
([`OPERATIONS.md`](OPERATIONS.md)).

**Enforced by.** `tests/core/test_env_schema.py` — schema ⇔ settings reads ⇔ `.env.example` are
equal sets (retired keys excluded from the last two); `test_validate_env.py` — an unknown key, a
missing required key and a retired key each produce their own error.

**Configurable, not hard-coded.** The schema is code, reviewed; the values are the operator's.

---

## 7. Project identity — one name derives the rest — **Tier 1 · Core**

**What.** A product sets a name, a slug and a domain once. Everything that spells the product's name
somewhere derives from them. Every shipped default **announces that it is a default.**

**Why.** Identity literals are the most expensive hard-coding in a base, because some of them cannot
be corrected after the fact:
- An authenticator app's **issuer** label is written into every device that enrols. A base that ships
  its own name as the issuer brands every product built on it in users' phones, and correcting it
  means re-enrolling users.
- A literal **from-address** sends mail as a company the product has nothing to do with.
- A fixed **cookie name** shared by every product on `localhost` (cookies ignore the port) logs a
  developer out of one project whenever they sign in to another — and keying it to the product name
  still collides between two checkouts of the *same* product.
- A fixed **cache key prefix** lets two products sharing one Redis read each other's permission
  versions and throttle counters.

**Rules.**
- **Three inputs** (env, rung 1): `PRODUCT_NAME`, `PRODUCT_SLUG` (optional — derived by slugifying
  the name when blank), `PRIMARY_DOMAIN`. Optional overrides for each derived value exist only where
  a product genuinely needs a different answer.
- **Derived, never set independently:**

  | Derived | From | Rule |
  |---|---|---|
  | `OTP_ISSUER` | name | The `otpauth://` issuer ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 6.8) |
  | `DEFAULT_FROM_EMAIL` | name + domain | `"<name> <no-reply@<domain>>"` |
  | Auth cookie prefix | slug | `<prefix>_access`, `<prefix>_refresh`, `<prefix>_csrf`, with `__Host-` per [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 17.5 |
  | `SESSION_COOKIE_NAME`, `CSRF_COOKIE_NAME` | slug | For the Django admin session, when mounted |
  | Cache `KEY_PREFIX` | slug | Two products, one Redis |
  | Celery queue and result-key prefix | slug | Two products, one broker |
  | OpenAPI title | name | `"<name> API"` |
  | Log `service` field, error-tracker release name | slug | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
  | Export and audit envelope `source` stamp | slug | So an import can tell "our bundle" from a foreign one |
  | Compose project name | slug | [`OPERATIONS.md`](OPERATIONS.md) |

- **Unset domain ⇒ `localhost`.** Mail from `no-reply@localhost` bounces loudly; it impersonates
  nobody. A plausible-looking default domain is worse than an obviously broken one.
- **Shipped defaults announce themselves.** `PRODUCT_NAME` defaults to `"Unnamed product"`, the
  tagline to *"Rename this deployment — set PRODUCT_NAME"*, both visible on the sign-in page. **No
  default logo** — a monogram from the name — so no copy wears the previous product's mark.
  `cfg.W003` warns in production while any identity value equals its shipped default.
- **The boilerplate's own name appears nowhere in core code.** It is the shipped default of nothing.
- **Development checkouts get distinct slugs:** `setup.sh` derives `PRODUCT_SLUG` from the directory
  name ([`OPERATIONS.md`](OPERATIONS.md)), so two worktrees on one machine keep separate cookies.
- **Boot identity versus display identity.** Cookie names, prefixes and the OTP issuer are **env**
  — changing them at runtime would sign everyone out or split cache namespaces mid-flight. The
  human-facing display name, tagline and logo are overridable at runtime by the identity row (§ 8),
  which falls back to these env values.

**Django + Next shape.**

```python
# config/settings/base.py (identity block)
PRODUCT_NAME   = env("PRODUCT_NAME", default=SHIPPED_PRODUCT_NAME)     # "Unnamed product"
PRODUCT_SLUG   = env("PRODUCT_SLUG", default="") or slugify(PRODUCT_NAME)
PRIMARY_DOMAIN = env("PRIMARY_DOMAIN", default="localhost")            # bounces loudly
OTP_ISSUER         = env("OTP_ISSUER", default="") or PRODUCT_NAME
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="") or (
    f"{PRODUCT_NAME} <no-reply@{PRIMARY_DOMAIN}>")
AUTH_COOKIE_PREFIX = PRODUCT_SLUG.replace("-", "_")
SESSION_COOKIE_NAME = f"{AUTH_COOKIE_PREFIX}_sessionid"
CACHES["default"]["KEY_PREFIX"] = PRODUCT_SLUG
SPECTACULAR_SETTINGS["TITLE"] = f"{PRODUCT_NAME} API"
```

The frontend never reads the product name from env: `generateMetadata` in the root layout reads it
from `/api/public/config/`, so a rename is a restart, not a rebuild.

**Enforced by.**
- `tests/core/test_identity.py` — with only `PRODUCT_NAME` set, every derived value in the table
  follows it; an explicit override wins; unset domain yields `@localhost`; `cfg.W003` fires for shipped
  defaults in production.
- `tests/architecture/test_no_boilerplate_identity.py` (§ 18) — the boilerplate's name and the
  literal cookie prefix do not appear in `backend/core/`, `frontend/src/core/` or settings, outside
  the one module that defines the shipped defaults.

**Configurable, not hard-coded.** `PRODUCT_NAME`, `PRODUCT_SLUG`, `PRIMARY_DOMAIN`; overrides
`OTP_ISSUER`, `DEFAULT_FROM_EMAIL`.

---

## 8. Installation identity and branding data — **Tier 2 · Core**

**What.** One singleton row holding the installation's human-facing identity, editable at runtime,
where **every column is nullable and NULL means "fall back to the deployment default"**. This file
owns the data and its validation; rendering (tokens, title sync, favicon, contrast display) is
[`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md); per-tenant branding is the tenancy module in
[`REUSABLE_MODULES.md`](REUSABLE_MODULES.md).

**Why.** A platform-default brand hard-coded in a frontend constant — legal entity, support address,
terms and privacy URLs — needed a code change per deployment. Branding in a row fixes that, but only
if an empty row can never degrade the product: **there must be no state in which this table being
empty makes the application worse than its env configuration.**

**Rules.**
- **Exactly one row**, enforced by the database (`CheckConstraint(pk=1)`), not by `save()` alone.
  Two rows is undefined branding.
- **Reads never create the row.** A missing row resolves to the env/derived defaults; `load()` on a
  GET is side-effect free.
- **NULL is "inherit", not "blank".** Clearing a field restores the deployment default rather than
  blanking the name. One `FALLBACKS` map drives the read, the diff and the admin UI's "inherited from
  environment" badges, so a field cannot be added to one and forgotten in another.
- **Colours are validated by grammar and contrast on write.** Accept only hex or an HSL triplet
  (≤ 64 characters; anything with parentheses, `url(`, `;` or braces is refused). The public identity
  endpoint is unauthenticated — a value like `red;background:url(…)` reaching a raw CSS variable is
  an exfiltration channel. A contrast solver adjusts lightness until both WCAG AA axes pass, or
  refuses with the measured ratios and a passing suggestion.
- **Logos and favicons are files** through the storage layer (§ 16), never URLs typed by an admin.
- **Every write is audited** (old → new, file changes by name) and triggers frontend revalidation of
  the `identity` cache tag, so a save shows immediately rather than after a cache TTL — a delayed
  save is reported as a broken feature.
- **Public exposure is an allow-list** of fields, not the model serialised.

**Django + Next shape.**

```python
class InstallationIdentity(SingletonModel):             # § 16 base: pk=1 CHECK, load(), cache
    display_name  = models.CharField(max_length=80, null=True, blank=True)
    short_name    = models.CharField(max_length=24, null=True, blank=True)
    tagline       = models.CharField(max_length=160, null=True, blank=True)
    support_email = models.EmailField(null=True, blank=True)
    support_url   = models.URLField(null=True, blank=True)
    legal_entity_name = models.CharField(max_length=160, null=True, blank=True)
    terms_url     = models.URLField(null=True, blank=True)
    privacy_url   = models.URLField(null=True, blank=True)
    logo          = models.ForeignKey("core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    brand_colour  = models.CharField(max_length=64, null=True, blank=True)   # validated grammar
    theme_preset  = models.CharField(max_length=32, null=True, blank=True)

    FALLBACKS = {"display_name": "PRODUCT_NAME", "short_name": "PRODUCT_NAME", "tagline": "PRODUCT_TAGLINE"}
```

(`CharField(null=True)` is a deliberate, documented exception to
[`DJANGO_STANDARDS.md`](DJANGO_STANDARDS.md) § 4: here NULL and `""` genuinely mean different things —
"inherit" versus "deliberately empty".)

`GET /api/public/config/` includes `identity` (resolved, allow-listed). `PATCH /api/core/identity/`
requires `settings.settings.manage`. Next: server fetch tagged `identity`, `revalidateTag("identity")`
from a route handler the backend calls on save.

**Enforced by.** `tests/core/test_identity_row.py` — no row renders from env alone; a NULL field
inherits; clearing a field restores the default; a second row violates the constraint; an injected
colour string is refused; every field in `FALLBACKS` is in the public serializer and vice versa.

**Configurable, not hard-coded.** Every column; the fallback env keys `PRODUCT_NAME`,
`PRODUCT_TAGLINE`.

---

## 9. The typed settings registry — **Tier 1 · Core**

**What.** The one mechanism for operator-tunable policy values: **declared in code** by the module
that reads them, **stored** as overrides in one table, **resolved** through a scope cascade into
typed values that never raise, **cached** in the shared cache with a version bump, **audited** on
every change, and **edited** through screens generated from the declarations. It replaces the thin
`core_setting` of [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 3.13 (⚠️ Conflicts #2).

**Why.** Without it, each module builds its own settings table and screen, thresholds stay constants
because changing one needs a migration, and nothing knows what a value means. With a registry that is
only a key/value store, nobody knows the type, the label, the safe default, or whether anything still
reads the key.

### 9.1 Declaration

**Rules.**
- **Settings are declared, not invented at the call site.** `registry.settings.register(...)` from
  `AppConfig.ready()` is the only way a key exists. The UI therefore always knows a label, a type and
  a group.
- **The key is the API contract**: dotted, namespaced, stable — `<namespace>.<group>.<name>`. The
  first segment is the registering app's label; core apps may also use the reserved `platform.` and
  `security.` namespaces. A plugin using another namespace fails the conventions test, exactly like a
  mis-prefixed permission ([`RBAC_DESIGN.md`](RBAC_DESIGN.md)).
- **Keys are literals at every read.** `get_setting(f"billing.{kind}.limit")` is banned — a dynamic
  key defeats every static test in § 9.11.
- **Every declaration carries** `type`, `default` (the safe one), `label` (a sentence),
  `description` (the *consequence* of changing it), `group`, `module`, allowed `scopes`,
  `changed_by_event` (admission rule 1, § 10), `used_by` (the surfaces it governs), and `exposure`
  (`private` · `authenticated` · `public`).
- **No `secret` type exists.** A secret is an integration credential
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)). A settings row is readable by anyone with
  the settings screen and is written to the audit log in clear.
- **No `restart_required` flag exists.** A value that needs a restart to take effect fails admission
  rule 3 and belongs in env.

```python
registry.settings.register(SettingDef(
    key="security.lockout.threshold",
    type=Int(min=3, max=100),
    default=10,
    label="Failed sign-ins before an account is locked",
    description="Lower locks attackers out sooner and locks real people out more often.",
    group="Sign-in protection", module="users", scopes=("platform",),
    changed_by_event="A credential-stuffing wave, or support load from lockouts",
    used_by=("Sign-in", "Password reset"),
))
```

### 9.2 Storage — overrides only

**Rules.**
- **The table stores overrides, not definitions.** Metadata lives in code; a row exists only where an
  admin changed a value at some scope. Absence means "the code default".
- **No seeder writes values, so a reseed cannot reset one.** `sync_settings` validates and reports
  (orphans, rows that no longer coerce); it never writes. This is the strongest form of "never reset
  on reseed": the reseed has nothing to reset with.
- **A changed code default is a behaviour change** for every installation that never overrode it. A
  snapshot test of all code defaults makes it a visible diff that needs an
  [`../UPGRADING.md`](../UPGRADING.md) note (Pending decision #2 records the alternative).
- **Rows for unregistered keys are kept, ignored and reported** — never auto-deleted. A rollback that
  briefly un-registers a key must not lose the admin's value.

| Column | Type | Notes |
|---|---|---|
| `id` | `BigAutoField` | |
| `key` | `CharField(128)`, indexed | Must be registered to be *read*; not enforced by FK |
| `scope_type` | `CharField(16)` | `platform` · `tenant` · `user` |
| `scope_id` | `CharField(64)`, NULL for `platform` | The tenant's or user's **public** id |
| `value` | `JSONField` | **Always `{"v": …}`** — § 9.3 |
| `is_locked` | `BooleanField(False)` | Platform rows only: lower scopes are ignored |
| `updated_by` | FK user, `SET_NULL`, `related_name="+"` | NULL for system writes |
| `updated_at` | `DateTimeField(auto_now=True)` | |

Uniqueness is two **partial** constraints — `(key)` where `scope_type='platform'`, and
`(key, scope_type, scope_id)` otherwise — because a plain unique constraint treats NULLs as distinct,
and partial indexes behave the same on SQLite and PostgreSQL
([ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md)).

### 9.3 The `{"v": …}` wrapper

A bare JSON `false`, `0`, `""` or `null` is indistinguishable, after a round trip through the ORM and
the cache, from "never written" or "the cache miss sentinel". **Every stored value is wrapped**, so
"explicitly set to null" and "no override" are different states, and the cache can store the
*absence* of a row as `{"found": false}` without confusing it with a stored `false`.

### 9.4 Strict coercion — validation and casting in one step

**Rules.**
- `bool` accepts only JSON `true`/`false` from the API; from text (CLI, env prefill) only `true`,
  `false`, `1`, `0`. **`"false"` → `True` is the bug nobody finds until a security control is quietly
  off.**
- `int` rejects Python `bool` (a subclass of `int`); `decimal` accepts strings only, never floats;
  `string` ≤ 1,000 characters by default, `text` ≤ 20,000; `choice` must be in `choices`; `json` is
  validated by the declaration's schema when one is given.
- **`min`/`max` are validated on write and clamped on read.** A row written before a floor existed, or
  by a data migration, cannot bypass it. Retention settings are the canonical case: a fat-fingered
  `0` wipes a table on the next nightly run, and that damage is immediate and unrecoverable.
- **Zero never silently means unlimited.** Where "unlimited" is a legitimate answer it is an explicit
  choice (`None` with a label), and the floor applies to every number.
- **Errors name the setting and the rule** (`400` with the key and the violated bound), using the
  standard error envelope ([`API_PLATFORM.md`](API_PLATFORM.md)).

### 9.5 The scope cascade

Resolution order is **user → tenant → platform → code default**, restricted to the scopes the
declaration allows.

**Rules.**
- **A setting declares its scopes.** A security policy is `("platform",)`; a display preference may be
  `("platform", "tenant", "user")`. A write at an undeclared scope is refused.
- **The tenant step exists only when a tenancy module registers a scope resolver**
  ([`REUSABLE_MODULES.md`](REUSABLE_MODULES.md)). Core never assumes tenancy.
- **A locked platform row stops the cascade.** An operator can pin a value tenants and users cannot
  override — lock, not a second setting.
- **The admin UI always shows where the effective value came from** ("user override", "tenant
  default", "platform", "code default").

### 9.6 Resolution never raises and defaults safe

**Rules.**
- **A reader never raises** for an unreachable database, a down cache, or a row that no longer
  coerces. It logs a warning, increments `setting_resolution_fallback_total{key,reason}`, skips that
  scope and continues down the cascade to the code default. Settings are read from background jobs
  that do not guard the call; they must degrade, not crash.
- **The code default is the safe one** — a switch that enables risk defaults off; a masking mode
  defaults to masking. "Fail closed, never the permissive branch" is part of the declaration's review.
- **An unregistered key raises `UnknownSetting`, always.** Unlike a database row, the registry lives
  in the same process as the caller, so a deploy cannot produce a mismatch — an unregistered read is a
  typo, and § 9.11 catches it before merge. Returning a default for a typo is how a control silently
  does nothing.
- **Modules read a frozen policy object**, not loose keys. The dataclass defaults *are* the code
  defaults, next to the types.

```python
@dataclass(frozen=True)
class LockoutPolicy:                                  # the defaults here ARE the code defaults
    threshold: int = field(default=10, metadata=meta("Failed sign-ins before lockout", min=3, max=100))
    window_seconds: int = field(default=900, metadata=meta("Counting window", min=60))
    duration_seconds: int = field(default=900, metadata=meta("Lockout duration", min=60))

registry.settings.register_group(LockoutPolicy, prefix="security.lockout", module="users",
                                 group="Sign-in protection", scopes=("platform",))

policy = resolve(LockoutPolicy)                       # immutable; never raises; one cached read
```

### 9.7 Caching

**Rules.**
- **Shared cache only.** Values live in the shared cache (Redis — required in production by
  `dbx.E005`/`cfg.E009`) under `settings:{generation}:{scope}:{key}`. A write bumps the generation
  with one `INCR` in `transaction.on_commit` — no key scans, no race with pattern deletes.
- **Never a per-process cache with a TTL.** It is an unbounded staleness window per worker: an admin
  saves, and one worker in eight obeys. "A setting that takes five minutes to take effect is worse
  than one that costs a query."
- **One snapshot per unit of work.** A request-local memo (a `contextvar`) means a request sees one
  consistent value for a key. It is reset by middleware per request **and** by a Celery
  `task_prerun` handler per task — a memo that lives for a worker's lifetime is the per-process cache
  again.
- **Absence is cached; failure is not.** `{"found": false}` is a legitimate cached state. A database
  error is never cached — a cached failure makes the setting look broken with no query to inspect.
- **Cache down ⇒ read the database.** Generation unavailable means "no cache", never "stale cache".

### 9.8 Writes and audit

**Rules.**
- **One writer:** `core.settings_service.set_value(key, value, *, scope, actor, reason="")`. The
  view, the CLI (`manage.py set_setting`) and data migrations all call it.
- **Every change writes `ActivityLog`** verb `core.setting.changed` with `meta={"key", "scope",
  "old", "new"}` — old **and** new, so the audit answers "what was it before?" without a second
  table ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)).
- **No create and no delete endpoints.** Rows appear only for registered keys. "Reset to default" is
  its own audited action that removes the override row.
- **Permissions:** `settings.settings.view` and `settings.settings.manage`
  ([`RBAC_DESIGN.md`](RBAC_DESIGN.md) already names the latter). User-scope preferences are written by
  the user through their own profile endpoint, which may only touch keys declaring the `user` scope.

**Endpoints.**

| Method | Path | Does |
|---|---|---|
| `GET` | `/api/core/settings/?module=&group=` | Declarations + effective value + source scope + last change |
| `PATCH` | `/api/core/settings/<key>/` | `{value, scope?}` → validated write |
| `POST` | `/api/core/settings/<key>/reset/` | Removes the override at a scope |
| `GET/PATCH` | `/api/users/me/preferences/` | The caller's own `user`-scope keys only |

### 9.9 Namespace screens answer 404 outside their namespace

A focused screen — "Security" over `security.*` — is a filtered view of the same service with its
own permission. **Its endpoint checks `key.startswith(prefix)` and answers `404` for any other key.**
Without that guard, the Security screen's endpoint is a second write path to every setting in the
product under a different permission. `404`, not `403`: from that screen's point of view the key does
not exist.

### 9.10 Screens generated from declarations

The admin UI renders an editor per `type` (toggle, number with bounds, select, text area, JSON editor
with schema), groups by `module › group`, and shows: label, description, the code default, the
effective value and its source scope, **`used_by` with live counts where a usage callable is
declared**, who changed it last and when. Next: one `<SettingsForm module=…>` in
`frontend/src/core/settings/`, driven by `GET /api/core/settings/`. No module hand-writes a settings
screen.

### 9.11 A setting nothing reads is a defect

**Why.** A threshold was editable for months with zero readers while the user guide described its
effect. A control that saves and does nothing teaches an admin that the screen is decorative — and
that lesson transfers to the controls that do work. It also implies a protection that does not exist.

**Rules.**
- **Every declared key has at least one reader that is not the settings screen.**
- **The reader lives with the thing it describes and is shared.** Screens render the verdict (e.g.
  "stale") from the owning service; they never re-derive it from the raw setting.
- **Withdrawal** deletes the declaration and its readers in one change. The override rows remain,
  ignored and reported by `settings_doctor`, removable only by an explicit command.

### 9.12 One policy, one switch, many windows

**Never duplicate a setting to give a module "its own" copy.** Duplicated switches diverge silently
and fail at cutover. A screen that edits a shared switch names the other surfaces it governs, from
`used_by`, with the sentence *"This is not a setting for this module only."* — otherwise an admin
changes the live product from an unreleased module's screen.

### 9.13 Job state is not configuration

Resume cursors and last-processed markers live in `core_job_state`
([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)), never in `core_setting`. Consumers own their
encoding and treat an unparseable value as "no state".

### 9.14 Moving a value from env to the registry

1. Declare the setting with the env value's current default.
2. Mark the env key `retired=True, moved_to=…` in `core/env_schema.py` (§ 6).
3. Prefill once from env where it was set (§ 16), never overwriting.
4. Delete the `env(...)` read **and** every `settings.X` read in the same change.
5. Add the old name to the retired-reads list in `test_moved_settings_not_read` (§ 18), so it cannot
   quietly return.

**Django + Next shape (summary).** `core/settings_registry.py` (`SettingDef`, types, `register`,
`register_group`), `core/settings_service.py` (`get_setting`, `resolve`, `set_value`, `reset`),
`core/models/setting.py`, `core/api/settings.py` (list/retrieve/partial_update + `reset`),
`manage.py settings_doctor` (orphans, unread keys, rows failing coercion, env keys shadowed), frontend
`frontend/src/core/settings/`, `useSetting(key)` for `authenticated`/`public` keys delivered in the
bootstrap.

**Enforced by.**
- `tests/core/test_settings_registry.py` — wrapper round trip for `false`, `0`, `""`, `null`;
  `sync_settings` twice writes nothing; strict coercion table (`"false"` refused for `bool`, `True`
  refused for `int`, floats refused for `decimal`); a row below `min` is clamped on read; resolution
  with the database unavailable returns the code default and increments the fallback metric; an
  unregistered key raises; the cascade honours declared scopes and `is_locked`; every write produces
  one `ActivityLog` row with old and new.
- `tests/core/test_settings_namespace_guard.py` — the Security endpoint answers `404` for a
  `billing.*` key, even for a superuser.
- `tests/architecture/test_settings_are_read.py` — AST-walks `backend/` (and `frontend/src/` for
  `useSetting("…")`): every registered key is read somewhere other than the settings app, **and** every
  literal key read is registered; dynamic keys fail. Shrink-only baseline
  ([`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md)).
- `tests/core/test_setting_defaults_snapshot.py` — the code defaults match a committed snapshot; a
  change is a reviewed diff.
- `tests/architecture/test_plugin_conventions.py` — a plugin's keys start with its label.

**Configurable, not hard-coded.** This *is* the mechanism. Its own knobs are none: the cache scheme
and coercion rules are code.

---

## 10. The admission test — what earns a setting — **Process**

**What.** Seven rules a value must pass before it may appear on a settings screen. They are how the
non-goal *"few knobs"* is kept without re-arguing every value in every session.

**Why.** An audit of one mature codebase found about twenty hard-coded values; without a test for
admissibility, every session re-argued every one, and screens accreted switches nobody chose.

**The seven rules.** A value becomes a registry setting only if **all** hold:

| # | Rule | Fails when |
|---|---|---|
| 1 | **A real, nameable event changes the right answer** | Nobody can name when an admin would change it. `changed_by_event` in the declaration is the evidence |
| 2 | **The admin is the authority** | The right answer is decided by law, a contract or the code's own correctness |
| 3 | **Changing it changes nothing else** — no deploy, migration, restart or upstream coordination | Then the setting is theatre; it belongs in env or code |
| 4 | **A wrong value is visible and reversible** | A wrong value silently destroys data — then it needs a floor (§ 9.4) or is not a setting |
| 5 | **It is policy, not mechanism** | It tunes an implementation detail only an engineer understands (pool sizes, internal batch sizes) |
| 6 | **It does not gate access** | A permission, a boundary or a tenant fence. Access belongs on a route or permission **the constrained party cannot move**. A feature flag is fine; an access boundary is not |
| 7 | **List-shaped vocabularies are edited by label, never key** | Then it is a lookup (§ 14), not a setting |

**Not reasons:** "it is a magic number", "it could be configurable", "another product might want it"
(then it is a product's setting, not core's), "the admin asked for a switch" without an event.
**One fact = one setting** (§ 9.12). **Presentational values** belong to design tokens.

**Where a rejected value goes instead.**

| Rejected because | Put it |
|---|---|
| Nothing changes it | A named constant with a comment saying why it is not configurable |
| It needs a restart or a deploy | Env, with a schema entry (§ 6) |
| It is list-shaped | A lookup (§ 14) |
| It gates access | A permission ([`RBAC_DESIGN.md`](RBAC_DESIGN.md)) |
| It is temporary | A feature flag (§ 11) |
| It is presentational | A design token ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)) |

**Django + Next shape.** The PR template gains one line: *"New setting? Name the event that changes
its value."* — the same text the declaration's `changed_by_event` carries.

**Enforced by.** `SettingDef` refuses registration with an empty `changed_by_event` or `description`;
the "unread setting" test (§ 9.11) removes switches that survive admission but never got a reader.

**Configurable, not hard-coded.** Not applicable — this is a review rule.

---

## 11. Feature flags — **Tier 1 · Core**

**What.** One registry of **temporary** gates on code paths: declared in code with an owner and an
expiry, toggled and targeted by an admin, resolved with a fixed kill-switch-first rule, exposed to the
frontend in the bootstrap, and deleted when the launch is done.

**Why.** Four overlapping mechanisms existed in one product: build-time public env booleans for UI
whose API did not exist yet (a rebuild to flip), backend env booleans exposed through half a dozen
ad-hoc "is this enabled?" endpoints each fetched separately by the layout, a per-organisation
capabilities endpoint, and a hand-edited launch-state file that existed because code could not see
what production had on. A feature went live while its help article stayed dark because nobody edited
the file. **One registry, read by nav, pages, help and the API alike, is the fix.**

**Rules.**
- **Resolution order is the contract:**
  1. **Unregistered key ⇒ off, always.** There is no `default=True` parameter anywhere — a deleted
     flag must never switch a feature back on.
  2. **No row yet ⇒ off.** Release flags start dark.
  3. **`enabled = false` ⇒ off for everyone, targets included.** "Disabled except for the people I
     listed" would make an incident unrecoverable: the kill switch must beat every target.
  4. **Enabled with no targeting ⇒ on for everyone.**
  5. **Enabled with targeting ⇒ on only for a matching user, role or tenant;** anonymous callers
     match nothing. **Targeting narrows who a live flag reaches; it never switches a flag on.**
  6. `NULL` and `[]` targeting are identical.
- **Flags are temporary; permanent switches are settings.** Every flag declares `owner` and
  `expires_on`. A permanent operational kill switch ("stop all outbound writes to provider X") is a
  registry `bool` setting or a guard mode, because it never expires and needs a label, not an owner.
- **A flag past `expires_on` fails CI.** Removing a flag means deleting the declaration and the dead
  branch in one PR; extending it means editing `expires_on` in review, where someone asks why.
- **Ship dark.** New risky behaviour lands behind a flag, default off; merging and launching are
  decoupled. The rollout is written as plan rows: deploy dark → backfill → verify → flip → soak →
  remove the flag.
- **A flag gates whether new code *runs*, not whether it *loads*.** Migrations run, imports execute,
  module-level code executes. A broken migration is not mitigated by a flag. A flagged task body
  returns **before** opening a database session or an external client.
- **Unreleased features are undiscoverable.** A route behind an off flag answers `404`, not `403`.
  The bootstrap lists only flags that are **on for this caller** — never the full catalogue of
  unreleased names.
- **Every write is audited** (created · toggled · targeting changed), with `settings.flags.view` and
  `settings.flags.manage` as separate permissions.
- **One registry replaces the rest.** No `NEXT_PUBLIC_FF_*`, no `*_ENABLED` env booleans for product
  features, no per-feature "enabled" endpoints, no launch-state files. Infrastructure switches that
  are deployment facts (`ADMIN_ENABLED`) stay env, because they are rung 1, not flags.
- **Percentage rollouts are out of scope for now** (Pending decision #6). Targeting by role, user and
  tenant covers staged rollout without the determinism questions a percentage raises.

**Django + Next shape.**

```python
registry.flags.register(FlagDef(
    key="billing.new_invoice_screen", owner="billing-team",
    expires_on=date(2026, 12, 31), description="Replaces the invoice list with the new DataTable.",
))
```

```python
def flag_enabled(key: str, *, user=None, tenant=None) -> bool:
    if key not in registry.flags:
        return False                                  # unknown ⇒ off; no default parameter exists
    row = cached_flag_row(key)                        # same generation-bump cache as § 9.7
    if row is None or not row.enabled:
        return False                                  # dark until written; kill switch beats targets
    if not (row.user_ids or row.role_slugs or row.tenant_ids):
        return True
    if user is None or not user.is_authenticated:
        return False
    return (user.public_id in (row.user_ids or []) or bool(set(user.role_slugs) & set(row.role_slugs or []))
            or (tenant is not None and tenant.public_id in (row.tenant_ids or [])))
```

- Model `core_feature_flag(key unique, enabled, user_ids JSON, role_slugs JSON, tenant_ids JSON,
  updated_by, updated_at)` — owner, description and expiry live in the code declaration.
- DRF: `RequiresFlag("billing.new_invoice_screen")` permission class answers `404` when off.
- Bootstrap: `/api/auth/me/` gains `"flags": ["billing.new_invoice_screen"]` (on-for-me only).
  Frontend `useFlag(key)` returns `false` while loading, on error and for unknown keys; nav items
  declare `flag` and are hidden when off ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)).
- `manage.py flags_doctor` — flags past expiry, flags whose key no longer appears in code, rows for
  unregistered keys.
- Admin screen: `/settings/flags` — state, targeting, owner, expiry, days remaining.

**Enforced by.**
- `tests/core/test_feature_flags.py` — pins all six resolution rules, including "disabled with
  targets is off for the targets" and "unknown is off".
- `tests/architecture/test_no_expired_flags.py` — fails when today is past any `expires_on`; proven to
  fail with a fixture flag dated yesterday.
- `tests/architecture/test_single_flag_mechanism.py` (§ 18) — no `NEXT_PUBLIC_FF_`, no env-read
  `*_ENABLED` for product features outside the infrastructure allow-list.
- `tests/core/test_flagged_route_404.py` — a flagged route is `404` when off and routes normally
  when on.

**Configurable, not hard-coded.** State and targeting (DB); owner and expiry (code, reviewed).

---

## 12. Capabilities — **Tier 2 · Core**

**What.** A named, resolved answer to "is this product surface *available* here?" — installed,
configured and allowed by policy — with a **declared failure direction per capability**. Distinct
from a flag (temporary, about code) and from a permission (about a person).

**Why.** Customer organisations on a "manual, no integration" arrangement must not see payment,
invoice or identity-verification surfaces; platform users must not see a flash of "feature missing"
while the answer loads. The same product then shipped one capability — self sign-up — failing open,
and missing configuration opened sign-up where it should have been closed.

**Rules.**
- **Each capability declares `fail_mode`.** `fail_open` capabilities only hide UI: while loading or
  on error, show. `fail_closed` capabilities widen access (sign-up, public sharing): missing data
  means `false`. The mode ships in the payload, so the frontend never guesses.
- **Hint versus authority.** A pre-auth *hint* rides on `/api/public/config/` (host- or
  installation-scoped); the post-auth *authority* rides on `/api/auth/me/`. **The backend enforces
  regardless** — a capability in the UI is a courtesy, like a permission code.
- **Installed-but-disabled plugins resolve to unavailable** through the soft-disable mechanism in
  [`EXTENSIBILITY.md`](EXTENSIBILITY.md); a capability for an absent plugin does not exist.
- **Resolvers are callables evaluated at request time**, never values captured at boot — the
  registry is populated before the database is safe to read.

**Django + Next shape.** `registry.capabilities.register(CapabilityDef(key, resolver, fail_mode,
exposure))`; bootstrap field `capabilities: {key: {available: bool, fail_mode}}`; frontend
`useCapability(key)` honours `fail_mode`.

**Enforced by.** `tests/core/test_capabilities.py` — a `fail_closed` capability whose resolver
raises is `false`; a `fail_open` one is `true` in the UI hint and still refused by the backend
endpoint; `useCapability.test.tsx` mirrors both directions while loading and on error.

**Configurable, not hard-coded.** Resolvers read settings, credentials and plugin state; no
capability list is written in core.

---

## 13. Guard modes — `off|log_only|enforce` — **Tier 1 · Core**

**What.** Every new *refusal* introduced into a system that already has traffic is a registered guard
with a mode setting — `off`, `log_only` or `enforce` — whose shipped default reproduces today's
behaviour. Tightening is a later, deliberate, evidence-based admin action.

**Why.** A security plan sat unbuilt for fifteen months because it was framed as a behaviour change
nobody would approve. Reframed as "every control ships at today's behaviour, and a test proves
installing it changes nothing", it shipped. `log_only` then let the team *observe* what a guard would
have blocked before it blocked anything.

**Rules.**
- **Scope — guards added to live traffic.** The guards specified from day one in
  [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) (default-deny, the elevated-role guard, the last-superuser
  guard) **enforce from the first commit**: there is no prior behaviour to preserve, and downgrading
  them to `log_only` in the name of this section would be a regression. This section governs refusals
  added *after* a product is running.
- **Shipped default = today's behaviour** — `off` or `log_only`. `enforce` as a default needs a
  written reason in the declaration: a guard closing a *known vulnerability* is not "today's behaviour
  worth preserving".
- **`log_only` does the full evaluation**, writes `guard.would_block` to `ActivityLog` with the context,
  increments `guard_decisions_total{guard,mode,outcome}`, and lets the request through.
- **`enforce` refuses with a stable error code** from the error catalogue
  ([`API_PLATFORM.md`](API_PLATFORM.md)) and writes `guard.blocked`.
- **The settings screen shows the evidence next to the switch:** would-block count for the last 7 and
  30 days. Moving to `enforce` with a non-zero count is a decision someone can see they made.
- **An unreadable mode resolves to the declared default,** and the default direction is chosen per
  guard: a CSP header fails *open* when settings are unavailable (a missing header is today's
  behaviour; failing closed would take the product down), while an *audit-only* guard defaults **on**
  when its row is missing (it only writes rows, and a missing row must not switch the audit off).
- **Audit-only controls ship on.** A control whose only effect is writing an audit row (for example,
  "log every time a person reveals a credential") changes no user-visible behaviour and has no reason
  to be off.

**Django + Next shape.**

```python
registry.guards.register(GuardDef(
    key="rbac.grant_beyond_actor", default_mode="log_only",
    description="Refuse granting a role a permission the acting user does not hold.",
    error_code="authz.grant_beyond_actor",
))

def check_guard(key: str, violated: bool, **context) -> None:
    if not violated:
        return
    mode = guard_mode(key)                       # registry setting "<key>.mode"; unreadable ⇒ default
    if mode == "off":
        return
    record_guard(key, mode, context)             # ActivityLog + metric, never raises
    if mode == "enforce":
        raise GuardRefused(key)                  # mapped to the catalogued error code
```

`GuardDef` registers its `<key>.mode` setting automatically (type `choice`, the three modes), so a
guard cannot exist without a switch and a label.

**Enforced by.**
- `tests/architecture/test_shipping_guards_changes_nothing.py` — every registered guard's default is
  not `enforce` unless it carries an `enforce_reason`; **and** for each guard, its positive control:
  the flow it would block succeeds under shipped defaults. Proven to fail by flipping one fixture
  guard's default.
- `tests/core/test_guard_modes.py` — `off` records nothing; `log_only` records and passes; `enforce`
  records and refuses with the declared code; an unreadable mode uses the declared default.

**Configurable, not hard-coded.** Each guard's mode (registry setting `<guard>.mode`).

---

## 14. Admin-editable lookups — **Tier 1 · Core**

**What.** One generic model for list-shaped vocabularies admins maintain — sources, reasons,
categories — with a **stable key admins cannot reach** and an **editable label** hanging off it.
Membership is validated **from the table at request time**; values are **deactivated, never deleted**.

**Why.** A table whose *label was the stored value* broke three ways at once: a rename split dashboard
categories into two rows (both percentages individually correct and jointly misleading), dropped
records from exact-match filters, and leaked the old word into an external system's logs forever.
Separately, hard-coded category enums meant adding a category needed a deploy.

**Rules.**
- **A vocabulary becomes admin-editable only once it has a stable key.** The key is a slug set at
  creation, `editable=False`, and never in a writable serializer field. Admins edit the label, the
  order and whether it is active.
- **A stable key is required exactly when something persists a reference** — a record stores it, a
  report groups by it, an external system receives it. Prompt-suggestion chips copied into a text box
  and forgotten do not need one.
- **Membership comes from the table, at request time.** Never a literal list in a serializer, never
  Django `choices=` for an admin-editable vocabulary.
- **Deactivate, not delete.** A deactivated value cannot be chosen for new or changed data; **records
  already holding it stay valid** (grandfathered) and still display their label.
- **Code enum or lookup?** If code *branches* on the value (a state machine, a workflow step), it is a
  `TextChoices` enum owned by code. If only people read it, it is a lookup. A lookup value code must
  refer to (an "other — please specify" entry) is `is_system=True`: it cannot be deactivated and its
  key is referenced by a constant.
- **Seeding never overrides an admin.** `sync_lookups` inserts missing seed keys only — never
  relabels, never reactivates, never deletes. The same "declared in code, never reset" rule as § 9.
- **Label changes are audited.** Keys never change, so there is nothing else to audit.
- **Core holds only platform vocabulary.** A vocabulary two plugins share is declared by the one that
  owns the concept and read by the other through a contract ([`EXTENSIBILITY.md`](EXTENSIBILITY.md)) —
  never promoted into core because it was convenient. § 18 bans product vocabulary in core.
- **Label translation is deferred** (Pending decision #7); the model keeps one `label` today.

**Django + Next shape.**

```python
class LookupValue(models.Model):
    set_key    = models.CharField(max_length=64, db_index=True)    # "crm.lead_source" — declared in code
    key        = models.SlugField(max_length=64, editable=False)    # stable; what records store
    label      = models.CharField(max_length=128)                   # what admins edit
    sort_order = models.PositiveIntegerField(default=0)
    is_active  = models.BooleanField(default=True)                  # deactivate, never delete
    is_system  = models.BooleanField(default=False)                 # code refers to it by key
    meta       = models.JSONField(default=dict, blank=True)         # validated by the set's schema

    class Meta:
        db_table = "core_lookup_value"
        constraints = [models.UniqueConstraint(fields=["set_key", "key"], name="core_lookup_value_uq")]
```

```python
class LookupField(serializers.SlugRelatedField):
    def __init__(self, set_key, **kw):
        super().__init__(slug_field="key", queryset=LookupValue.objects.filter(set_key=set_key), **kw)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)                 # membership from the TABLE, now
        current = getattr(getattr(self.parent, "instance", None), self.source, None)
        if not value.is_active and value != current:            # grandfather what the record holds
            self.fail("does_not_exist", slug_name="key", value=data)
        return value
```

- Records reference `LookupValue` by FK with `on_delete=PROTECT` (deletion is impossible by
  construction), or store the key string where the record must outlive the vocabulary.
- `registry.lookups.register(LookupSetDef("crm.lead_source", label="Lead source",
  seed=[("web", "Website"), ("referral", "Referral")], admin_can_add=True, meta_schema=None))`.
- `GET /api/core/lookups/?set=` for any authenticated user (cached with the generation scheme);
  `PATCH` behind `settings.lookups.manage`. Next: `useLookup(setKey)` feeding selects and filters.
- A data-plane check: every declared set has at least one active value
  ([`OBSERVABILITY.md`](OBSERVABILITY.md)) — an empty required vocabulary makes a form unsubmittable,
  and config in rows has no schema to fail loudly.

**Enforced by.**
- `tests/core/test_lookups.py` — the key is not writable through the API; a deactivated value is
  refused on create, accepted unchanged on update of a record already holding it, and refused as a
  *change* to it; `sync_lookups` never relabels an admin-edited row or reactivates a deactivated one;
  deleting a referenced value raises `ProtectedError`.
- `tests/architecture/test_no_choices_for_lookups.py` — no model field referencing a declared lookup
  set also declares `choices=`.

**Configurable, not hard-coded.** Every vocabulary's values and labels (DB); the set declarations and
seed keys (code).

---

## 15. Locale, currency, timezone and formats — **Tier 1 · Core**

**What.** Locale, timezone, currency and display formats are **registry settings at platform, tenant
and user scope**, delivered to the frontend in the bootstrap, and applied by **one formatter home** on
each side. Storage is UTC; the API speaks ISO-8601.

**Why.** Every product on this core will have a different answer. Codebases that assumed one market
wrote that market's locale into their standards: every formatter pinned to one locale, a default
currency substituted for a missing one "so it never throws", a scheduler constant set to one zone, a
database server started with a fixed offset, and the frontend test runner pinned to one timezone — so
the suite could not catch a timezone bug even in principle. Another returned *display-formatted*
strings from its API, which every machine consumer then had to parse back.

**Rules.**
- **Store UTC.** `USE_TZ=True` and `TIME_ZONE="UTC"` (the current `settings.py` is already right —
  keep it). The database server's own timezone is UTC too; a readiness check verifies it
  ([`OBSERVABILITY.md`](OBSERVABILITY.md)).
- **The API returns ISO-8601, never display strings.** Datetimes as `2026-09-29T14:03:00Z`; dates as
  `2026-09-29`; durations as seconds or ISO durations; money as `{"amount": "12.50", "currency": "EUR"}`
  ([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md)). Formatting is the client's job.
- **The settings.**

  | Key | Type | Scopes | Default |
  |---|---|---|---|
  | `platform.locale` | BCP-47 tag | platform · tenant · user | `en` |
  | `platform.timezone` | IANA zone, validated against `zoneinfo.available_timezones()` | platform · tenant · user | `UTC` |
  | `platform.currency` | ISO-4217 code | platform · tenant | **none** |
  | `platform.country` | ISO-3166 alpha-2 | platform · tenant | **none** |
  | `platform.date_style` / `platform.time_style` | `locale` · `short` · `medium` · `long` | platform · tenant · user | `locale` |
  | `platform.week_start` | `locale` · `monday` · `sunday` · `saturday` | platform · tenant · user | `locale` |

- **No default currency and no default country.** Every possible default is one market's assumption.
  The first-run wizard asks ([`OPERATIONS.md`](OPERATIONS.md)); until set, money renders as the bare
  ISO code with the amount, and a data-plane warning says "currency not configured". **A missing
  currency is never silently replaced** — substituting a default "so it never throws" is how an
  amount gets shown in the wrong money.
- **`locale` is a neutral default**; `UTC` is not a market. Styles default to `locale` so the
  formats follow the locale unless an admin chooses otherwise.
- **The viewer's settings, not the actor's or the server's.** A page renders in the *viewer's*
  timezone and locale; an email or PDF renders in the *recipient's*. Business hours, quiet hours and
  schedules name a timezone setting explicitly and never use server local time
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md), [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md)).
- **One formatter home per side.** Frontend: `frontend/src/core/format/` — `formatDate`,
  `formatDateTime`, `formatTime`, `formatRelative`, `formatNumber`, `formatMoney`, `formatBytes`, all
  reading the locale context from the bootstrap. Backend: `core/formatting.py` for the few
  server-rendered surfaces (emails, PDFs, CSV exports).
- **Date and datetime are different types with different formatters, and each refuses the other.**
  - Backend: calling a datetime formatter on a `date` fails deep inside timezone conversion
    (`date` has no `utcoffset`). With every date field nullable, the crash sat latent until a field
    was first populated. `format_date(value: date)` and `format_datetime(value: datetime)` check
    their argument's type and raise a clear `TypeError` immediately.
  - Frontend: `new Date("2026-09-29")` parses as **UTC midnight**, which renders as the previous day
    in any negative-offset timezone. `formatDate` takes the `YYYY-MM-DD` string and formats it with
    `timeZone: "UTC"`; it never converts a date-only value into the viewer's zone.
- **Formats reach every control through the shared context** — a date picker in a plugin's modal
  formats like the table behind it, with no per-view prop to forget.
- **Catalogue-ready, not catalogued.** No string concatenation around formatted values (`"Due " +
  date` becomes a template with a placeholder), so adding translations later is additive
  ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) owns i18n rendering).

**Django + Next shape.** `/api/auth/me/` gains `locale: {locale, timezone, currency, country,
dateStyle, timeStyle, weekStart}` resolved through the cascade for this user; `/api/public/config/`
carries the platform defaults for signed-out pages. `core/middleware.py::TimezoneMiddleware`
activates the resolved zone per request for the server-rendered paths, falling back to UTC on an
invalid value rather than failing the request.

**Enforced by.**
- `tests/architecture/test_no_locale_literals.py` (§ 18) — no ISO-4217 code, no IANA zone other than
  `UTC`, no BCP-47 locale literal in production code outside the settings layer.
- **ESLint:** `no-restricted-syntax` bans `toLocaleString`, `toLocaleDateString`,
  `toLocaleTimeString` and `new Intl.*` outside `src/core/format/`, and bans declaring any function
  named `format(Currency|Money|Amount|Price|Date|Time|Number|Bytes|Size)*` outside it.
- `tests/core/test_formatting.py` — `format_datetime(date)` and `format_date(datetime)` both raise
  `TypeError`; API serializers emit ISO-8601 for every date and datetime field (a schema walk).
- **The frontend suite runs twice in CI, under `TZ=UTC` and under a negative half-hour-offset zone
  (for example `America/St_Johns`).** A date that shifts by a day fails one of the two runs; a suite
  pinned to one zone cannot catch that class of bug at all.

**Configurable, not hard-coded.** Every key in the table above, at its declared scopes.

---

## 16. Runtime configuration in the database — env as prefill — **Tier 2 · Core**

**What.** Configuration an operator changes after the process has started — storage connections, the
outbound mail transport, sign-in providers, identity — lives in the database. Environment variables
**only prefill** a fresh install and are then ignored. Cohesive groups of such config use one generic
singleton base; scalar policy uses the registry (§ 9).

**Why.** Django reads settings once, at import. Anything read after startup from `settings` is frozen
for the life of the process, and staging and production run the same image, so an env-only switch
"could not differ between them without a rebuild". One codebase moved from env-only storage
configuration to database configuration and superseded its own earlier decision to do so; the same
codebase then let every integration invent its own singleton model — around eleven — each with a copy
of the same `get_or_create` service.

**Rules.**
- **Registry first.** A scalar policy value is a registry setting. A singleton row is only for a
  *cohesive* group that is saved and tested together (a storage connection: endpoint, bucket, region,
  credential reference).
- **One base, `core.SingletonModel`:** `CheckConstraint(pk=1)`; `load()` returns the row or unsaved
  defaults without writing; every field nullable with **NULL = fall back to the env value**, driven
  by one `FALLBACKS` map; save bumps the cache generation; every write audited; registered in
  `registry.install_config` (§ 17).
- **Secrets in a singleton are references to the credential store**, never columns in the row
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).
- **Prefill is once, and never overwrites.** `manage.py prefill_from_env` copies env values into
  *empty* fields only; idempotent; run by `setup.sh` and by the first-run wizard. After that,
  `validate_env` reports prefill keys as "set but ignored" (§ 6).
- **Connectivity tests before commit.** Every singleton's admin form offers a real round trip (send a
  test message, put/get/delete a test object) before saving ([`OPERATIONS.md`](OPERATIONS.md) owns the
  wizard's use of the same probes).
- **No cross-environment fallback.** A development process never resolves production configuration
  "because the local row was empty" — convenience fallbacks that route development traffic to
  production are exactly how a laptop sends real mail.

**Example — a storage backend resolved from the database per operation.** `STORAGES["default"]`
points at a proxy that owns no configuration and resolves the real backend on each file operation.

```python
class DatabaseConfiguredStorage(Storage):
    def _backend(self) -> Storage:
        cfg = storage_config_summary()               # shared cache: {backend, prefix, fingerprint} — NEVER secrets
        if cfg is None:                               # DB unreadable (mid-migrate) or not configured
            return env_configured_storage()           # the deployment default from env
        inst = _INSTANCES.get(cfg.fingerprint)        # per-process, keyed by config fingerprint
        if inst is None:
            inst = _INSTANCES[cfg.fingerprint] = build_backend(load_storage_config())   # secrets read here only
        return inst

    def _save(self, name, content):  return self._backend()._save(name, content)
    def _open(self, name, mode="rb"): return self._backend()._open(name, mode)
    # … every Storage method delegates the same way
```

- **Saving the row bumps the generation, so every worker rebuilds** on its next operation — no
  restart.
- **The shared cache never holds the secret**; each process reads credentials into memory only when
  the fingerprint changes.
- **Cold database ⇒ the env-configured default, never local disk in production.** The pattern this
  generalises fell back to the filesystem; in a production-like environment that silently writes
  files into a container that will be recycled, so there the fallback is the env backend or an honest
  `503 storage_unavailable` — local filesystem only in development.
- **A key prefix per environment** lets one bucket serve several environments safely.
- Presigned URLs, private buckets and upload validation are
  [`API_PLATFORM.md`](API_PLATFORM.md)'s.

**Django + Next shape.** `core/models/singleton.py` (`SingletonModel`), `core/storage.py`
(`DatabaseConfiguredStorage`), `core/management/commands/prefill_from_env.py`, admin forms generated
the same way as § 9.10 with an "inherited from environment" badge on NULL fields.

**Enforced by.**
- `tests/core/test_singleton.py` — a second row violates the constraint; `load()` on an empty table
  writes nothing; a NULL field returns the env value; `prefill_from_env` twice changes nothing and
  never overwrites a set field.
- `tests/core/test_storage_proxy.py` — a config save makes the next operation use a new backend
  without restart; the cached summary contains no credential field; with the database unavailable in
  a production-like environment, the proxy never returns a filesystem backend.
- `tests/architecture/test_moved_settings_not_read.py` (§ 18) — once moved to the database, a value
  is not read from `django.conf.settings` by production code.

**Configurable, not hard-coded.** Every singleton field (DB), each with its env prefill key.

---

## 17. Restore and environment separation — **Tier 2 · Core**

**What.** The configuration half of restoring one environment's data into another: the target keeps
**its own** connections, schedules, flags and credentials; the source's are neutralised. The
procedure — backups, `restore.sh`, verification — is [`OPERATIONS.md`](OPERATIONS.md)'s; this section
owns what configuration must survive it and how modules declare theirs.

**Why.** Environments shared one encryption key. A production dump loaded into staging therefore
carried *working* credentials to production's storage bucket, chat workspace and upstream providers —
**with the scheduler running**. A restored box's single sign-on also broke, because the source's
redirect URIs belonged to the source host.

**Rules.**
- **Separate encryption keys per environment.** A production dump restored into staging then cannot
  decrypt production's secrets. **Decryption failure raises** — a decrypt helper that returns the
  ciphertext on failure makes an unusable secret look configured
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).
- **Modules declare their configuration kind** so the snapshot needs no hand-maintained model list:
  `registry.install_config.register(Model, kind=…)`.

  | Kind | On restore | Examples |
  |---|---|---|
  | `singleton` | **Target's snapshot wins**, matched by natural key | Identity row, storage connection |
  | `setting` | Target's snapshot wins, matched by `(key, scope_type, scope_id)` — never by pk | `core_setting`, `core_feature_flag` |
  | `scoped` | Incoming rows **neutralised** (sync off, endpoint and credential cleared); target rows reinstated only where their parent survived | Per-site connector config |
  | `schedule` | **Everything incoming switched off**; the target's schedule written back exactly | Periodic tasks, automation rules |
  | `credential` | Incoming dropped; target's reinstated | The credential store |

- **Lookups are data, not configuration.** Records reference them, so they come from the source.
- **An environment stamp.** `core_installation(environment, key_fingerprint)` records which
  environment last wrote the database and a fingerprint of its encryption key. A readiness check
  warns when the stamp disagrees with the running process ("this database was written by production")
  — the cue to run `config_snapshot load` and `post_restore`.
- **Non-production never sends.** The outbound guard is the second line
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).

**Django + Next shape.** `manage.py config_snapshot dump` before the drop, `config_snapshot load`
after migrations, then `manage.py post_restore` publishing `core.restore_completed` so modules drop
caches keyed to vanished rows (handlers idempotent; failures are warnings but set the exit code).

**Enforced by.** `tests/core/test_config_snapshot.py` — a snapshot round trip keeps the target's
singleton, settings and flags; incoming schedules are all disabled; incoming scoped rows are
neutralised; a model holding encrypted fields that is not registered in `install_config` fails a
registry-completeness test.

**Configurable, not hard-coded.** Declarations per module; nothing enumerated in the command.

---

## 18. The anti-hard-coding tests — **Tier 1 · Core** · **Process**

**What.** The tests that make "nothing hard-coded" fail a build. Each is a source-walking test in
`backend/tests/architecture/` (AST, not regex, wherever the language allows) or a frontend
ESLint/vitest rule, with a shrink-only baseline for pre-existing hits
([`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md)).

**Why.** A rule that is only written down is already half-broken ([`../VISION.md`](../VISION.md)
principle 2). One codebase's written standard for "no hard-coded values" used, as its own example, a
constants file of hard-coded admin role names.

**Rules.**
- **Every test must be proven to fail** — a fixture file containing the forbidden pattern, run once,
  red, then removed or kept as a negative fixture.
- **Allow-lists live in the test with a reason per entry**, and each file's header says *"do not add
  an exception without one."*
- **Scope is production code**: `backend/core/`, `backend/project/`, `backend/plugins/*/`,
  `frontend/src/`. Tests, fixtures, seed data and migrations are excluded by path, not by comment.

| Test | Asserts | How |
|---|---|---|
| `test_no_locale_literals` | No ISO-4217 code, no IANA zone except `UTC`, no BCP-47 locale tag in string constants outside `config/settings/` and `core/formatting.py` | AST string constants vs `zoneinfo.available_timezones()` (stdlib) and a committed ISO-4217 list in `core/data/iso4217.txt`; frontend twin in vitest |
| `test_no_role_name_literals` | No `has_role("…")`, `role.name == "…"`, `Role.objects.get(name=…)`, `groups__name=` outside `rbac/seeding.py` and migrations. Roles are classified by column (`is_system`, `is_elevated`), never by name | AST call and compare nodes. A new external role must be a row, not a missed name comparison that quietly returns false |
| `test_env_reads` | `os.environ`, `os.getenv`, `environ.Env`, `env(` only in `config/settings/`; stricter for secret-shaped names (`*KEY`, `*SECRET`, `*TOKEN`, `*PASSWORD`) — management commands and scripts included | AST; frontend: `process.env` only in `src/core/config/server.ts` and `next.config.ts` |
| `test_environment_predicate` | No `settings.DEBUG` in a conditional outside `config/settings/`; no `APP_ENV` comparison outside `core/env.py` | AST |
| `test_no_product_vocabulary_in_core` | `backend/core/` and `frontend/src/core/` contain no identifier or string equal to a registered plugin label, a `project/` app label, or the configured `PRODUCT_SLUG` | The denylist is **derived from the registry at test time**, so it maintains itself |
| `test_no_boilerplate_identity` | The boilerplate's name and literal cookie prefix appear only in the shipped-defaults module | String scan |
| `test_no_host_literals` | No `http(s)://` literal with a host other than `localhost`, `example.com`, `example.org` in production code | AST; documentation links in docstrings excluded |
| `test_settings_are_read` / registered | § 9.11 — every key read, every read key registered, no dynamic keys | AST |
| `test_moved_settings_not_read` | Keys moved to the registry or a singleton are not read from `settings.*` or env | A committed list of retired names, grown by § 9.14 step 5 |
| `test_no_expired_flags` | § 11 | Registry + today's date |
| `test_single_flag_mechanism` | No `NEXT_PUBLIC_FF_`; no env-read `*_ENABLED` for product features outside the infrastructure allow-list | String scan, both halves |
| `test_shipping_guards_changes_nothing` | § 13 | Registry + positive controls |
| ESLint `no-restricted-syntax` | Formatter home (§ 15); no raw colour literals outside the token files ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)) | Lint in CI |

**Django + Next shape.** `backend/tests/architecture/` (the folder [`CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md)
§ 6 already plans); a shared `iter_production_sources()` helper so every scan has the same scope;
frontend rules in `eslint.config.mjs` plus `frontend/tests/architecture/*.test.ts` for what lint cannot
express.

**Enforced by.** Themselves, in the normal `pytest` and `vitest` runs — not a separate lint step that
can be skipped.

**Configurable, not hard-coded.** Allow-lists, each entry with a reason; the ISO-4217 list is data.

---

## 19. ⚠️ Conflicts with existing docs

Recorded, not edited — each needs the owner or the owning doc's next change.

| # | Where | Conflict | Fix |
|---|---|---|---|
| 1 | `AGENTS.md` § 1 protected files; [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 12; [`DJANGO_STANDARDS.md`](DJANGO_STANDARDS.md) § 2 | All name a single `backend/config/settings.py`. § 3 splits it into a `config/settings/` package | If accepted: the protected-file entry becomes `backend/config/settings/`, and § 2 step 1 of `DJANGO_STANDARDS.md` says `config/settings/base.py`. Pending decision #1 |
| 2 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 3.13; [`DATA_MODEL.md`](DATA_MODEL.md) § 3 (`Setting` row) | `core_setting(key unique, value TextField, value_type, is_public)` has no scope, no `{"v"}` wrapper, no strict types, and stores what should be code metadata | Replace with § 9.2's table; `value_type` and `is_public` move into the code declaration (`type`, `exposure`) |
| 3 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 3.13 vs § 12 | § 3.13 says lockout thresholds live in `core_setting`; § 12 lists `LOCKOUT_THRESHOLD` / `LOCKOUT_WINDOW` / `LOCKOUT_DURATION` as env vars | Registry settings `security.lockout.*` (§ 9.6 example), env keys marked retired with `moved_to` (§ 6) |
| 4 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 12 and § 9.2 | Production behaviour keyed on `DEBUG`: `AUTH_COOKIE_SECURE` defaults to `not DEBUG`, `ADMIN_ENABLED` to `DEBUG`, `dbx.E005`/`dbx.E008` fire "while `DEBUG=False`" | Key on `is_production_like()` (§ 4). `DEBUG=True` in production is itself refused (`cfg.E002`), so the checks stop depending on the switch being honest |
| 5 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.2 heading "At boot" | System checks do not run under gunicorn, uvicorn or a Celery worker | Keep `dbx.E00x` for `check` and `check --deploy`; the boot guard is § 5's import-time audit, which carries `cfg.*` twins of the configuration-only checks |
| 6 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 12 and Ch. 18 | `DEFAULT_FROM_EMAIL` defaults to a literal address; cookie names are written as a literal `dbx_` prefix | Derive from identity (§ 7); `dbx_` becomes `<AUTH_COOKIE_PREFIX>_` — § 12's own note ("derives from a slug setting") already intends this |
| 7 | `backend/config/settings.py` (`SPECTACULAR_SETTINGS`); [`../NEW_PROJECT.md`](../NEW_PROJECT.md) § 2 | The API title and description are the boilerplate's name, renamed by hand from a table | Derive from `PRODUCT_NAME` (§ 7); the rename table shrinks to setting env keys |
| 8 | `AGENTS.md` § 3 "Settings" row; [`DJANGO_STANDARDS.md`](DJANGO_STANDARDS.md) § 8; [`SECURITY.md`](SECURITY.md) § Secrets | "Every environment-dependent value comes from `.env`" is too absolute — it forbids runtime configuration (§ 16) and the credential store | Reword to: *bootstrap values from env; operator-tunable values from the registry; third-party secrets from the credential store; nothing from a literal.* (`AGENTS.md` is protected — the owner's edit) |
| 9 | [`DATA_MODEL.md`](DATA_MODEL.md) § 3 | Lists `FeatureFlag` as "Phase 2+, as needed" | § 11 is Tier 1 because "ship dark" needs it from the first product module. Sequencing is `BUILD_ORDER.md`'s call — Pending decision #4 |
| 10 | [`../VISION.md`](../VISION.md) non-goals | *"Not maximal configurability"* and *"Not multi-language … on day one"* read as against this file | Not a real conflict: § 1 distinguishes values from knobs, and formatting from translation. Worth one sentence in `VISION.md` pointing here, so the non-goal is not cited against removing a literal |

---

## Pending decisions (for the repository owner)

1. **Split settings package.** Accept `config/settings/{base,dev,prod,test}.py` and update the
   protected-file list (⚠️ #1)? The alternative — one file with `if` blocks per environment — is how
   staging silently diverges.
2. **Code defaults resolved live, or materialised at first registration?** This file resolves the
   default from code when no override exists, so a core update can change behaviour for installations
   that never touched a value (made visible by the defaults snapshot test). Materialising pins every
   value at install time — safer across upgrades, but a fixed bad default then never reaches existing
   installations.
3. **Tenant scope in core.** The cascade reserves `tenant` and activates it only when a tenancy module
   registers a resolver. Confirm core never ships tenancy itself ([`REUSABLE_MODULES.md`](REUSABLE_MODULES.md)).
4. **Feature flags in Phase 1 or Phase 2** (⚠️ #9).
5. **No default currency or country** — confirm the first-run wizard asks, versus shipping a
   placeholder default that announces itself.
6. **Percentage rollouts for flags.** Deferred; targeting covers staged rollout today. If added, the
   bucket must be a stable hash of the user's public id and the flag key, so a user does not flicker
   between variants.
7. **Lookup label translation** — one `label` now; a `labels` map per locale when a product needs
   translation.
8. **Unknown setting key raises in production.** Chosen here because the registry and caller share a
   process; the alternative (log and return `None`) hides typos. Confirm.
9. **Plugins never read env.** Chosen here for validation and ownership; the escape hatch, if one is
   ever needed, is the product's composition root reading env and registering a default.

---

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section.
