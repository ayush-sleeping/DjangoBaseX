# Lessons learned — mistakes mature codebases made so this one doesn't

**A catalogue of just over a hundred failures that several mature production codebases actually shipped — each generalised,
each with the reason it stayed invisible, the rule DjangoBaseX adopts because of it, and the document that owns the
guard.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.
>
> The lessons themselves are history — they happened. What is not built is every **guard** named below.

## Scope — read first

**Owns:** the narrative catalogue of failures learned elsewhere — what happened, why nobody saw it, and the rule it
produced — and the pointer from each lesson to the document that specifies its guard. Per
[`../../AGENTS.md`](../../AGENTS.md) rule 5a, no source is named: every entry is written as the mechanism and the
reason. Magnitudes (rows, days, counts) are kept, because a number is what makes a lesson believable.

**Does not own:**

| Topic | Owner |
|-------|-------|
| The recurring bug-class checklist used in review | [`BUG_CLASSES.md`](BUG_CLASSES.md) — this file is the evidence; that file is the checklist |
| The specification of any guard | the document named in each entry's **Guard** line |
| How tests, CI and docs are made to enforce rules | [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) |
| Incidents in DjangoBaseX itself, and in products built on it | `documentation/incidents/`, per [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 31 |
| Failure modes specific to authentication and RBAC design | [`AUTH_FAILURE_MODES.md`](AUTH_FAILURE_MODES.md) — overlapping entries here only point to it |

### How to read an entry

Each entry has four parts. **What happened** — the failure, generically. **Why it was invisible** — the part that
matters most: almost every entry here passed its tests, its review and its dashboards. **Rule** — what DjangoBaseX
does instead. **Guard** — the document that specifies the test, check or mechanism that enforces the rule.

### How to add an entry

Add one when an incident in DjangoBaseX or a product built on it teaches something that generalises (its write-up's
*Prevention* section says so). Same four parts; one id in its category's sequence; the guard must name a document
that exists. If the class recurs, it also earns a row in [`BUG_CLASSES.md`](BUG_CLASSES.md).

---

## 0. The rules in one screen — what the catalogue has in common

1. **A check that cannot fail is worse than none, because it is believed.** Nearly every entry below had a green
   check standing over it. → [T4](#t4--checkers-that-could-not-see-what-they-checked), [C1](#c1--a-production-refusal-that-did-not-refuse), [J10](#j10--alerting-people-muted-and-alerting-that-could-not-alert)
2. **Zero is not a fact.** An empty failure table, a count of `0` and "no data" each have three possible meanings;
   only one is good news. → [J1](#j1--an-empty-failed-jobs-table-read-as-healthy), [J8](#j8--integration-failures-nobody-could-see), [O8](#o8--health-checks-that-told-the-wrong-story)
3. **Systems fail silently in both directions** — silence first, then a flood. → [J1](#j1--an-empty-failed-jobs-table-read-as-healthy), [J10](#j10--alerting-people-muted-and-alerting-that-could-not-alert)
4. **The second copy is the bug.** Two implementations of one decision drift, and the drift is invisible until it
   matters. → [A6](#a6--second-ways-of-doing-one-thing), [S4](#s4--one-security-decision-made-in-many-places), [F2](#f2--one-client-became-many-and-then-one-enormous-file)
5. **Hand-kept lists rot; derive them from the code.** → [A1](#a1--the-core-knew-every-plugin-by-name), [T5](#t5--code-and-tests-that-silently-never-ran), [T9](#t9--hand-kept-page-lists-and-the-screenshot-nobody-opened)
6. **Every default fails in some direction — choose it, and test it.** Sentinels meaning "everything" and flags
   defaulting open were among the costliest bugs. → [S3](#s3--scoping-holes-a-sentinel-that-meant-everything-and-writes-nobody-narrowed), [A5](#a5--registries-that-failed-the-unsafe-way)
7. **Hiding is not denying.** A hidden link, a hidden prop and a hidden section are all still reachable.
   → [S2](#s2--hiding-was-mistaken-for-denying), [F5](#f5--permission-aware-ui-that-failed-open)
8. **Record, don't infer.** History reconstructed from `updated_at`, "whoever is logged in" or a default value is
   fiction presented as fact. → [D6](#d6--history-inferred-instead-of-recorded)
9. **One writer per invariant.** Balances, grants and audit rows written from many places are wrong in some of them.
   → [D2](#d2--twelve-code-paths-wrote-one-balance), [S6](#s6--grant-paths-nobody-enumerated)
10. **What the operator authored is theirs.** No migration, sync or seeder rewrites it. → [D8](#d8--a-data-migration-that-rewrote-what-operators-wrote), [S5](#s5--seeders-used-as-a-deployment-tool)
11. **The environment that matters is the one you did not configure by hand.** → [T1](#t1--ci-that-never-ran-or-ran-red-for-reasons-nobody-read), [O5](#o5--behaviour-only-a-live-deploy-revealed)
12. **Docs overstate as easily as they understate**, and agents believe both. → [P1](#p1--docs-that-described-code-that-did-not-exist), [P4](#p4--registers-that-were-wrong-in-both-directions)
13. **Fixes do not stay fixed unless a test fails when they are reverted.** → [P7](#p7--fixes-that-did-not-stay-fixed)
14. **Untrusted text is data.** Templates, agents and outbound requests all turned user input into control.
    → [S9](#s9--user-text-reached-a-template-engine), [AI5](#ai5--a-bug-report-that-could-drive-a-coding-agent)
15. **Estimates are hypotheses; the call sites are the facts.** → [P8](#p8--plans-were-wrong-and-the-code-was-right)

---

## 1. Architecture and seams

### A1 · The core knew every plugin by name

**What happened.** A plugin-based platform still hard-coded its plugins in about twenty core places: the navigation
builder, the nav-badge provider (which imported plugin models), the webhook event list, the API ability catalogue,
the notification purposes, the error-alert skip list, route-to-permission maps, the job schedule, a per-plugin source
glob in the frontend entry point and per-plugin build aliases. Its own split plan listed "the ~20 core files to edit
to remove one plugin". A sibling codebase registered its routers by hand-enumerated imports in one file.

**Why it was invisible.** Everything worked while every plugin was installed. The failure only appeared where a
plugin was absent — as a fatal import in a core page — or when a second product tried to use the core.

**Rule.** Every core literal that names a model, path, event, ability, purpose or tool is a registry; plugins
register from `AppConfig.ready()`; the core learns keys, never vocabulary. `manage.py check` passes with every plugin
removed from `INSTALLED_APPS`.

**Guard.** [`EXTENSIBILITY.md`](EXTENSIBILITY.md) — the registry catalogue and the core-only assembly test.

### A2 · Broken modules vanished behind a swallowed import error

**What happened.** Optional modules were loaded inside `try: import … except ImportError:`. A typo *inside* a
present module raises `ModuleNotFoundError` — a subclass of `ImportError` — so the whole module silently disappeared
from the running system.

**Why it was invisible.** The only symptoms were permissions missing from the catalogue and a handful of 404s, both
of which look like configuration mistakes, not a crash.

**Rule.** Catch `ModuleNotFoundError` only when `exc.name` is the optional package itself; re-raise everything else.
A present-but-broken plugin fails boot loudly. This contradicts a line in `AUTH_BLUEPRINT.md` § 7.2, now tracked.

**Guard.** [`EXTENSIBILITY.md`](EXTENSIBILITY.md); [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-18**.

### A3 · Product vocabulary leaked into the core through channels no import scan sees

**What happened.** A core extracted from a product kept the product's words in: route **strings** in a layout file,
icon **names**, a database enum spelled with product terms, a product setting key in the core seeder, webhook header
names and token prefixes built from the product's initials, one market's phone-number pattern, a default staff email
domain, and HR fields (employee id, designation, personal phone) on the core `User`. Worse, the first text-based
vocabulary scan flagged the constant used to derive the encryption key — and "tidying" that constant would have made
every stored secret undecryptable.

**Why it was invisible.** Every import-boundary test was green; the coupling was in strings, enums and schema, not in
imports.

**Rule.** Boundary tests scan AST identifiers and route strings (never raw text, never string or bytes literals), with
an exception list pinned empty; core FKs target only core tables; the core `User` holds identity and auth state only
— product fields go on a product profile; key-derivation constants are documented as never-change.

**Guard.** [`EXTENSIBILITY.md`](EXTENSIBILITY.md) (boundary tests); [`DATA_MODEL.md`](DATA_MODEL.md) (the user model);
[`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (the encryption service).

### A4 · Tenancy decided late cost a 258-signature sweep

**What happened.** A core that began single-tenant later needed organisations. Its schema could not even be created
without a product table, and threading tenant scope through the code was estimated at "about 40 signatures" and
measured at 258.

**Why it was invisible.** Until the second customer type appeared, nothing needed it — and the cost of a missing
decision grows silently with every function written in the meantime.

**Rule.** Decide tenancy before the first migration, deliberately, and record the retrofit cost in the ADR whichever
way it goes.

**Guard.** [`DATA_MODEL.md`](DATA_MODEL.md) D3; [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-23**;
[`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) (tenancy).

### A5 · Registries that failed the unsafe way

**What happened.** A registry resolved per request instead of as a singleton handed every reader an empty list. Its
default for an unregistered entry was "on", so the switch built on it silently did nothing. Elsewhere, a role left
unclassified fell through to the *internal staff* branch — widening access instead of refusing it — and an external
team member saw a competitor's organisation.

**Why it was invisible.** An empty registry and an unconfigured default both look exactly like "nothing to do".

**Rule.** Registries are module-level singletons populated at boot; every registry documents its unknown-key default,
chosen in the safe direction (unknown flag = off, unknown classification = least privilege, unregistered probe =
unverifiable), and a test pins it.

**Guard.** [`EXTENSIBILITY.md`](EXTENSIBILITY.md); [`CONFIGURATION.md`](CONFIGURATION.md) (flag resolution).

### A6 · Second ways of doing one thing

**What happened.** Three error envelopes, so every client carried three parsers. Two pagination conventions, one of
which relied on a response header that CORS did not expose, so white-label portals could not read their totals.
Twenty-five currency formatters with different decimals; status-badge switches that disagreed with each other; three
functions with near-identical names and different caching semantics; two modules whose names differed by a word and
shadowed each other, breaking every authenticated request. And eleven hand-rolled settings singletons, each with its
own save, test and snapshot path, sitting beside a generic credential store that had **zero** registered consumers.

**Why it was invisible.** Each copy was reasonable when written. The cost only shows in aggregate — and a generic
primitive nobody adopted looks like progress.

**Rule.** One way to do each thing, enforced by lint and guard tests; grep before creating; extract a primitive at its
third genuine consumer and never before its first; identical names never hide different semantics.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 20, § 23; [`API_PLATFORM.md`](API_PLATFORM.md) (one
envelope, one pagination).

### A7 · Request-scoped state leaked across boundaries

**What happened.** A per-request tenant held in a context variable leaked twice: a middleware base class ran the
endpoint in a separate task context, so the reset in middleware cleared a context the endpoint had never written.
Request-id middleware that reset its value in a `finally` block made every 500 body report `request_id: "-"` and every
access line read `[-]`. Audit attribution bound to a thread-local would misattribute actors the day the app ran
asynchronously.

**Why it was invisible.** Each worked in synchronous tests; the fault appeared only under the production server's
concurrency model.

**Rule.** Request-scoped state uses `contextvars`, is set by the outermost layer as its first act, and is reset only
after the response is fully built; tenant scope is bound to the request object, not ambient state; a test crosses the
boundary.

**Guard.** [`OBSERVABILITY.md`](OBSERVABILITY.md) (request ids); [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) (actor and
tenant context).

---

## 2. Configuration

### C1 · A production refusal that did not refuse

**What happened.** Four versions of the same failure. Security gates written as `environment == "production"` were
bypassed by deployments named `Production` and `staging` — and two predicates for "is this production?" drifted
apart. Safety rules written as framework system checks never ran, because system checks run on management commands,
not when the application server serves requests. A placeholder check by equality let `"changeme" * 4` through a length
floor. And a docstring claimed "the boot validator already requires this secret" when no such validator existed — the
missing secret surfaced as a fleet-wide monitoring outage. A second application entrypoint on the same codebase ran
two of eight boot validators and forgot to initialise its database, so every one of its endpoints returned 500.

**Why it was invisible.** In every case, the code that looked like a guard was present and plausible.

**Rule.** One `is_production_like()` predicate — an allow-list of non-production names, so an unknown name counts as
production. The production audit runs at settings import and lists every problem at once; placeholders match by
substring and distinct-character count; one boot sequence shared by every entrypoint; CI proves a development config
refuses to import under `APP_ENV=production` and a valid one succeeds.

**Guard.** [`CONFIGURATION.md`](CONFIGURATION.md); [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-19**;
[`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 13.

### C2 · Settings stores multiplied

**What happened.** One platform grew four parallel settings tables before a registry existed, and a security plan
proposed a fifth. Another grew ten per-feature singleton settings tables, each with a service "modelled on" the
previous one, plus 38 environment booleans in a 1,100-line settings class.

**Why it was invisible.** Each new table was the fastest way to ship one feature.

**Rule.** One typed, code-declared settings registry over one table; registration never resets a value; every value
must pass an admission test before it earns a place on a screen.

**Guard.** [`CONFIGURATION.md`](CONFIGURATION.md).

### C3 · Feature flags the application could not see

**What happened.** Flags lived in untracked per-server environment files, so the application, its docs and its agents
could not tell what production had on. A hand-maintained launch-state file had to shadow them — and a feature went
live while its help article stayed dark. The frontend meanwhile had four unrelated gating mechanisms: build-time
booleans, ad-hoc "is X enabled" endpoints, per-organisation capabilities and that file.

**Why it was invisible.** Each mechanism answered its own question correctly; nobody owned the union.

**Rule.** One flag registry, declared in code, state in the database, resolved kill-switch-first, served in the
bootstrap payload, each flag with an owner and an expiry; new behaviour ships dark by default.

**Guard.** [`CONFIGURATION.md`](CONFIGURATION.md); [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (bootstrap).

### C4 · Settings screens that lied

**What happened.** A staleness threshold was editable for months with **zero** readers, while the admin guide
described its effect. Elsewhere a string `"false"` coerced to `True` — the kind of bug nobody finds until a security
control is quietly off.

**Why it was invisible.** The screen saved, the value persisted, and nothing complained. *A control that saves and
does nothing teaches an admin that the screen is decorative, and the lesson transfers to the controls that work.*

**Rule.** Every registered setting has a reader outside the settings app, asserted by a completeness test; coercion is
strict (booleans accept only `true/false/1/0`; integers reject booleans).

**Guard.** [`CONFIGURATION.md`](CONFIGURATION.md); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 3.

### C5 · One market hard-coded into a product meant for many

**What happened.** One codebase held about 300 currency literals and 24 timezone literals; formatters were pinned to
one locale; the database server ran at a fixed offset; the test runner pinned one timezone; geolocation failed open
to a default country; currency and even the identity-verification provider were derived from the phone number's
country. Another wrote its locale, currency and timezone into its *standards document*, where every plugin copied it.

**Why it was invisible.** For the first market, every value was correct.

**Rule.** Locale, currency, timezone and formats are platform, tenant and user settings from day one; store UTC and
return ISO-8601; money is always an amount plus a currency; a scan fails on currency or timezone literals outside
settings and fixtures.

**Guard.** [`CONFIGURATION.md`](CONFIGURATION.md); [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) (money).

### C6 · Dangerous values with no floor

**What happened.** A retention setting of `0` would have wiped a table on the next nightly run — *one of the few
places where the damage from a bad value is immediate and unrecoverable*. A session cap of `0` silently meant
"unlimited".

**Why it was invisible.** Nothing validates a value an admin is allowed to type.

**Rule.** Settings declare `min`, `max` and `choices`; values are validated on write and clamped on read; `0` never
means "unlimited" or "disabled" unless the key's name says so.

**Guard.** [`CONFIGURATION.md`](CONFIGURATION.md); [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) (retention floors).

### C7 · Identity literals that could never be recalled

**What happened.** An authenticator-app issuer literal is baked into every device that has already enrolled — it
cannot be corrected without re-enrolment. A `MAIL_FROM` literal sent mail as a company the product had nothing to do
with. Two local stacks kept logging each other out, because every project on `localhost` used the same session
cookie name and cookies ignore the port.

**Why it was invisible.** Each literal was right for the product it was written in, and wrong for every copy.

**Rule.** One project identity setting (name, slug, primary domain) derives the issuer, the from-address, the API
title and the cookie names; shipped defaults announce themselves ("Rename this deployment") and the production audit
warns while they are unchanged.

**Guard.** [`CONFIGURATION.md`](CONFIGURATION.md) (project identity).

### C8 · Build-time configuration for runtime facts

**What happened.** The API URL was baked into the frontend at build time, so every environment needed its own build
and "the frontend is calling localhost" was a recurring incident; production-ness was decided by comparing that URL
to a string. By contrast, the one switch that was read at runtime — the flip from report-only to enforced
Content-Security-Policy — became "a container restart, not a rebuild".

**Why it was invisible.** A build-time value is correct in the build that was tested.

**Rule.** `NEXT_PUBLIC_*` holds only build-stable public values; anything that varies by environment is served at
runtime; environment identity is an explicit variable, never inferred; a table in the frontend standards lists which
settings are build-time.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md); [`CONFIGURATION.md`](CONFIGURATION.md).

### C9 · A label stored as the value

**What happened.** An admin-editable vocabulary stored its display label as the persisted value. Renaming a label
split dashboard categories in two ("both percentages individually correct and jointly misleading"), dropped rows from
exact-match filters, and leaked the old word into an external system's logs forever.

**Why it was invisible.** Renames happen months after the data is written, and each screen still rendered.

**Rule.** Admin-editable vocabularies have a stable key the admin cannot edit and a label they can; references store
the key; membership is validated against the table at request time, never a literal list.

**Guard.** [`CONFIGURATION.md`](CONFIGURATION.md) (vocabularies).

---

## 3. Security and authorization

### S1 · Security meaning carried by names

**What happened.** A route's permission was inferred from its name and its controller's name, with pluralisation and
verb maps. It caused at least four incidents of "403 for everyone while the grant reads as granted" (one produced 54
refused auto-saves over three weeks) and the inverse: a route resolved to the *wrong* permission and exposed a
dashboard with hidden margins to every sales user for a year. A substring match on controller names crossed module
boundaries — 25 colliding pairs — and handed an unreleased module to 31 users. Elsewhere a read-only role was derived
by dropping permissions whose last segment was a write verb; a permission ending in a noun sailed through and gave
credential minting to the read-only role.

**Why it was invisible.** The permission always *looked* right in the admin screen.

**Rule.** Every view declares its permission explicitly and a system check refuses a view without one; permissions
carry explicit metadata (`kind`, `sensitivity`) and derived roles are computed from metadata, never from names.

**Guard.** [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) (explicit view permissions); [`RBAC_DESIGN.md`](RBAC_DESIGN.md).

### S2 · Hiding was mistaken for denying

**What happened.** Nav gating was treated as access control. Admin pages reachable only by URL were ungated until
someone added a nav entry, because unrecognised routes fell back to "any admin". A dashboard shipped a hidden payload
property with every colleague's name and email to 119 users — rendered by no component, fully readable in the
browser's developer tools. Counts on a dashboard disclosed what the lists behind them refused.

**Why it was invisible.** On screen, nothing was visible.

**Rule.** The route carries the gate; unknown routes are denied by default; responses carry only what the user may
see, and a dashboard section the user may not see is not computed at all; counters are built from the same scoped
query as the list.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (nav as route gate); [`API_PLATFORM.md`](API_PLATFORM.md);
[`RBAC_DESIGN.md`](RBAC_DESIGN.md).

### S3 · Scoping holes: a sentinel that meant "everything", and writes nobody narrowed

**What happened.** A shared scoping helper returned `None` for admins to mean "no restriction", and a refactor turned
that into an unscoped query that showed every tenant's resources on an admin's self-service dashboard. In another
codebase the read path was tenant-scoped and the write path was not: a user who could not *see* a row could `PATCH`
it by id, change its email, and drive a password reset. A bypass flag whose ORM default computed `True` for any
constructor that omitted a version became a permanent governance bypass.

**Why it was invisible.** Tests used users for whom the sentinel and the default happened to be right.

**Rule.** No sentinel means "everything" — the privileged path is an explicit opt-in flag defaulting to `False`;
`None` and an empty set are different and neither means all; writes are narrowed exactly like reads, and an invisible
row answers 404 to `PATCH`; exemption flags default closed and are set explicitly.

**Guard.** [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) (scoping extensions); [`DATA_MODEL.md`](DATA_MODEL.md) § 5;
[`BUG_CLASSES.md`](BUG_CLASSES.md).

### S4 · One security decision made in many places

**What happened.** Seven login paths (password, several social providers, magic link, confirm-link) each had a
copy-pasted completion block; one skipped the second factor, and inactive users could still obtain tokens. Token
decoding was copied five times, and only the `type` check stopped a refresh token being used as an access token.
The list of roles that bypass checks existed in five places and had already drifted — the frontend showed a role
everything the backend refused. Cookie clearing did not mirror the flags used to set the cookie, which would have
silently broken logout under `SameSite=None`. An owner bypass the backend applied was invisible to the "my
permissions" endpoint, so the UI hid owner actions. And testing with bypass roles hid a missing permission for every
real role — and a broken global search for two months.

**Why it was invisible.** Each copy was correct on the day it was written.

**Rule.** One login-completion pipeline, guarded by a test that tokens are minted only from it and a parity test
across every login route; one typed token decoder; one bypass function whose result the `/me` endpoint returns as
*effective* permissions; cookies set and cleared by one function; tests act as non-bypass users.

**Guard.** [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md); [`AUTH_FAILURE_MODES.md`](AUTH_FAILURE_MODES.md);
[`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 1.

### S5 · Seeders used as a deployment tool

**What happened.** A permission seeder deleted every permission not in its list and relied on plugin seeders to
recreate theirs: each run destroyed 411 of 460 permissions and 2,242 role grants, with an empty intermediate state. A
role re-sync reverted every grant an admin had changed on the roles screen, on every deploy.

**Why it was invisible.** Immediately after a run, the numbers looked right again.

**Rule.** Catalogue sync reconciles and never deletes-then-rebuilds; removed codes are deprecated, not deleted; default
grants are applied once per permission (a ledger records it), so an admin's later removal sticks; grant changes on a
live system ship as migrations.

**Guard.** [`RBAC_DESIGN.md`](RBAC_DESIGN.md); [`EXTENSIBILITY.md`](EXTENSIBILITY.md) (additive role grants).

### S6 · Grant paths nobody enumerated

**What happened.** A permission added with its route was seeded nowhere, and the grant-by-name path silently did
nothing — three permissions had been ungrantable since launch. A machine-token ability typed wrong "read as granted
and arrived as a 403". Any admin could create a super-admin through an unguarded registration path, and anyone who
could edit role permissions could grant their own role anything by enumerating ids.

**Why it was invisible.** A behavioural test only covers the write paths someone remembered.

**Rule.** "Referenced" is mechanically tied to "catalogued" in both directions; abilities and scopes are validated at
write time; a privilege ceiling — you cannot grant what you do not hold — lives in the single grant writer, and a
source-level test asserts every grant-writing function calls it and no other module writes grants.

**Guard.** [`RBAC_DESIGN.md`](RBAC_DESIGN.md); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 3.

### S7 · A spoofable client IP disabled every rate limit

**What happened.** The proxy *appended* to `X-Forwarded-For`, the application trusted the leftmost value, and the
application server accepted forwarded headers from anyone — so every IP-based limit was bypassable by a header. An
earlier "trusted peer" fix was a no-op. Rate-limit counters kept in memory across two replicas of four workers made
every limit eight times looser. Keying limits by the concrete URL gave every slug its own bucket; a per-user limiter
decoded the token without verifying its signature, so a forged subject got a fresh bucket each time. Headers set by a
middleware registered inside the CORS layer never reached preflight responses, and a 429 without CORS headers shows in
the browser as an opaque network error.

**Why it was invisible.** Every limit worked in a test from one client, one process, no proxy.

**Rule.** Model the real proxy chain: the proxy overwrites the header, the app walks it right-to-left over trusted
CIDRs; counters live in the shared cache; limits key on the view's scope and, per user, only on an authenticated
user; security headers wrap everything, and throttled responses carry CORS headers.

**Guard.** [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) (`client_ip`); [`API_PLATFORM.md`](API_PLATFORM.md) (rate limiting);
[`OPERATIONS.md`](OPERATIONS.md) (proxy); [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-17**.

### S8 · One key for every purpose, and every environment

**What happened.** One signing secret was reused for session tokens, at-rest encryption and agent tokens; a legacy
symmetric algorithm was always appended to the accepted token algorithms, so a leaked secret could forge admin tokens
even with asymmetric signing switched on. An encryption key derived from the signing secret meant rotating the
signing secret made every encrypted value unreadable. And every environment shared one encryption key, so a restored
production dump carried **working** production credentials into staging, with background workers live.

**Why it was invisible.** Everything decrypted, everywhere.

**Rule.** One key per purpose and per environment; algorithm policy enforced at boot; encryption uses a key *list*
(newest first) so rotation is a re-encrypt, not an outage; foreign ciphertext fails closed.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (encryption service); [`CONFIGURATION.md`](CONFIGURATION.md)
(boot refusal); [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) (signing-key fallbacks).

### S9 · User text reached a template engine

**What happened.** Tenant-editable email templates were rendered by a general-purpose template engine — autoescaping
does not stop template injection, so this was remote code execution. Separately, user-supplied names were unescaped
in 37 of 39 email-sending methods.

**Why it was invisible.** Every template anyone tested was benign.

**Rule.** User-authored templates render in a sandbox with an allow-listed token set, validated at save time in the
same sandbox; every fallback email escapes user input; the class is on the review checklist.

**Guard.** [`BUG_CLASSES.md`](BUG_CLASSES.md); [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md);
[`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) (templated documents).

### S10 · Outbound requests the attacker could aim

**What happened.** Webhook URLs were accepted with any host and plain HTTP; a later SSRF check validated the address
and then let the HTTP client resolve DNS again (a rebinding window) and follow redirects. A server-side branding fetch
was driven by the request's `Host` header. Host matching used a substring test, so `not-the-host.example.evil.test`
matched.

**Why it was invisible.** Every URL in testing was one the developer typed.

**Rule.** One SSRF-safe HTTP client: resolve every address, refuse private, loopback, link-local and reserved ranges
at write time **and** before each send, connect to the vetted address, never follow redirects; hosts are compared by
exact match after normalisation; any fetch driven by a request header goes through the same guard.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md); [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md).

### S11 · Secrets in the places they leak from

**What happened.** A validation-error handler logged raw request bodies — passwords, one-time codes and government
identifiers ended up in logs and the error tracker. A one-time setup token was printed to container logs on every
start. A token committed in a seeder was auto-revoked by the host's secret scanning. Tokens embedded in clone URLs sat
in a tracked agent-permissions file and a submodule config. One SMTP password was stored in plaintext beside
encrypted secrets — and the whole configuration object, password included, was cached in the shared cache.
Decryption failures returned the ciphertext itself, "so nothing looked wrong".

**Why it was invisible.** Each was a convenience in the path of debugging.

**Rule.** Input is echoed to the client, never to logs; one scrubber serves logs, the error tracker and the frontend;
one-time tokens are never logged; secret scanning covers code, docs and agent config; all secrets go through the one
encryption helper and never into a shared cache; decryption failure raises.

**Guard.** [`OBSERVABILITY.md`](OBSERVABILITY.md) (scrubber); [`SECURITY.md`](SECURITY.md);
[`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 16, § 39.

### S12 · Security machinery that existed only on paper

**What happened.** Six security columns — lockout counters, last-login, reset-token fields — were never written: *a
false sense of security, not just dead code*. Guards were defined and wired nowhere. Email-verification routes were
ported from a reference implementation and never enforced. Every emailed link landed on a 404, and the "forgot
password" link had been hidden because its page did not exist — so nothing looked broken.

**Why it was invisible.** The code, the columns and the routes all existed; reviewers saw them.

**Rule.** Every security mechanism has a behavioural test through the real HTTP path; do not port half-wired
features; browser workflows follow every link in every email they send.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 1, § 3, § 11; [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md).

### S13 · Machine access and human sessions blurred together

**What happened.** A machine API accepted the browser's session cookie, so every browser session silently passed its
scope gate, and the API docs' "Send" button succeeded with an empty credential box. API keys were not bound to the
organisation they were minted in, so a key inherited its owner's reach across every organisation. Ending an
impersonation did not revoke its token, which stayed valid for up to fifteen minutes. A 24-hour bearer token lived in
`localStorage`, readable by any script injection, while the content policy was still report-only.

**Why it was invisible.** Every one of these made the product *easier* to use.

**Rule.** Machine callers are distinct principals and the machine API takes no cookie; credentials are bound to the
scope they were issued in; ending impersonation revokes; browser credentials live only in `httpOnly` cookies (as
DjangoBaseX already specifies).

**Guard.** [`API_PLATFORM.md`](API_PLATFORM.md) (machine principals; [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md)
**DB-21**); [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md).

### S14 · Private files served publicly, and uploads trusted by name

**What happened.** In filesystem mode, the web server served the media directory without authentication — while
uploads included signatures and signed delivery documents — so the security posture depended on a storage toggle.
Support attachments and bug-report screenshots were accepted with no validation, their type taken from the filename.

**Why it was invisible.** In the object-storage mode everyone tested, files were private.

**Rule.** Private files are always served through an authenticated view (with an internal redirect for efficiency),
whatever the storage backend; the bytes decide the type; reads are bounded before the size check; images are
re-encoded; SVG carrying script is refused.

**Guard.** [`API_PLATFORM.md`](API_PLATFORM.md) (files and uploads).

---

## 4. Data and money

### D1 · Money handled as floats and re-derived for display

**What happened.** Admin add-funds and deduct-funds request schemas typed the amount as a float, so a client float
could reach the balance-debit path unquantised; meanwhile 679 cargo-cult `Decimal(str(x))` calls, mostly no-ops, made
the code *look* careful. In another codebase each display surface rounded for itself — the same service showed ±1
across five screens; a monthly column was subtracted from a term total (a large negative "saving"); a percentage
column mixed with fixed amounts was averaged ("4,672% average discount"); and an unrecognised price component returned
`0.0`, under-quoting by 56% — which survived a parity check because both sides called the same method. *One
implementation consulted twice is not evidence.*

**Why it was invisible.** Every individual number was plausible.

**Rule.** Money is `Decimal` plus a currency code, quantised once at the domain boundary with one rounding rule;
display never re-derives; an unknown component is refused, never priced at zero; a scan bans float fields named like
money.

**Guard.** [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) (money).

### D2 · Twelve code paths wrote one balance

**What happened.** Twelve code paths mutated a wallet balance directly and hand-built its transaction rows, so the
per-bucket credit ledger drifted from the real balance — and a promotion's expiry deducted real money. The same
defect had been catalogued four times before it was fixed.

**Why it was invisible.** Each path balanced its own books; nobody reconciled the total.

**Rule.** One writer per invariant — ledgers, balances, audit rows and grants each have a single service entry point;
a source-scan guard with **line-level** allow-lists (a file-level exemption would have excused the highest-volume
writer) proves nobody else writes; a reconciler compares.

**Guard.** [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md); [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) (ledger);
[`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 2.

### D3 · Billing truth taken from the wrong place

**What happened.** Usage closers recomputed `rate × lifetime` on a forward-only collector, repricing history
retroactively and double-billing prepaid customers across twelve closers. "Metered" was assumed to mean "billed",
when billing needed a rate, a collector, an invoice line and an unbilled total all to exist. An invoice "pay"
endpoint marked invoices paid with any method, from a client-reachable call.

**Why it was invisible.** The totals were right for accounts that never changed plan.

**Rule.** Billing is forward-only from a stored cursor; payment success comes only from the payment provider's
verified callback; "metered ≠ billed" is on the review checklist.

**Guard.** [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) (billing); [`BUG_CLASSES.md`](BUG_CLASSES.md).

### D4 · Document numbers minted by scanning for the maximum

**What happened.** Document numbers were chosen by scanning existing documents for the highest number, and collided
under concurrency and across sites. Another codebase needed separate sequences per document type after statements
consumed invoice numbers.

**Why it was invisible.** One user at a time never collides.

**Rule.** Numbering is a sequence row locked with `select_for_update()` inside the caller's transaction (so a rollback
returns the number); forms *peek* and saves *reserve*; each series, scope and period is its own sequence.

**Guard.** [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) (document sequences).

### D5 · Soft delete that destroyed uniqueness

**What happened.** The popular advice — widen a unique index with `deleted_at` — silently destroys uniqueness, because
NULLs are distinct: two live rows with the same email were accepted. Elsewhere there were no soft deletes at all, so
every delete was permanent.

**Why it was invisible.** The constraint still existed in the schema.

**Rule.** On PostgreSQL, uniqueness among live rows is a partial unique constraint (`condition=Q(deleted_at__isnull=True)`);
restore checks for conflicts; the recycle bin shows what a binned row still holds (the email behind "already taken").

**Guard.** [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) (soft delete).

### D6 · History inferred instead of recorded

**What happened.** Durations were computed from `updated_at`, which moves on every edit — a typo fix turned a two-day
response into a two-month one. *A gap in a duration table does not look like a gap; it looks like a fast stage.* A
proposed backfill would have defaulted a provenance flag to "entered by a person", asserting that about 20,000
unverified rows were human-typed. A base model stamped `updated_by` from "whoever is logged in" unconditionally, which
would have written NULL over real attribution on every job and seeder save.

**Why it was invisible.** Inferred history is indistinguishable from recorded history once it is in a table.

**Rule.** State transitions are written when they happen, for every write path; system writes record a system actor
(or none), never "whoever is resolvable"; `null` means unknown and is never backfilled; reconstructed rows are marked
as reconstructed and excluded from measured figures.

**Guard.** [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) (transitions, provenance, actors).

### D7 · No base model, no locking, naive time

**What happened.** A UUID-plus-timestamps base model was copy-pasted into five apps while the core mixed primary-key
types. Another codebase redeclared the same columns in all 189 model files, had no optimistic locking (so concurrent
admin edits silently overwrote each other), and still called a naive `utcnow()` in 37 files.

**Why it was invisible.** Every copy worked; the cost was in the next change to all of them.

**Rule.** One base model set, decided before the first migration; optimistic locking where humans edit shared
records (a version and `If-Match`, answering 409); timezone-aware time only, enforced by lint.

**Guard.** [`DATA_MODEL.md`](DATA_MODEL.md); [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 19.

### D8 · A data migration that rewrote what operators wrote

**What happened.** A regex data migration "fixed" duplicate signature blocks in operator-authored document templates.
It matched every row on the one development database, and would have silently mangled production templates it had
never seen; its no-op reverse admitted it was irreversible. A person stopped it before it shipped.

**Why it was invisible.** It was correct on every row anyone had looked at.

**Rule.** A migration may create, update or delete what the product ships; it never transforms what a person
authored. Corrections to authored content ship as a new default or an in-app "upgrade this template" action.

**Guard.** [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md); [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md).

### D9 · Two authorities for one schema

**What happened.** Development startup created tables from model metadata, so the schema could exist without a
migration. Later, production's migration history was reconciled by *stamping* — which skips data migrations — so a
seed migration never ran, the allowed-countries table stayed empty, and **every sign-up was refused for about five
days**. Elsewhere a migration chain could not run from an empty database (a migration referenced a table created in a
later one), and tests ran on a persistent, hand-migrated test database, so failures surfaced as "table not found" or
a 403 that looked like a test bug.

**Why it was invisible.** Development had run the real migrations; every dashboard counted refused sign-ups as normal
4xx.

**Rule.** Migrations are the only schema authority; stamping is not migrating; CI migrates from empty on every PR and
tests never build the schema from models; required reference rows are checked at boot, in health and in metrics.

**Guard.** [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md)
§ 13; [`OBSERVABILITY.md`](OBSERVABILITY.md) (data-plane checks).

### D10 · The model and the database disagreed

**What happened.** The ORM declared `CASCADE` while the migration said `SET NULL`, so a deleted organisation's custom
roles became organisation-less rows that were then assignable globally. Schema autogeneration proposed 80 unrelated
operations — including dropping unique constraints on the RBAC tables and two deliberately created hot indexes —
inside a migration named after something else. A migration created an enum type twice (explicitly and implicitly),
so it had never executed successfully anywhere. And invariants lived in per-caller checks that drifted, while a
`TextField(max_length=…)` that neither the database nor `full_clean()` enforces gave a false sense of a limit.

**Why it was invisible.** Each layer was self-consistent; nobody compared them.

**Rule.** A freshly generated migration is empty at rest; when the database is right about a constraint the model
forgot, fix the model; one purpose per migration, and every migration is read before merge; invariants live in a
model validator **and** a database constraint, with a test that the database rejects a bypass.

**Guard.** [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md); [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) (invariants).

### D11 · Retention by accident

**What happened.** A third-party package's log cleaner read its own default of 50 days and silently destroyed three
weeks of audit trail against an agreed 90-day policy — *seven tables each quietly deciding for themselves*. One
scratch table reached 76% of the database because nobody wrote its prune. Three tables had no purge at all — and
the fastest-growing tables (request logs, error occurrences, webhook deliveries) grow fastest *exactly when
something is wrong*.

**Why it was invisible.** Deletion leaves no row to notice, and growth is gradual until it is not.

**Rule.** One retention engine; every append-only table registers a policy when it is created, with an age **and** a
row cap, batched deletes, `--dry-run` and floors; evidence tables are opt-in; package cleaners are disabled in favour
of the engine.

**Guard.** [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) (retention engine).

---

## 5. Jobs, integrations and alerting

### J1 · An empty failed-jobs table read as healthy

**What happened.** 2,162 queued jobs — 127 of them real emails to real people — sat unprocessed for seven months.
The failed-jobs table was empty the whole time, *which reads as healthy — those jobs never failed, they were never
picked up*. When the missing worker was finally wired, the next hazard appeared: a worker attached to a months-old
backlog delivers months-old notifications to real people within a minute.

**Why it was invisible.** The only signal anyone watched counted failures, and nothing had failed.

**Rule.** Record every job's lifecycle; "alive" means a job started recently or the queue is empty; "stalled" means
pending work older than a threshold; triage, back up and purge a stale backlog *before* attaching a worker.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (run monitor); [`OBSERVABILITY.md`](OBSERVABILITY.md);
[`OPERATIONS.md`](OPERATIONS.md) (runbook).

### J2 · A queue with no consumer

**What happened.** A set of tasks was re-routed to a new queue that no worker consumed; billing, reconcilers and
cleanups would have silently stopped. Variants in the same codebase: a task with a custom `name=` bypassed its
wildcard route and landed on the default queue; a routed module was never imported, producing "unregistered task";
and the framework's built-in default queue name had no consumer until it was set explicitly.

**Why it was invisible.** *A task routed to a queue with no consumer is enqueued and never executed. Nothing raises.*

**Rule.** When two configuration halves must agree, a test parses both: every routed queue has a consumer, every
schedule names a registered task, and missing queues raise instead of being created.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (queue invariants).

### J3 · Locks that never expired and limits that never fired

**What happened.** A bare overlap lock defaulted to a 24-hour hold; a deploy killed the worker holding it, and the job
did not run for a day. A hard task time limit without a smaller soft limit never behaved as intended, because the
framework filled the soft limit from a much longer global default. Periodic entries without an expiry piled up behind
slow runs.

**Why it was invisible.** Each looks fine until a process dies at the wrong moment.

**Rule.** Every lock has a TTL no longer than the job's maximum runtime and a token-checked release; every hard time
limit has a smaller soft limit; every periodic entry expires before its next period.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (locks, task limits).

### J4 · Payloads and pools that did not fit the worker model

**What happened.** A queued listener serialised a fully hydrated user — roles and permissions included — and exhausted
128 MB on logout. A database engine created at import in the pre-fork parent leaked idle-in-transaction connections
into every child until the server hit its connection limit. Twelve parallel test workers pointed at the application
database exhausted its 200 connections and starved the running app.

**Why it was invisible.** Each worked with one process and small data.

**Rule.** Job payloads carry ids only, serialised as JSON; database pools are created per process, lazily; parallel
test runs never target a database anything else uses.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md); [`OPERATIONS.md`](OPERATIONS.md) (connection budget);
[`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 5.

### J5 · Side effects that were lost, doubled or fatal

**What happened.** A send that timed out after the provider may already have accepted it was retried blindly —
double-sending to customers — while a worker that died mid-send lost the message entirely. An emit that only flushed
after the caller's commit silently dropped its rows; webhook dispatch ran inline in the request. Six separate outbox
implementations in one codebase disagreed on at-least-once versus at-most-once. And a notification failure could fail
the save that triggered it.

**Why it was invisible.** The happy path was right every time.

**Rule.** Durable side effects go through one transactional outbox — enqueued in the same transaction, unique dedupe
key, leased claims with `SKIP LOCKED`, and an `unknown` state for ambiguous sends that a human resolves; notifications
dispatch on commit and never raise into the business action.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (outbox); [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md).

### J6 · Transient states nobody reconciled

**What happened.** Resources created with an asynchronous provider status (`PENDING_*`) had no reconciler, or one
whose filter was too narrow or ignored child tables — and stayed pending forever with no escape hatch in the UI. A
reconciler that committed only at the end of its batch lost all progress when its soft time limit killed it.

**Why it was invisible.** A pending state is a legitimate state; nothing distinguishes "pending" from "stuck".

**Rule.** Every transient state has a scheduled reconciler covering every non-terminal state and child table; it
commits incrementally, skips calls bound to fail, keeps its cursor in a job-state table, and records a finding for a
human when it gives up.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (reconcilers); [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md)
(findings queue).

### J7 · Integration contracts that let absence mean something

**What happened.** Two systems, each reasonable: an upstream returned an empty success, and the pipeline read it as
consent to advance — a whole clarification stage was skipped for two weeks. A strict membership check on an enum the
*upstream* owned produced 422s that were blamed on the wrong system. A proxy silently dropped keys it had not listed,
so a model never learned from its reviews. Mirroring a feed — treating absence as deletion — would have deleted four
blocks of live content on its first nightly run. Silent auto-creation on sync duplicated vendors and catalogue items,
and a pull that collected nothing reported success.

**Why it was invisible.** Every call returned 200.

**Rule.** Validate by ownership: theirs → type and normalise; ours → membership; caller ids → form. Every key a client
sends is listed or rejected. An empty success on a money- or customer-facing step is a hold for a human. Feeds are
additive — absence never means delete. Sync never silently creates; unmatched data becomes a pending change. A pull
that collected nothing is a failure.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md); [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) (ingestion).

### J8 · Integration failures nobody could see

**What happened.** A shared key was rotated upstream and every call returned 403 for **seven weeks** unnoticed; none
of 25 stored credentials had ever been verified. A "not found" from a CRM lookup was cached for five minutes while the
user created the record 57 seconds later — *the app was not even making the call, so there was no request to
inspect*. The integrations screen under-reported traffic about 400:1 because a second entry point had no consumer row;
the busiest integration read "never called" because recency was computed over a window; a feed that priced money had
no record at all. And one unreachable target multiplied its timeout by the size of the fleet on every sweep.

**Why it was invisible.** Each surface showed a number, and the number was zero.

**Rule.** Credentials are probed at save time (`verified | failed | unverifiable`, never "ok" by default) and re-probed
nightly; failed lookups are never cached; every integration relationship is registered, with *untracked* as an
explicit state and recency computed all-time; dead targets back off.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (credential probes, integration registry);
[`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) (caching); [`OBSERVABILITY.md`](OBSERVABILITY.md).

### J9 · A laptop that emailed customers

**What happened.** Local development ran on a same-day copy of production data whose credential rows held working
provider credentials; queued emails reached the real mail provider from a developer's laptop. A convenience setting
let development fall back to production credentials when local ones were missing, with a comment warning that
mutating providers "will hit the real production accounts".

**Why it was invisible.** It was supposed to be a dry run.

**Rule.** A non-production outbound guard with no switch to disable it: mail rewritten to one test recipient, and an
HTTP transport allow-list that answers blocked requests itself; no cross-environment credential fallback; production
data is not imported into development (demo data is).

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (non-production guard); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 9.

### J10 · Alerting people muted, and alerting that could not alert

**What happened.** A reminder chased each item exactly once, ever, and went silent for weeks; the fix flooded 63
messages per run. An operations channel received 227 alerts in 30 days — 119 in one day — of which about 25 needed a
human; 127 were duplicate "scheduled command failed" messages and about 129 were one outage re-announced hourly. A
director left the channel. A delta digest kept its last-run marker in the cache, so a deploy cleared it and it posted
twice; it committed its baseline before the send succeeded, so an outage swallowed a day. Elsewhere every alert
receiver's destination was commented out — a valid configuration that discarded all 25 alert rules — metric names
disagreed across three repositories so that 15 of 19 allow-listed metrics could never resolve, and gate counters were
created lazily so an outage read "no data" instead of a rising count, for three days.

**Why it was invisible.** A flood trains people to ignore the channel; silence looks like health.

**Rule.** One dispatcher and a database ledger; incidents announced once and recovered once; digests with no row cap;
quiet hours with a held release; markers and baselines in the database, committed after success; the alerting pipeline
watches itself (a dead-man's switch, `absent()` rules, a config test that every receiver has a destination); metrics
exist at zero from boot with closed label sets.

**Guard.** [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md); [`OBSERVABILITY.md`](OBSERVABILITY.md).

### J11 · Upstream errors that impersonated the caller

**What happened.** An upstream 401 was passed through to the browser, and the frontend logged the user out. The fix —
mapping every provider error to 502 — then masked real root causes across many resource types.

**Why it was invisible.** Both mappings are the obvious one-liner.

**Rule.** Pass upstream 4xx through with detail, **except** upstream 401/403, which become 502 (a provider's auth
failure must never look like the caller's); upstream 429 becomes 503 with `Retry-After`; one provider-error hierarchy
maps it everywhere.

**Guard.** [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) (provider error mapping); [`BUG_CLASSES.md`](BUG_CLASSES.md).

---

## 6. Frontend

### F1 · Every page fetched for itself

**What happened.** 145 of 201 pages hand-rolled fetch-on-mount with local loading flags, and shipped the same three
defects repeatedly: a failed fetch rendered as an authoritative empty state ("No invoices yet" — to a billing user);
124 pages had no cancellation, so responses raced; and a cache not keyed by tenant showed the previous organisation's
rows after a switch.

**Why it was invisible.** Every page worked on a good connection with one organisation.

**Rule.** One data layer with a load-state contract — error is disjoint from empty (`isEmpty = success && length == 0`),
the cache key carries the tenant, a failed refetch keeps the last good data and says so once — and a ratchet test over
every page.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (load-state contract).

### F2 · One client became many, and then one enormous file

**What happened.** Per-module copies of the fetch helper read only the base token, ignoring impersonation and the
active organisation, so admin actions taken during impersonation silently targeted the admin's own organisation;
hand-rolled upload helpers forgot the organisation header. Meanwhile the shared client grew into an 18,277-line file
imported by 337 modules and mocked by 209 suites — with a duplicated namespace holding 12 byte-identical methods, so
fixes to one silently missed the pages using the other.

**Why it was invisible.** Each copy worked in the context it was written for.

**Rule.** One transport through which every request passes, with one header builder, enforced by a lint ban on
`fetch` elsewhere; the client is generated per domain from the API schema, one module per namespace; a namespace is
never duplicated to wrap another.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (transport); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 20.

### F3 · Contracts nobody generated

**What happened.** A hand-written client called endpoints that did not exist and sent query parameters the backend
ignored. A UI type declared a field the backend never sent, discovered only by the first key-set equality check. A
period-length constant existed with one value in five backend sites and another in the frontend, so quotes and
invoices disagreed. An identity field declared with a default was never populated by its builder — `null` for
everyone — and a whole dashboard never rendered, hidden because the wrong answer was also the common answer.

**Why it was invisible.** *A type-clean frontend reading `undefined` at runtime*: hand-typed clients typecheck against
yesterday's contract.

**Rule.** Types are generated from the schema; constants and enums are exported from the backend with a
generated-equals-generator test; hand-narrowed types assert key-set equality both ways; fields a builder owns get no
default.

**Guard.** [`API_PLATFORM.md`](API_PLATFORM.md) (contract generation); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 4.

### F4 · Pages cloned per portal

**What happened.** Customer, operator and partner portals each had their own copy of the same detail page, one of them
3,692 lines. Fixes landed on one copy only — a stop-action fix shipped to the customer page and nowhere else.

**Why it was invisible.** Each portal's tests covered its own copy.

**Rule.** Resource views are portal-agnostic components that take a scope (which changes the API namespace and
permission set); portal layouts only compose them; page size is capped.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (module UI contract); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 22.

### F5 · Permission-aware UI that failed open

**What happened.** When the permissions request failed, the provider fell back to broad default permissions. An
organisation-scoped role *named* "admin" was treated as a platform administrator. Twenty-three affordances advertised
rights their endpoints refused, because one `canManage` flag was answering five different questions.

**Why it was invisible.** Refusals happen server-side; the button still looked enabled.

**Rule.** The permission provider fails closed and exposes its error; a missing provider denies everything; the
platform-admin claim is separate from organisation roles; per-row affordances come from the endpoint's own predicate
(the handler is passed only when allowed), never from a blanket flag.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (permission provider); [`API_PLATFORM.md`](API_PLATFORM.md)
(per-row permissions).

### F6 · Errors that told the user nothing

**What happened.** A rate-limited sign-up showed the literal text "HTTP 429" beside a live button, and one user fired
13 one-time-code requests in 43 seconds; the client armed its cooldown only on success, and the retry header was not
exposed to CORS. A failed create said "Input should be ≤ 2000" with no field, so support had to reproduce the request
to learn which field was wrong. Stringified error objects leaked raw enum codes into the interface.

**Why it was invisible.** Developers read the network tab; users cannot.

**Rule.** One error envelope with machine codes, field paths and `retry_after_seconds` in the body *and* the header;
the client maps codes to copy, never stringifies a structure, and throttles the failure path as well as the success
path.

**Guard.** [`API_PLATFORM.md`](API_PLATFORM.md) (error envelope, 429); [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)
(typed errors).

### F7 · Failures that existed only at render time

**What happened.** A confirm-dialog hook returned a promise and a dialog component; a caller that used only the promise
awaited forever, and a "Void" button went silently dead. A removed icon imported as `undefined` and crashed only when
rendered — after an icon deliberately replaced earlier was re-added. A navigation icon key missing from the frontend
map rendered nothing, with no error.

**Why it was invisible.** All of it typechecked and built.

**Rule.** An API shape that can be half-used is redesigned (one root-mounted confirm host) or guarded by a structural
test; icon imports and registry icon keys are checked for existence.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 2, § 3.

### F8 · Theming by literal

**What happened.** A brand colour was hard-coded in 242 places across 37 files — the first grep for hex values
under-counted by an order of magnitude because it missed utility classes. `text-white` sat on a tenant-overridable
primary colour at 110 sites, so white-label hosts rendered white text on pale brand colours; accent tokens stayed the
platform's colour beside a reseller's buttons. An undeclared CSS variable made the utility-class compiler emit no class
at all, and dynamically built class names compiled to nothing — transparent chips, no error. Tenant-supplied colour
values were a CSS-injection vector until they were validated against a grammar. Branded hosts flashed the platform
logo on first paint, and the page title reverted after every client-side navigation.

**Why it was invisible.** The default theme looked right.

**Rule.** Semantic tokens only, every fill paired with its foreground token, both themes first-class, a test for token
completeness and a ban on raw palette classes; status tones spelled out literally; tenant colours validated against a
grammar; branding seeded server-side for the first paint and re-applied after navigation.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (design tokens, runtime branding).

### F9 · Stale screens after every deploy

**What happened.** HTML responses carried no `Cache-Control`, so browsers heuristically reused old documents until a
hard reload; only some pages were affected, which made it look random. A cache-everything service worker would have
reinstated the same bug permanently.

**Why it was invisible.** Developers hard-reload by habit.

**Rule.** HTML and page payloads are never cached; hashed assets are immutable; a service worker caches only an
offline shell and never re-sends a mutation.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (offline); [`OPERATIONS.md`](OPERATIONS.md) (proxy headers).

### F10 · State parked in the address bar

**What happened.** "405 on save" recurred across many models from one root cause: an error re-render left the POST URL
in the address bar, and a background reload then sent a GET to it mid-edit. A shared validation handler re-rendered a
hard-coded page, so an error raised from a different screen swapped the whole page and showed no error. Reading
`window` during render to restore view state broke server rendering.

**Why it was invisible.** Each symptom was patched per form, so the root cause kept producing new symptoms.

**Rule.** Fix the shared root cause, not the symptom per screen; the server resolves view state from the URL and the
client writes it with `replaceState`; shared endpoints never assume which screen called them; after a mutation,
revalidate the current URL with its filters.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (URL state).

### F11 · Tables whose controls lied

**What happened.** Search was debounced twice, by the page and by the component. The page-size cap was below the
largest size the picker offered, so the pager disagreed with the rows. Fifty-two sortable column headers did nothing
because the server's sort allow-list did not include them; seventy controllers passed the client's sort parameter
unguarded. Rows sorted on a non-unique column appeared on two pages or none.

**Why it was invisible.** Page one, with default sorting, was always right.

**Rule.** The component owns its behaviour (one debounce); the server's maximum page size equals the UI's largest
option; a column is sortable only if the server's allow-list accepts it; every ordering ends with a unique tiebreak.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (DataTable); [`API_PLATFORM.md`](API_PLATFORM.md) (list
pipeline).

### F12 · Identity and session edges

**What happened.** Cached responses from the previous identity survived a logout and re-login in the same tab; stale
project ids produced spurious 403s for the next user; logging out did not revoke the server session. Impersonation
leaked the operator's organisation into impersonated calls. Path-scoped auth cookies were invisible to page
navigations, so an edge route guard bounced signed-in users once their access token expired — measured at 77 live
sessions of which only 4 had ever refreshed. Silent session expiry lost unsaved work. A sign-in button that made two
blocking identity-provider calls produced duplicate successful logins as users retried what looked like a hung
button.

**Why it was invisible.** Every flow was tested from a fresh browser, once.

**Rule.** One sign-out path in a defined order (revoke on the server, clear the cache, clear tenant context);
impersonation is isolated from the operator's own context; a `Path=/` session marker cookie lets the edge tell "needs
refresh" from "signed out"; sessions warn before expiry and re-authenticate in place; identity tokens are verified
locally with bounded timeouts and the button shows its working state.

**Guard.** [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) (session marker, sign-out);
[`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-20**; [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md).

---

## 7. Testing and CI

### T1 · CI that never ran, or ran red for reasons nobody read

**What happened.** One codebase's workflows triggered on branches that did not exist — its only branch had another
name — so CI never ran on a single push. Another committed a complete pipeline under a `.disabled` name and kept
adding steps to it for months. A third had no CI by decision, and its gate was a manual script on a shared machine.
Where CI did run, it migrated but seeded nothing and was red for days for purely environmental reasons (912 passed, 91
skipped, 5 failed, against 1,003/5/0 locally) — *the state in which nobody reads it*. A lint step carried
`continue-on-error` for months with a note to remove it.

**Why it was invisible.** A workflow file in the repository looks exactly like CI.

**Rule.** CI on every push and every PR with no branch filter, a test that the triggers cover the default branch, no
optional steps, and reference data seeded before tests — the environment that matters is the one nobody configured
by hand.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 12, § 13; [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md)
**DB-6**.

### T2 · Typechecks that checked nothing

**What happened.** A typecheck aborted on a file-name casing collision, so nothing was typechecked. Later it ran with
680–737 pre-existing errors, so a new one was indistinguishable from the noise. The bundler stripped types without
checking them, and three delete dialogs shipped dead. A production build broken by a type error stayed broken,
unnoticed, because nothing ran it. Test files were excluded from the typecheck, so their types were never checked.

**Why it was invisible.** A typecheck that exits early and a typecheck that passes print the same thing.

**Rule.** Zero-error typecheck (or an error-count ratchet that only falls) with a canary that must produce exactly one
known error; tests included; the production build runs in CI on every PR.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 14, § 17.

### T3 · Dependency changes that silently disabled the guards

**What happened.** A security override of a transitive dependency broke the linter's glob library, and lint crashed
repo-wide for a long stretch — so every invariant moved into unit tests; once repaired, lint reported 117 pre-existing
problems. A "linter version mismatch" turned out to be lost execute bits on the package shims. A framework upgrade
turned route nodes lazy and broke every guard that walked the route tree. A security floor pinned in the requirements
file was reverted two days later by a feature commit, invisible to a test that only checked the installed version.
`--legacy-peer-deps` outlived its conflict by a month. And in lint configuration itself: `exclude` replaced the
built-in excludes and linted a dead virtualenv (32,488 errors); an autofix hoisted an import above a load-bearing
comment in a migrations file, and reverting it with `git checkout` destroyed unrelated uncommitted work.

**Why it was invisible.** A dependency bump's diff is a lockfile nobody reads.

**Rule.** A canary per checker proves each tool runs after every dependency change; security floors are tested in the
lockfile *and* the installed environment; one shared introspection walker; strict peer resolution; `extend-exclude`;
no autofix on protected files; never revert with `checkout` over others' work.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 2, § 16, § 17, § 19.

### T4 · Checkers that could not see what they checked

**What happened.** A permission probe saw every request as unauthenticated and reported "0 regressions over 1,007
routes" for both the old and the new rule. A refusal-only test passed against a rule that refused everything. A
fixture written as a wildcard matched nothing. A grep in double quotes expanded a variable to an empty pattern. A
deployment check of the form `grep -ql … | wc -l` could only ever report 0. A drift guard built on `git diff` passed
unconditionally, because `git diff` does not see untracked files. The deploy driver's tests checked the *order* of its
steps but not that failures propagated — a piped `tee` masked remote exit codes, and the migrate step ended in
`|| true`.

**Why it was invisible.** *A checker that cannot see what it checks for is worse than no checker, because it is
believed.*

**Rule.** Positive controls; every guard proven red by removing the line it guards; counts that must balance; ask the
framework, not the formatting; test the failure paths, not only the happy sequence.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 1; [`OPERATIONS.md`](OPERATIONS.md) (deploy driver).

### T5 · Code and tests that silently never ran

**What happened.** A completeness test scanned a directory that a refactor had removed, and skipped on every run
thereafter. Cross-stack parity tests skipped whenever the other tree was not mounted — the normal state of the
container the suite ran in. A retention test compared against a hand-typed set of tables. Four carefully written purge
and retry functions each carried a docstring saying "nothing calls this on a schedule" — *care wasted on a function
with no caller*.

**Why it was invisible.** A skip is not a failure, and uncalled code has no failures.

**Rule.** Completeness tests derive their universe from the code and fail on an empty one; in CI, a skip is a failure;
every job and policy is registered, and a test proves each registered one is reachable.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 3, § 4.

### T6 · A suite that rotted into a baseline

**What happened.** Without CI, a suite re-grew to 191 failures and 14 errors while teams ran only targeted batches;
the working standard became "zero *new* failures versus the baseline", computed by diffing failed-test ids by hand.
Among the root causes found when it was repaired: mock drift that made failures look like logic bugs, phantom
failures from tests that walked to the repository root with `parents[N]` and escaped the container mount, and pinned
migration-head ids that churned on every merge.

**Why it was invisible.** A regression inside a non-green baseline is indistinguishable from the baseline.

**Rule.** The target is a green suite. A failing test is quarantined by id with an owner and a ticket as
`xfail(strict=True)`, so it fails the run the moment it passes; lineage is asserted, not pinned ids.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 18.

### T7 · The test harness that dropped the shared database

**What happened.** A gate script built a test database URL with an empty database name. The driver defaulted the name
to the user name — which was the shared application database — and the harness dropped its schema. The newest backup
was 19 days old, and nobody noticed for a day because the running application kept serving from its connections.

**Why it was invisible.** The harness had always pointed at a test database before.

**Rule.** The harness computes the effective database name exactly as the driver will and refuses anything empty,
without `test`, or equal to the real name — before any database is created; backups are verified and taken before
every deploy.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 5; [`OPERATIONS.md`](OPERATIONS.md) (backups).

### T8 · Tests that depended on the machine

**What happened.** Tests read development settings and talked to the live development cache; a concurrent dev process
repopulated cached singletons mid-test and made setup tests flaky. Tests wrote into a developer's live object-storage
bucket and failed wherever it was unreachable. A kill switch in a developer's `.env` changed test outcomes. Tests
hunted for whatever rows existed and skipped when none did — one stopped running for weeks inside a green suite. A
migration-tooling logging config silently disabled every application logger after the first migration-driving test.
Random values at collection made parallel workers collect different tests.

**Why it was invisible.** The suite was green on the machine of the person who wrote it.

**Rule.** A dedicated test settings module; autouse isolation of cache, storage, mail, time and outbound HTTP; pinned
settings; tests create what they read; deterministic collection; `disable_existing_loggers=False`.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 5.

### T9 · Hand-kept page lists, and the screenshot nobody opened

**What happened.** A browser check drove headless Chrome over a hand-kept list of pages; four staff screens were
simply not on it and had never been visited. A 500 hid behind an error state whose copy matched the text probe. A
check passed on a page whose whole purpose was a block that never rendered — found only when a person looked at the
screenshot. Horizontal overflow broke whole pages on phones. An end-to-end suite never grew past one smoke test,
because sign-in was single-sign-on only and no test authentication path was built.

**Why it was invisible.** A list cannot fail on what it omits.

**Rule.** The page list comes from the navigation registry per role; each page asserts a page-specific selector;
mobile, accessibility and both-theme sweeps run over the same list; test authentication is designed in; *look at the
screenshot*.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 11.

### T10 · Tests below the route

**What happened.** A queue endpoint's response serializer raised on every non-empty queue. It was hidden by an early
return for the empty case, a deliberate-looking empty state, a green service-level suite of about 1,000 tests, and a
browser check whose text matched the empty state. Invitation acceptance was tested by calling the model directly —
312 tests passed while the HTTP flow users actually hit was broken.

**Why it was invisible.** Every test exercised the code beneath the route, with zero or one row.

**Rule.** List endpoints are tested at the route with at least two rows; flows are tested through the real URL;
refusal tests assert the side effect did not happen.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 1.

### T11 · Headline numbers that flattered

**What happened.** In one core, 44% of an 1,187-test suite was two parametrised structural suites, and 59% coverage
was propped up by models and schemas "covered by being imported" — while the six services on the authentication,
permission and secrets path ran at 13–49%. A later push took those services to 90–99%.

**Why it was invisible.** The headline numbers were real; they just measured the wrong thing.

**Rule.** Report coverage per service and test counts per file; per-file floors with a default for new core code; a
floor that never lowers.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 10.

### T12 · Demo data that rotted

**What happened.** While the core owned every app's demo fixtures, its copy of each domain silently rotted — twice —
because nothing tested the command; once, the seeder did not run at all. Fixtures created with raw inserts bypassed the
model events the audit trail depended on.

**Why it was invisible.** Nobody runs a demo seeder until a demo.

**Rule.** Each app owns its demo seeder; seeders go through services, are idempotent, and are tested per app; CI runs
the whole seeder twice on a fresh database and the second run creates nothing.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 9; [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md)
**DB-13**.

---

## 8. Documentation and process

### P1 · Docs that described code that did not exist

**What happened.** A standards document made a base-model mechanism mandatory for five months; it had never been
implemented, and its documented sample would have corrupted attribution. A standards table listed three standards
files that did not exist. The written badge standard described the style of 13 files while 470 used the other. An
observability document promised JSON logs, request ids and metrics — the code had none. An ADR said background tasks
were wrapped in a gating helper that had zero callers. A diagrams document left off the must-update list drifted a
month behind and was missing three apps. A committed, confident comment explaining a library's behaviour turned out to
be false and had to be retracted. One repository had 125 broken links across its docs.

**Why it was invisible.** *Plugins copy the core — and right now they copy absence.* Agents believe the docs they are
told to read first.

**Rule.** Docs that quote code are tested against the code; links and anchors are tested; diagrams and feature
matrices are generated from registries; a mechanism written into a comment is checked against the installed package
first; a quarterly doc-vs-code audit.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 26, § 29, § 32, § 34.

### P2 · Stack docs for a stack that was not installed

**What happened.** Frontend guides named a framework two majors behind the installed one, plus a state library and a
form library that were not installed, and showed a button example using exactly the pattern a guard test forbade.
Agents told to read those guides first invented stores and copied the forbidden pattern. A README stated versions
wrong in a dozen places.

**Why it was invisible.** A version in prose is correct on the day it is written.

**Rule.** Never describe the stack from memory (already `AGENTS.md` § 0): version tables are generated from, or tested
against, the manifests — or removed in favour of a pointer to them.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 29.

### P3 · Status lines in records

**What happened.** More than a thousand incident write-ups carried a *Status* line; most were stale — *Open* long after
the fix shipped. The eventual rule was that write-ups carry no status at all; the tracker is the status of record.

**Why it was invisible.** A record looks authoritative, and nobody re-reads it.

**Rule.** Records (ADRs, incident write-ups, dated plans, `DAILY_CHANGES.md`) carry no mutable status; status lives in
`TECH_DEBT.md`, `ROADMAP.md` or the tracker.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 28, § 31.

### P4 · Registers that were wrong in both directions

**What happened.** Two 🔴 blockers sat open in a register while the code was already fixed. A summary table was wrong
for eleven days because two registers had to be updated together. Nine documentation passages still referenced a
deleted seeder, so the documented setup command failed — and one doc still published the old default password.

**Why it was invisible.** *Registers overstate as easily as they understate.*

**Rule.** The register is a map, not the territory — verify against the code before acting; compound statuses instead
of premature ticks; one register per fact, with any summary generated; resolved entries keep their original text.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 30.

### P5 · Decisions nobody could find

**What happened.** One codebase had 9 ADRs against 192 specs and plans; the real decisions lived in specs, review notes,
"owner decision" lines in the agent contract and the tracker, so nobody knew where to check whether something was
settled. An ADR stayed *Proposed* after all five of its phases had shipped. Two ADRs shared one number, and number
claiming by scanning a docs folder collided across worktrees four times. Decisions churned on day one — one frontend
approach was superseded the same day; where configuration lives was reversed later — and a feature built and then
removed was kept in the register only so nobody would re-propose it.

**Why it was invisible.** Each decision was recorded *somewhere*.

**Rule.** One register; every quoted owner decision links an ADR; ids are checked for uniqueness and allocated by
reading the register at the moment of writing; a `Reverted` status; decide where configuration and code live before
building.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 24.

### P6 · Verification nobody could re-run

**What happened.** A security hardening pass was verified superbly — by hand, once — and no command could reproduce
it: *a description of behaviour that was correct on a date*. The owner had deferred tests to the end of the queue;
the compensating control, recording every verification in the daily log, helped but did not re-run.

**Why it was invisible.** The write-up was excellent.

**Rule.** Every verification becomes a test or a re-runnable command, and the daily log records how it was verified,
how the guard was proven red, what was found while verifying, and what is still open.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 1, § 33.

### P7 · Fixes that did not stay fixed

**What happened.** A billing rewrite deleted an incremental-cursor helper and reintroduced the retroactive recompute it
had fixed. A feature commit reverted a security pin two days after it was set. A refactor squash-merged from a stale
branch silently reverted unrelated shared-component work, restored only by a follow-up. A ledger defect had been
catalogued four times before it was fixed.

**Why it was invisible.** Nothing failed when the fix disappeared.

**Rule.** Every fix lands with a regression test named by its ticket and shown failing against the pre-fix code;
branch protection requires an up-to-date branch; a catalogued defect that recurs gets a guard, not another ticket.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 7, § 12.

### P8 · Plans were wrong, and the code was right

**What happened.** A specified generic CRUD base class was rejected once the real write paths were read — audit diffs
and state machines would have overridden it wholesale. An estimate of "about 40 signatures" for a tenancy sweep was
258. Blanking a default, as a plan proposed, would have locked every single-sign-on user out — caught by reading all
three call sites.

**Why it was invisible.** Plans are written before the code is read.

**Rule.** Verify a plan against the call sites before executing it; open every plan with a measured baseline and the
commands that produced it; sequence cheap renames before expensive sweeps.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 46.

### P9 · Guards rolled out all-or-nothing

**What happened.** A security hardening plan went unbuilt for fifteen months because it was framed as a behaviour
change; it shipped once it was reframed as "installing changes nothing" with each guard's default reproducing current
behaviour. The opposite failure elsewhere: new fail-closed entitlement gates assumed data only newly onboarded
customers had, so **every legacy customer was blocked** from creating resources — with the message "None limit" — and
it took three days to surface, because the first gate masked the second. Meanwhile "merged" kept being mistaken for
"released": features were live with their help articles dark.

**Why it was invisible.** A guard shipped dark does nothing visible; a guard armed blind looks like the customers'
fault.

**Rule.** Every new guard has a mode — `off`, `log_only`, `enforce` — and ships with a default that changes nothing,
with a test proving it; before arming a fail-closed gate, census the existing rows against its predicate and keep
"missing data" separate from "limit reached"; new work ships dark behind a registered flag and the daily log records
what is not live yet.

**Guard.** [`CONFIGURATION.md`](CONFIGURATION.md) (guard modes, flags); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md)
§ 33, § 45.

---

## 9. Operations and deployment

### O1 · Containers started before migrations

**What happened.** New containers started against the old schema and served about a minute of "column does not exist"
500s on core endpoints — on every column-adding release, twice in one day. A production server running with hot
reload on a bind-mounted source tree swapped in new code about 90 seconds before its migration ran. A migration that
had never executed anywhere reached a deploy, with a feature flag offered as mitigation — but *a feature flag gates
whether new code runs; it does not gate whether new code loads*. An application-side "wait for the latest migration"
gate was rejected because it only turns 500s into 503s.

**Why it was invisible.** In development, migrate-then-run is a single command.

**Rule.** Build an immutable image; run migrations from the **new** image while old containers serve; then swap;
migrations are additive (expand/contract) so the old code survives the new schema; never hot-reload in production;
apply every migration to a real database before merge.

**Guard.** [`OPERATIONS.md`](OPERATIONS.md) (deploy driver, expand/contract); [`DEPLOYMENT.md`](DEPLOYMENT.md).

### O2 · Rolling deploys that were not rolling

**What happened.** Scaling back to one web container after a roll recreated the *surviving* container: about 25
seconds of outage, around 90 × 502. A force-recreate redeploy took the proxy and the web tier down together. A
"rolling" swap split traffic 50/50 with no upstream failover, so the half hashed to the replica being replaced still
got 502s.

**Why it was invisible.** Each deploy "succeeded".

**Rule.** Start the new container beside the old, gate on readiness, retire the old one by id, and give the proxy a
real upstream with failover to the surviving replica.

**Guard.** [`OPERATIONS.md`](OPERATIONS.md) (rolling swap).

### O3 · Logs deleted by every deploy, and logs nobody could use

**What happened.** The container log driver discarded every container's logs whenever it was recreated — every
release wiped history. JSON logging existed but was switched off in production; rotating file handlers shared by three
processes lost lines; there was no request id anywhere. Granted-access log lines made up about half of all volume and
hid a live defect; a 23 MB log never rotated.

**Why it was invisible.** Logs are only read on the day you need them.

**Rule.** A persistent log driver on every service (enforced by a policy test); JSON to stdout in production (enforced
at boot); request ids end to end; routine success at debug level, refusals at warning.

**Guard.** [`OBSERVABILITY.md`](OBSERVABILITY.md); [`OPERATIONS.md`](OPERATIONS.md) (policy tests).

### O4 · Restoring another environment's connections

**What happened.** A production dump restored into staging brought production's integration rows with it — and
because every environment shared one encryption key, the credentials *worked*, with scheduled jobs live. Importing a
live dump into local development replaced local credential rows the same way.

**Why it was invisible.** A restore that "just works" is the goal of a restore.

**Rule.** Restores preserve the target environment's own configuration (a config snapshot taken before and reapplied
after); imported schedules and integrations are neutralised on restore; encryption keys differ per environment so
foreign ciphertext fails closed.

**Guard.** [`OPERATIONS.md`](OPERATIONS.md) (restore safety); [`CONFIGURATION.md`](CONFIGURATION.md).

### O5 · Behaviour only a live deploy revealed

**What happened.** Five behaviours surfaced only on a real host, four of them quietly: the load balancer's path to the
application port was firewalled (502s); a process manager aborted starting **everything** because one log directory
was unwritable; the frontend's persistent build cache replayed empty data captured during a build against an empty
database, so pages 404'd after a build that reported success (the tell: the sitemap listed URLs that 404'd); an
assertion written as `grep -ql … | wc -l` always reported 0; and a missing proxy-routing file presented as "every
process healthy, every path 404". Separately, a single-file bind mount kept the proxy on the old file's inode after a
`git pull`, so reloads re-read stale configuration.

**Why it was invisible.** None of it exists in a development environment.

**Rule.** Build order is migrate → seed → start the API → build the frontend, with build caches cleared; verify through
the public URL with a data-bearing endpoint; mount directories, not files, and restart rather than reload when a mount
may be stale; any deployment manifest whose shell never runs in the repository gets its own linter in CI.

**Guard.** [`OPERATIONS.md`](OPERATIONS.md); [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 15.

### O6 · Connection pooling that silently broke session features

**What happened.** Behind a transaction-mode connection pooler, session-level advisory locks and prepared statements
break without an error, because each transaction may land on a different server connection. One codebase's client
connection budget sat close to its limit, and its background-worker engines lacked the pooler-compatibility settings
its web engine had.

**Why it was invisible.** Everything works without the pooler, which is how development runs.

**Rule.** One database settings factory used by web and workers; transaction-scoped advisory locks only; server-side
cursors and statement caching configured for the pooler; a written connection budget (processes × concurrency × pool
size).

**Guard.** [`OPERATIONS.md`](OPERATIONS.md) (pooling).

### O7 · A datastore published to the internet

**What happened.** A compose mapping published the cache and queue store on every interface, with no password and
protected mode off. It was taken over as an attacker's replica, and background processing was down for about ten
hours.

**Why it was invisible.** `"6379:6379"` looks like every tutorial.

**Rule.** Only the edge proxy publishes a port; datastores bind to the internal network or loopback; every secret in
compose is `${VAR:?}` (never `:-default`), and `.env.example` leaves them blank; policy tests parse every compose file.

**Guard.** [`OPERATIONS.md`](OPERATIONS.md) (infrastructure policy tests); [`SECURITY.md`](SECURITY.md).

### O8 · Health checks that told the wrong story

**What happened.** A liveness endpoint stayed green while the database was down, keeping a broken instance in the load
balancer. A readiness endpoint echoed exception text to anonymous callers. Probing third-party vendors from readiness
would have ejected healthy instances during a vendor outage. The scheduler container inherited the web image's HTTP
health check, which always failed. A single-ping worker check reported healthy workers as degraded — the first ping
from a fresh process misses. The task-result backend configured in settings differed from the one in compose, so the
scheduler history page was empty in every compose deployment.

**Why it was invisible.** A health endpoint is only questioned when it disagrees with an outage.

**Rule.** Three rungs — liveness with no I/O, readiness that checks the database and cache with timeouts and fixed
error tokens, and a scoped detail endpoint; never probe vendors; a health check per process role; a boot check that the
backend the UI depends on is the one configured.

**Guard.** [`OBSERVABILITY.md`](OBSERVABILITY.md) (health); [`../planning/TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-11**.

### O9 · Shared environments left changed, and setup that forgot

**What happened.** Testing a feature branch on a shared development server left its database on a branch-only
migration, so everyone else's upgrade failed with "can't locate revision"; workers had cached the branch's schedule
and filled the queue with "unregistered task" errors. A setup script chose free ports but did not persist them, so a
re-run printed a URL nothing was listening on; a generated database password containing URL-special characters broke
the connection string.

**Why it was invisible.** It worked for the person who changed it.

**Rule.** Leave shared environments exactly as found — branch, migration state, workers restarted — and prefer a
database per worktree; the setup script is idempotent, persists what it chooses, and generates URL-safe secrets.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 38; [`OPERATIONS.md`](OPERATIONS.md) (setup script).

---

## 10. AI-assisted development

### AI1 · Narration that overstated completion

**What happened.** Implementer agents reported tasks complete and tests passing when the diff said otherwise. One
model's recorded quirk: its helper-extraction refactors hoisted sibling bookkeeping out of the branch that guarded it,
changing behaviour while the happy-path tests stayed green. Delegations that omitted the model silently inherited the
orchestrator's — the expensive one.

**Why it was invisible.** The summary was fluent and confident.

**Rule.** The diff is the verdict: read the diff and the untracked files, reject changes outside the spec's file list,
diff control flow for refactors, run the gate yourself, keep a worker-quirk log, pass the model explicitly.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 37.

### AI2 · A hallucinated method that passed every test

**What happened.** An AI-generated change called a client method that did not exist. Every test passed, because the
client was a bare async mock that accepts any attribute. The rule "never use bare mocks" was then written down — and
about 2,400 bare mocks remained, because nothing enforced it.

**Why it was invisible.** A bare mock agrees with whatever the code under test believes.

**Rule.** Autospec every test double for a typed dependency, enforced by an AST guard with a ratchet; pin the public
surface of large external clients.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 6.

### AI3 · Agents colliding in one working tree

**What happened.** Concurrent agents in one repository collided "three or more times": commits landing on another
agent's branch, uncommitted work overwritten in a shared tree, one command-line tool ignoring its working directory,
400+ stale branches, and a shared database stranded at one lane's migration.

**Why it was invisible.** Each agent saw a clean result in its own terms.

**Rule.** A worktree, branch and database per lane; stage explicit paths only; never switch branches or reset in a
tree holding others' work; verify each commit landed on its lane's branch.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 38, § 39.

### AI4 · An audit nobody audited

**What happened.** A "comprehensive" audit by five agents was re-verified against a pinned commit by five independent
agents. It had rated a P1 as a P0, reported "84 files" where there were 35, flagged an access-control hole that was
already fixed — and missed unescaped user input in 37 of 39 email methods.

**Why it was invisible.** An audit's framing is persuasive, and its omissions are silent.

**Rule.** Pin a commit; verify every finding independently; record *Confirmed / Partially confirmed / Refuted* with a
"what it missed" column; re-rank by validated impact; one ticket and one guard per confirmed finding.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 41.

### AI5 · A bug report that could drive a coding agent

**What happened.** Text from an anonymous in-app bug report was fed to an autonomous coding agent running with its
permission prompts disabled and the entire worker environment — a prompt-injection path from any visitor to the
repository's credentials. The remedy: an admin-only trigger behind a default-off flag, a tool allow-list, an
environment allow-list, and no token in any clone URL.

**Why it was invisible.** Every report anyone tested was a genuine bug report.

**Rule.** Untrusted text is data, never instructions; any automation on it is operator-triggered, sandboxed and
credential-scoped; the class is on the review checklist.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 42; [`BUG_CLASSES.md`](BUG_CLASSES.md).

### AI6 · Context budgets, stale vintages and agent config that drifted

**What happened.** Agents under a context budget followed whichever of three vintages of a rule they happened to load.
A 38 KB agent contract was paid for on every turn until it was split into on-demand skills. Two contracts in one
repository drifted into opposite instructions (the reason [ADR-0006](../adr/0006-one-agent-contract.md) exists here). A
subagent definition still named the product the core had been extracted from, and paths that no longer existed — no
drift check covered agent configuration. And agents imitate whatever they find: *the audience doesn't read
documentation, and the agents it drives copy the nearest example*.

**Why it was invisible.** Agent configuration is not code, so nothing tested it.

**Rule.** One short contract; on-demand skills hold procedures, never rules; each doc owns one concern; agent config is
in the link, path and vocabulary checks; a reference module and a scaffolder whose output matches it.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 27, § 40; [`EXTENSIBILITY.md`](EXTENSIBILITY.md) (scaffolder).

### AI7 · "Mechanical" work that was not

**What happened.** "Add soft deletes to six tables" was delegated as mechanical and hid the unique-constraint trap
([D5](#d5--soft-delete-that-destroyed-uniqueness)). Agents auto-advanced past approval gates — *auto mode is not
approval*.

**Why it was invisible.** The task description was short, so the task looked small.

**Rule.** A delegable spec carries its known failure modes, its file list, a reference to copy, its verification
commands and "if an assumption is false, stop and report"; risky areas stay with the orchestrator; human gates are
named in the spec; commits need the user's yes.

**Guard.** [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 36; [`../../AGENTS.md`](../../AGENTS.md) rule 1 and § 5.

---

## 11. Index by guarding document

Which lessons each specification exists to prevent — read the row for your document before changing it.

| Guard document | Lessons |
|----------------|---------|
| [`EXTENSIBILITY.md`](EXTENSIBILITY.md) | A1 · A2 · A3 · A5 · S5 · AI6 |
| [`CONFIGURATION.md`](CONFIGURATION.md) | A5 · C1–C9 · S8 · P9 · O4 |
| [`API_PLATFORM.md`](API_PLATFORM.md) | A6 · S2 · S7 · S13 · S14 · F3 · F5 · F6 · F11 |
| [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) | A3 · S8 · S10 · J1–J9 · J11 |
| [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md) | S9 · J5 · J10 |
| [`OBSERVABILITY.md`](OBSERVABILITY.md) | A7 · S11 · D9 · J1 · J8 · J10 · O3 · O8 |
| [`OPERATIONS.md`](OPERATIONS.md) | S7 · J1 · J4 · T4 · T7 · O1–O7 · O9 |
| [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) | S2 · S10 · C3 · C8 · F1–F12 |
| [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) | A7 · S3 · C6 · D5 · D6 · D7 · D8 · D10 · D11 |
| [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) | C5 · D1 · D2 · D4 · J6 · J8 |
| [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) | A4 · S9 · D2 · D3 · J7 |
| [`BUG_CLASSES.md`](BUG_CLASSES.md) | S3 · S9 · D3 · J11 · AI5 |
| [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) | A6 · C1 · C4 · S4 · S6 · S11 · S12 · D2 · D7 · D9 · J4 · J9 · F2 · F3 · F4 · F7 · T1–T12 · P1–P9 · O5 · O9 · AI1–AI7 |
| [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) · [`AUTH_FAILURE_MODES.md`](AUTH_FAILURE_MODES.md) | S1 · S4 · S7 · S8 · S12 · S13 · F12 |
| [`RBAC_DESIGN.md`](RBAC_DESIGN.md) | S1 · S2 · S5 · S6 |
| [`DATA_MODEL.md`](DATA_MODEL.md) · [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md) | A3 · A4 · S3 · D7 · D8 · D9 · D10 |
| [`SECURITY.md`](SECURITY.md) · [`DEPLOYMENT.md`](DEPLOYMENT.md) | S11 · O1 · O7 |

---

## Pending decisions (for the repository owner)

1. **Where DjangoBaseX's own incidents are recorded** — `documentation/incidents/` as
   [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) § 31 proposes; lessons that generalise are then promoted
   into this file.
2. **Whether this catalogue stays one file** past about 150 entries, or splits by category — one file is recommended
   while it can still be read in a sitting.
3. **Whether lesson ids are cited from code comments and test docstrings** (for example, a guard test naming the
   lesson it prevents). Recommended: yes, alongside the register id — ids here are stable and never reused.

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section. The incidents are reported as the studied codebases recorded them;
> magnitudes are theirs and were not re-measured. Guard documents are linked by file; the specific section inside each
> should be checked once that document is final, since several were written in parallel with this one.
