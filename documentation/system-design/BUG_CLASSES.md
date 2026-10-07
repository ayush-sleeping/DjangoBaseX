# Recurring bug classes — the review checklist

**A numbered register of bug classes that have each shipped as a real production bug somewhere, with the form
each takes in Django and Next.js, the guard that stops it, and the one question a reviewer asks.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.
>
> The guards named below are specified tests and checks, **not existing ones**. Until a guard exists, its class
> is enforced by review alone — which is why the review question matters.

## Scope — read first

**Owns:** the cross-cutting register of recurring bug classes (`BC-nn`), the review questions, the trigger areas
that make the checklist mandatory, the post-mortem procedure that feeds the register, and the PR-template
checkbox block.

**Does not own:**

| Topic | Owner |
|---|---|
| The authentication/authorization failure catalogue (F1–F17) and its reasoning | [`AUTH_FAILURE_MODES.md`](AUTH_FAILURE_MODES.md) — cited here, not repeated |
| The mechanisms the guards test (list pipeline, error envelope, throttles, tokens, uploads) | [`API_PLATFORM.md`](API_PLATFORM.md) |
| Scoping, write narrowing, provenance, audit, actor stamping | [`DATA_MODEL.md`](DATA_MODEL.md) § 5, [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) |
| Environment identity, fail-closed defaults per registry, guard modes | [`CONFIGURATION.md`](CONFIGURATION.md), [`EXTENSIBILITY.md`](EXTENSIBILITY.md) |
| Queues, outbox, SSRF-safe client, provider errors, encryption | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| Money, numbering, bulk actions, exports | [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md); billing specifics in [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) |
| Load-state contract, cache keys, redirects in the UI | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) |
| Expand/contract, migration linting, deploy order | [`OPERATIONS.md`](OPERATIONS.md), [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md) |
| How to write tests that can fail, ratchets, CI | [`ENGINEERING_PRACTICES.md`](ENGINEERING_PRACTICES.md) |
| Design anti-patterns that are not bugs (god files, speculative primitives, doc drift) | [`LESSONS_LEARNED.md`](LESSONS_LEARNED.md) |

---

## 0. The rules in one screen

1. **Every class here has shipped as a real bug.** Review against this list, not against a generic top-ten — a
   checklist of bugs that actually happened catches the next one; a generic list catches the first one. → [§ 1](#1-how-to-use-this-register--process)
2. **A change that touches a trigger area answers that area's review questions** in the PR. → [§ 1](#1-how-to-use-this-register--process)
3. **Every class names a guard that can fail** — a test, a system check or a lint rule. A class whose guard is not
   built yet has a [`TECH_DEBT.md`](../planning/TECH_DEBT.md) row. → each entry
4. **A guard is proved red once**: delete the line under test, watch it fail, say so in the PR. A guard nobody has
   seen fail is a belief. → [BC-45](#bc-45--tests-that-cannot-fail)
5. **A fix for a bug in a class adds or strengthens that class's guard in the same change.** A fix without a guard
   is reverted by the next large rewrite — it has happened to money code and to dependency pins alike. → [§ 13](#13-how-a-post-mortem-feeds-the-register--process)
6. **Every post-mortem cites a class or adds one.** No incident closes without it. → [§ 13](#13-how-a-post-mortem-feeds-the-register--process)
7. **IDs are permanent.** A class is retired with a date and a reason, never deleted and never renumbered;
   commits, tests and post-mortems cite it by number. → [§ 13](#13-how-a-post-mortem-feeds-the-register--process)
8. **Authorization tests act as a non-bypass user who is authorised for a *different* object.** A superuser, or a
   user who holds nothing, passes before and after most fixes and proves nothing. → [BC-01](#bc-01--tenant-scoping-and-idor), [BC-45](#bc-45--tests-that-cannot-fail)
9. **One decision, one function.** Two copies of a rule — a scope, a login completion, a bypass list, a ledger
   write, an environment check — is the precursor of a third of the classes below. → [BC-09](#bc-09--bypass-lists-duplicated), [BC-10](#bc-10--n-login-paths-drifting), [BC-29](#bc-29--money-moved-outside-the-single-writer)
10. **Every default states which way it fails, and the safe way wins.** → [BC-36](#bc-36--fail-open-defaults)
11. **"Nothing" and "everything" are never represented by the same value.** → [BC-02](#bc-02--none-means-all-sentinels)
12. **Untrusted text is data** — in templates, in redirects, in URLs the server fetches, in spreadsheets, and in
    prompts. → [§ 5](#5-injection-and-untrusted-input--process)

---

## 1. How to use this register — **Process**

**What.** Each entry has the same six parts:

| Part | Says |
|---|---|
| **Class** | The bug, in one sentence general enough to recur in any module |
| **Shipped as** | A real incident, described generically, that proves the class is not hypothetical |
| **Django / Next form** | The concrete shapes it takes in *this* stack — what to grep for |
| **Guard** | The test, check or lint that prevents it, and what it asserts |
| **Review question** | The one question a reviewer asks of any diff in its area |
| **See also** | Where the mechanism or the deeper reasoning lives |

**Trigger areas — the checklist is mandatory when a change touches:**

| Area | Classes to review |
|---|---|
| Any endpoint, viewset, serializer or queryset | BC-01 – BC-07, BC-12, BC-17 |
| Roles, grants, invitations, tokens, `/me` | BC-06, BC-08, BC-09 |
| Sign-in, sessions, MFA, SSO, password flows | BC-10, BC-11, BC-13, BC-14 |
| Rate limiting, proxies, client IP | BC-13, BC-35 |
| Logging, error handling, error tracking | BC-14, BC-16, BC-42, BC-44 |
| Secrets, encryption, integration credentials, agent config | BC-14 – BC-16 |
| Templates, email, notifications, rich text | BC-18, BC-19 |
| Outbound HTTP, webhooks, PDF rendering, anything fetching a URL | BC-20 |
| Uploads, files, exports, search | BC-21, BC-22 |
| AI features, agents, automation fed by user text | BC-23 |
| Money, balances, invoices, payments, quotas, numbering | BC-24 – BC-30 |
| Background jobs, schedules, caches | BC-31 – BC-35 |
| Settings, flags, environment, new guards | BC-36 – BC-38 |
| Migrations, seeders, data fixes | BC-39 – BC-41 |
| Frontend data display, API contracts | BC-42, BC-43 |
| Integrations with third parties | BC-20, BC-34, BC-44 |
| Tests, CI, guards themselves | BC-45 |

**The index.**

| ID | Class | Primary guard |
|---|---|---|
| [BC-01](#bc-01--tenant-scoping-and-idor) | Tenant scoping / IDOR, including bulk and related fields | cross-scope 404 per model; zero-membership lists empty |
| [BC-02](#bc-02--none-means-all-sentinels) | "None means all" sentinels | scope helpers return querysets only |
| [BC-03](#bc-03--read-scoped-but-write-unscoped) | Read-scoped but write-unscoped | `PATCH` to an invisible row is 404 |
| [BC-04](#bc-04--layer-1-only-rbac) | Layer-1-only RBAC | `dbx.E003`; permitted user, other scope |
| [BC-05](#bc-05--the-forgotten-gate) | The forgotten gate | `dbx.E001`; route enforcement test |
| [BC-06](#bc-06--authority-inferred-from-names) | Authority inferred from names | no role-slug literals; permission `kind` metadata |
| [BC-07](#bc-07--hiding-mistaken-for-denying) | Hiding mistaken for denying; hidden props in payloads | payload key tests; orphan-page test |
| [BC-08](#bc-08--grant-writers-without-a-privilege-ceiling) | Grant writers without a privilege ceiling | every-writer completeness test |
| [BC-09](#bc-09--bypass-lists-duplicated) | Bypass lists duplicated | one `bypasses()` function; effective `/me` |
| [BC-10](#bc-10--n-login-paths-drifting) | N login paths drifting | one completion choke point, AST-guarded |
| [BC-11](#bc-11--user-enumeration) | User enumeration | byte-identical responses |
| [BC-12](#bc-12--mass-assignment) | Mass assignment | `__all__` refused; strict input |
| [BC-13](#bc-13--rate-limits-keyed-on-the-wrong-thing) | Rate limits keyed on spoofable input or per path | rotating-XFF and concurrency tests |
| [BC-14](#bc-14--secrets-in-logs-errors-and-urls) | Secrets in logs, validation errors, error tracking, URLs | canary test |
| [BC-15](#bc-15--secrets-in-tracked-configuration) | Secrets in tracked agent config and remote URLs | secret scanner; userinfo test |
| [BC-16](#bc-16--decryption-that-fails-open) | Decryption that fails open | decrypt raises; dedicated key check |
| [BC-17](#bc-17--per-user-data-in-a-shared-cache) | Per-user data in a shared cache | `no-store` test; tenant in cache keys |
| [BC-18](#bc-18--server-side-template-injection) | Server-side template injection | no non-literal templates outside the renderer |
| [BC-19](#bc-19--open-redirect) | Open redirect | one `safeNextPath()` with a payload table |
| [BC-20](#bc-20--server-side-request-forgery) | SSRF | one outbound client; hostile-URL table |
| [BC-21](#bc-21--upload-type-trusted-from-the-client) | Upload type trusted from the client | renamed-HTML test |
| [BC-22](#bc-22--spreadsheet-formulas-and-pattern-escaping) | CSV formula injection; `LIKE`/regex escaping | export cell helper; no raw SQL with non-literals |
| [BC-23](#bc-23--untrusted-text-into-ai-agents) | Untrusted text into AI agents | allow-listed env and tools |
| [BC-24](#bc-24--money-as-float-and-rounding-in-display-layers) | Money as float; rounding in display layers | float-on-money scan |
| [BC-25](#bc-25--recomputation-from-the-start) | Recomputation from the start on a forward-only meter | recompute-pattern scan |
| [BC-26](#bc-26--metered-is-not-billed) | Metered ≠ billed | billable-type registry completeness |
| [BC-27](#bc-27--payment-success-from-a-client-reachable-endpoint) | Payment success from a client-reachable endpoint | method allowlist; gateway-only success |
| [BC-28](#bc-28--currency-mismatch-converted-11) | Currency mismatch converted 1:1 | cross-currency arithmetic raises |
| [BC-29](#bc-29--money-moved-outside-the-single-writer) | Money moved outside the single writer | line-level source scan |
| [BC-30](#bc-30--check-then-act-without-a-lock) | Check-then-act without a lock | concurrency tests on PostgreSQL |
| [BC-31](#bc-31--side-effects-before-commit) | Side effects before commit | `on_commit` scan |
| [BC-32](#bc-32--unconditional-actor-stamping) | Unconditional actor stamping | job save preserves attribution |
| [BC-33](#bc-33--a-queue-with-no-worker) | A queue with no worker | queue ↔ worker test |
| [BC-34](#bc-34--a-cached-failure) | A cached failure | hit-only cache helper |
| [BC-35](#bc-35--per-process-state-across-workers) | Per-process state across workers | `dbx.E005`; `lru_cache` scan |
| [BC-36](#bc-36--fail-open-defaults) | Fail-open defaults | unknown-key default pinned per registry |
| [BC-37](#bc-37--environment-checks-that-a-typo-defeats) | Environment checks that a typo defeats | one predicate; literal-comparison scan |
| [BC-38](#bc-38--a-fail-closed-gate-armed-without-a-census) | A fail-closed gate armed without a census | `log_only` first; census in the PR |
| [BC-39](#bc-39--migrations-that-rewrite-operator-authored-content) | Migrations rewriting operator-authored content | authored-model scan of migrations |
| [BC-40](#bc-40--destructive-migrations-without-expandcontract) | Destructive migration without expand/contract | migration linter |
| [BC-41](#bc-41--migrations-faked-past-their-data) | Migrations faked past their data | data-plane self-check |
| [BC-42](#bc-42--failure-rendered-as-empty-or-zero) | Failure rendered as empty or zero | load-state ratchet |
| [BC-43](#bc-43--client-and-api-drifting-apart) | Client and API drifting apart | three contract drift checks |
| [BC-44](#bc-44--upstream-errors-mis-mapped) | Upstream errors mis-mapped | provider error table test |
| [BC-45](#bc-45--tests-that-cannot-fail) | Tests that cannot fail | proved-red; fail on empty universe |

---

## 2. Authorization and scoping — **Process**

### BC-01 — Tenant scoping and IDOR

**Class.** A caller reaches a row outside their scope by naming its id — through a detail route, a custom
action, a bulk endpoint, a writable related field, a nested route, an aggregate, a search or an export.

**Shipped as.** A refactor onto shared scope helpers put every tenant's resources on a global administrator's
own self-service dashboard. Elsewhere, membership of one group let a user read another tenant's resources; and
a scope applied to a list but not to its counters and filter dropdowns disclosed which other organisations
existed.

**Django / Next form.**
- `@action(detail=True)` doing `Model.objects.get(pk=pk)` instead of `self.get_object()`; `get_object_or_404(Model,
  pk=…)` in any view.
- A writable `PrimaryKeyRelatedField(queryset=Model.objects.all())` — attaches another tenant's row by id.
- Bulk: `Model.objects.filter(pk__in=ids).update(…)` / `.delete()` that never passed through `visible_to()`.
- Nested routes where the parent is scoped and the child is looked up by `pk` without `parent=`.
- Counts, sums, choice lists and "select all" computed from an unscoped queryset.
- A Next.js route handler or server component calling the API with a server-held credential instead of the
  user's own cookie — it acts with a reach the user does not have.

**Guard.**
- `tests/architecture/test_cross_scope.py` — for **every** model registered for scoping (DATA_LIFECYCLE), an
  `other_scope_actor` fixture (holds the feature permission, owns a *different* object) gets `404` on
  retrieve, update, delete and each detail action. Fails on an empty universe.
- `test_zero_membership_user_sees_empty_lists` — every list endpoint, a user in no scope, `count == 0`.
- `test_writable_related_fields_are_scoped` — introspects every serializer on a writable view (API_PLATFORM § 12).
- `run_list` refuses an unscoped queryset (API_PLATFORM § 1); bulk selection re-runs it.
- Ratchet scan: no `.objects.get(`, `.objects.filter(` or `get_object_or_404(` in `views.py`/`viewsets.py`.

**Review question.** *For every id this change accepts — path, body, related field, bulk list — which queryset
resolves it, and is it `visible_to()` of this caller?*

**See also.** AUTH_FAILURE_MODES F3 · DATA_MODEL § 5 · API_PLATFORM §§ 1, 12.

### BC-02 — "None means all" sentinels

**Class.** A scoping helper returns a sentinel — `None`, `"*"`, an empty list, an empty `Q()` — that some caller
reads as "no restriction".

**Shipped as.** An "admin bypass" helper returned `None` to mean unrestricted; a clause builder expanded `None`
to `TRUE`; after a refactor a non-admin path received the `None` and saw every tenant. In another codebase a
helper conflated "no allowlist" with "empty allowlist", turning a fail-closed resource into the whole table.

**Django / Next form.**
- `ids = allowed_ids(user)` then `if ids: qs = qs.filter(id__in=ids)` — an empty list *skips the filter*.
- `reduce(operator.or_, conditions)` guarded by `if conditions else Q()` — `filter(Q())` matches every row.
- `def scope_for(user) -> set[int] | None` where `None` is "superuser" and callers forget to branch.
- Frontend: `permissions ?? ["*"]` or treating an unloaded permission list as "allow".

**Guard.**
- Scope helpers return a `QuerySet` (or a `Scope` object whose unrestricted form exists only via
  `Scope.unrestricted(reason=…)`, which is audited). A type-check plus `test_scope_helpers_never_return_none`.
- `core.scoping.any_of(conditions)` returns `Q(pk__in=[])` on an empty list; a scan bans bare `reduce(or_,` over
  `Q` objects elsewhere.
- `test_a_user_with_zero_grants_gets_none` for every scoping rule.

**Review question.** *What does this helper return for a user with no grants at all — and can any caller read
that as "everything"?*

**See also.** DATA_MODEL § 5 ("`.none()`, never `.all()`") · API_PLATFORM § 14 (`fields=None` refused).

### BC-03 — Read-scoped but write-unscoped

**Class.** Reads go through the scope; writes resolve their target some other way.

**Shipped as.** A custom role holding "update users" could `PATCH` a user it could not *see*, change their email
address, and then trigger a password reset to take the account over. In another codebase, cross-tenant writes
were safe only because "no account with these permissions belongs to an organisation" — a configuration fact
nothing enforced.

**Django / Next form.**
- `get_queryset()` branching on `self.action` and returning `Model.objects.all()` for `update`/`destroy`.
- A service taking an id and loading `Model.objects.get(pk=id)` instead of receiving the scoped object.
- `update_or_create(email=payload_email, defaults=…)` matching a row outside scope.
- Django admin actions, which bypass every DRF gate (`TECH_DEBT` DB-15).

**Guard.** `test_patch_to_an_invisible_row_is_404` and `test_delete_of_an_invisible_row_is_404`, generated for
every writable viewset; write actions resolve through `get_object()` over a `writable_by(user)` queryset
(DATA_LIFECYCLE), asserted by introspection.

**Review question.** *If this caller cannot see the row, can they still change it?*

**See also.** DATA_LIFECYCLE (write-path narrowing) · BUILD_ORDER 9.3's acceptance criterion.

### BC-04 — Layer-1-only RBAC

**Class.** The endpoint checks "may this user use the feature" and then acts on whichever row the URL names.
The full argument is AUTH_FAILURE_MODES **F3**.

**Shipped as.** The most common shape in every studied codebase that had an RBAC layer at all; a scaffolded
object-permission hook that nobody implemented read as though the check existed.

**Django / Next form.** `required_permissions = {"partial_update": ["crm.deals.update"]}` with a `get_queryset()`
returning `Deal.objects.all()`; `has_object_permission()` defined and returning `True`.

**Guard.** `dbx.E003` (every listable model implements `visible_to()`); `VisibleToQuerySet.visible_to()` raising
`NotImplementedError` by default; the BC-01 cross-scope test, which acts as a user **holding** the permission.

**Review question.** *This user may update deals — which line stops them updating* this *deal?*

**See also.** AUTH_BLUEPRINT § 7.6 · RBAC_DESIGN § The two layers.

### BC-05 — The forgotten gate

**Class.** An endpoint ships with no permission attached and serves any authenticated caller — or any caller at
all. The asymmetry that makes it durable is AUTH_FAILURE_MODES **F1**.

**Shipped as.** Everywhere a gate was a call inside the handler. In one frontend, pages reachable only by URL were
ungated because unmatched routes fell back to "any admin".

**Django / Next form.**
- A function view with `@api_view`, or an `APIView` not inheriting `BaseAPIView`.
- `@action(…, permission_classes=[IsAuthenticated])` overriding the viewset's gate for one action.
- `get_permissions()` overridden to return `[AllowAny()]` for `create`.
- `authentication_classes = []` on a view that is not in the public ledger.
- **Next.js Server Actions are reachable by direct `POST` even when nothing imports them**; a route handler
  under `app/**/route.ts` is an endpoint nobody reviewed as one.

**Guard.** `dbx.E001`, `dbx.E004` and the route enforcement test (AUTH_BLUEPRINT § 9); a scan banning
`@api_view`, `AllowAny` outside `core/`, and `permission_classes=` inside `@action(...)` except in a reviewed
allowlist; a frontend lint rule that confines `"use server"` modules and route handlers to one directory whose
functions only call the API with the user's own cookie.

**Review question.** *Which declaration makes this endpoint refuse a user holding no permissions — and what
happens if I delete it?*

**See also.** AUTH_BLUEPRINT §§ 9.1–9.3 · API_PLATFORM § 7 (credential kinds default to session).

### BC-06 — Authority inferred from names

**Class.** Access is decided by what something is *called* — a route name, a role slug, a permission's last
segment — instead of by an explicit declaration. The route-resolution version is AUTH_FAILURE_MODES **F4**/**F5**.

**Shipped as.** A seeder built a "read-only" role by copying every permission whose last segment was a read verb;
a permission named with a noun ending sailed through and handed credential-minting to the read-only role. In
another codebase, 29 call sites compared role names; a new external role failed every comparison and several fell
through to the internal-staff branch — *widening* rather than refusing.

**Django / Next form.** `if user.roles.filter(slug="admin").exists()`; `user.groups.filter(name=…)`; `is_staff`
used as an authorization decision (RBAC_DESIGN: it grants the Django admin and nothing else); a derived role
computed by `code.endswith(".view")`.

**Guard.** A scan banning role-slug and group-name literals outside seeders and migrations; every permission in
the catalog carries explicit metadata (`kind ∈ read · write · admin · credential`, `sensitivity`) and a test fails
if one lacks it; derived roles are computed from that metadata only; role classification (internal, external,
machine) is a column (API_PLATFORM § 9's `Role.audience`).

**Review question.** *If this role or permission were renamed tomorrow, would access change?*

**See also.** RBAC_DESIGN § Naming · EXTENSIBILITY (role registries).

### BC-07 — Hiding mistaken for denying

**Class.** Access control is left to what the UI shows: a hidden nav item, a hidden button, a field the component
never renders — while the route, or the payload, still delivers it.

**Shipped as.** A dashboard sent every internal user a hidden property holding colleagues' names and email
addresses that no component rendered — "invisible on screen, fully readable in devtools". A dashboard section
permission was registered but the section was still computed and shipped for everyone.

**Django / Next form.**
- A serializer returning fields the page does not render ("the frontend just ignores it").
- **Props passed from a Server Component to a Client Component are serialised into the page payload** — whatever
  crosses that boundary is readable by the user.
- A `/me` or bootstrap payload carrying more than the shell needs.
- A frontend route gate with no matching server-side gate (FRONTEND_PLATFORM makes the nav manifest the route
  gate *in addition to*, never instead of, the API).

**Guard.** Section and widget registries: a test that no key outside the caller's granted sections appears in the
response; API_PLATFORM § 13's canary test for sensitive values; FRONTEND_PLATFORM's "every page has a manifest
entry" test; the affordance-parity rule (AUTH_BLUEPRINT § 11, F16).

**Review question.** *If the user opened devtools on this page, what would they see that the screen does not
show?*

**See also.** RBAC_DESIGN § Frontend ("a courtesy, not a control").

### BC-08 — Grant writers without a privilege ceiling

**Class.** Whoever can grant can grant more than they hold. AUTH_FAILURE_MODES **F14** covers elevated roles; this
class is the general ceiling: **you cannot grant a permission you do not hold**, on every path that writes a grant.

**Shipped as.** Anyone able to edit a role's permissions could give their own role anything by enumerating
permission ids. Any administrator could create a super-administrator through an unguarded register path. A staff
account escalated itself through a generic user `PATCH` that accepted a role list.

**Django / Next form.** Grants written from more than one place — create role, update role, clone role, a matrix
cell toggle, set role permissions, an invitation carrying a role, token scopes (API_PLATFORM § 9) — with the
ceiling copied into some of them.

**Guard.** `tests/architecture/test_grant_writers.py`: every named writer in `rbac/services.py` calls the ceiling
check (source inspection) **and** a module scan finds no other code creating `RolePermission`/`UserRole` rows —
so a sixth write path fails the test instead of skipping the rule; a behavioural test per writer; invitations and
token issuance tested against the same ceiling.

**Review question.** *Can the person making this grant end up holding something they did not hold before?*

**See also.** AUTH_BLUEPRINT §§ 8.2–8.4 · RBAC_DESIGN.

### BC-09 — Bypass lists duplicated

**Class.** "Who skips the checks" is answered in more than one place, and the answers drift.

**Shipped as.** One codebase had five separate lists of bypass roles — the backend gate, the frontend's "is super
admin" flag, a helper, a privilege checker, a two-factor enforcement list — and they already disagreed: the
frontend showed controls the backend refused, and a checker exempted a role "because it already holds everything",
which was false. Elsewhere an owner-level bypass was invisible to the role-derived `/me` permission list, so the UI
hid owner actions the API would have allowed.

**Django / Next form.** `if user.is_superuser or user.has_perm(…)` repeated across services; `is_staff` checks;
a frontend `can(code) || isSuperuser()`; `/me` returning role-derived codes instead of the **effective** set.

**Guard.** One function, `core.authz.bypasses(principal)`, read by the RBAC backend, `/me` and the audit writer; a
scan allowing `is_superuser` only in an allowlist of modules; `test_me_returns_effective_permissions` (a
superuser's list is the full catalog, computed by the same function the backend uses); a frontend lint rule
banning `isSuperuser()` inside gating expressions.

**Review question.** *Is this the only place that decides who bypasses this check?*

**See also.** AUTH_BLUEPRINT § 9.5 (the bypass is audited) · FRONTEND_PLATFORM (permission provider).

### BC-10 — N login paths drifting

**Class.** Several paths end in a session — password, MFA verify, invitation accept, password reset, SSO callback,
magic link, impersonation start and stop — and each re-implements the checks that must precede one.

**Shipped as.** Social sign-in paths minted tokens without the second factor, and for inactive accounts, because
each entry point carried its own copy of the completion block. On one path an administrator flag failed closed
because role assignments were not loaded there.

**Django / Next form.** A view calling `tokens.issue_pair()` or `django.contrib.auth.login()` directly; a new
authentication backend whose `authenticate()` returns a user without the `is_active` decision (AUTH_BLUEPRINT
§ 6.2); an SSO callback that sets cookies itself.

**Guard.** `users.services.complete_login(request, user, method)` is the **only** caller of `issue_pair()`
(AST-guarded). A parametrised test over every route registered as session-issuing asserts: inactive → refused;
MFA-enrolled → challenge and no session; session cap applied; exactly one audit row.

**Review question.** *Does this new way in end at the same function as every other way in?*

**See also.** AUTH_BLUEPRINT §§ 6.2, 6.8 · AUTH_FAILURE_MODES F9–F11.

### BC-11 — User enumeration

**Class.** A response, its timing or a side effect tells an unauthenticated caller whether an account exists.
Login is AUTH_FAILURE_MODES **F9**; this class covers every other door.

**Shipped as.** A one-time-code password reset answered "No account found with this email address". Elsewhere a
throttle that only counted real accounts answered the same question by throttling.

**Django / Next form.** Forgot-password, registration ("email already taken"), invitation ("already a member"),
resend-verification; an `IntegrityError` mapped to a field message on an anonymous endpoint (API_PLATFORM § 3);
a hasher skipped for unknown users; an email sent inline for real accounts only, so real accounts answer slower.

**Guard.** Byte-identical-response tests for every public route flagged `accepts_identifier`; the hasher-called
assertion (a mock call count, not a flaky timing test); message sending through `on_commit` or a queue so timing
does not depend on it; recipient throttles counted before the lookup (API_PLATFORM § 6).

**Review question.** *Could someone with a list of addresses learn which ones are customers from this endpoint?*

**See also.** AUTH_BLUEPRINT § 6.2 · API_DESIGN § Authentication.

### BC-12 — Mass assignment

**Class.** A client sets a field it was never meant to set, because the write accepts whatever keys arrive.

**Shipped as.** A hand-crafted request set fields belonging to a form section the operator was never shown,
because the host owned the column. A machine integration created an already-approved record, skipping the
approval path and every guard hanging off the pending state.

**Django / Next form.** `fields = "__all__"` or `exclude = …` on a `ModelSerializer`; `Model.objects.create(
**request.data)`; `for k, v in request.data.items(): setattr(obj, k, v)`; `serializer.save(**request.data)`;
writable nested serializers; a contributed form section whose fields the host does not strip; a Django admin
`ModelAdmin` with no `fields`.

**Guard.** A system check refusing `__all__` and `exclude`; `StrictModelSerializer` refusing unknown and
read-only input and forcing server-owned fields (API_PLATFORM § 12); a scan for `**request.data` and `setattr`
loops over request input; `Meta.field_permissions` stripping.

**Review question.** *Which fields can a client set here — and is that list written down, or inferred?*

**See also.** API_DESIGN § Requests · API_PLATFORM §§ 12–13.

---

## 3. Abuse controls — **Process**

### BC-13 — Rate limits keyed on the wrong thing

**Class.** A limit keys on something the caller chooses (a forwarded header, an unverified token), on something too
fine (the concrete path), or lives in something too small (one process's memory).

**Shipped as.** Taking the leftmost `X-Forwarded-For` let every request pick a fresh identity and defeated every
IP limit. In-memory counters across two replicas × four workers made every limit about 8× looser. Per-URL keying
gave every slug its own bucket. A per-user key decoded a bearer token *without verifying it*, so a forged subject
got a fresh bucket each time.

**Django / Next form.**
- **DRF's `get_ident()` with `NUM_PROXIES` unset returns the entire `X-Forwarded-For` header** — the default is
  the vulnerability.
- `request.META["HTTP_X_FORWARDED_FOR"].split(",")[0]` anywhere.
- `LocMemCache` behind throttles (`dbx.E005`).
- DRF's `SimpleRateThrottle` history is a non-atomic read-modify-write: a parallel burst passes a `5/min` limit.
- A reverse proxy appending to `X-Forwarded-For` instead of overwriting it with the peer address.

**Guard.** API_PLATFORM § 5's tests: 12 requests with rotating leftmost `X-Forwarded-For` still hit `429`; 50
concurrent requests against `5/min` let exactly 5 through; no throttle class keys on `request.path`; `client_ip()`
is the only reader of forwarding headers (scan); `dbx.E005`; OPERATIONS' proxy-config policy test.

**Review question.** *Could one attacker look like a thousand callers to this limit — or a thousand callers look
like one?*

**See also.** AUTH_BLUEPRINT §§ 17.3–17.4 · AUTH_FAILURE_MODES F10.

---

## 4. Secrets and data exposure — **Process**

### BC-14 — Secrets in logs, errors and URLs

**Class.** A credential, token, one-time code or personal identifier leaves the process in a log line, an error
response, an error-tracker event or a URL.

**Shipped as.** A validation handler logged raw request bodies, retaining passwords, one-time codes and national
identifiers in logs and in the error tracker. Server-side error events had no scrubber at all, "so server errors
leaked everything", while the client-side scrubber missed URLs and request bodies.

**Django / Next form.**
- `logger.info("payload %s", request.data)`; logging a `ValidationError` detail that echoes input.
- **Django's error reports include `request.POST` (form and multipart fields — an upload view's password field,
  say) unless the view is decorated with `@sensitive_post_parameters`**, and DRF views are not by default; a
  JSON body logged by our own code is filtered by nothing at all.
- Tokens in query strings (`?token=` in an emailed link) land in proxy access logs and browser history; the page
  must exchange and scrub them at once, and prefer the URL fragment.
- `__repr__`/`__str__` of a model holding a secret; `print()` in a management command.
- `NEXT_PUBLIC_*` values are inlined into the client bundle (SECURITY).

**Guard.** A canary test: send `password=canary-<uuid>` (and a token, and an identifier) through the normal path,
the validation-failure path and a forced 500; assert the canary appears in no captured log record and no
error-tracker event. OBSERVABILITY's single scrubber, tested; a scan banning `request.data`/`request.body` inside
logging calls; Ruff `T20` outside an allowlist of commands; a `repr` test over models with secret fields.

**Review question.** *If this request failed, where would its body end up?*

**See also.** SECURITY § Errors and logging · OBSERVABILITY (the scrubber) · API_PLATFORM § 3.

### BC-15 — Secrets in tracked configuration

**Class.** A credential is committed inside something that does not look like a secrets file: an agent's
permission settings, a submodule URL, a git remote, a seeder, a CI log.

**Shipped as.** A tracked agent-settings file persisted permission allow-rules whose clone URLs embedded a git
access token; a submodule definition embedded another; a token committed in a seeder was revoked automatically by
the hosting platform's secret scanning — "a revoked token never works again".

**Django / Next form.** `.claude/settings.json` allow-rules containing `https://<token>@…`; `.gitmodules` with
userinfo in plugin submodule URLs (DjangoBaseX plugins **are** submodules); `seed_*` commands with real keys;
`echo $SECRET` in CI.

**Guard.** A secret scanner in pre-commit and CI; `test_no_url_with_userinfo_in_tracked_files` (covers
`.gitmodules`, agent config, CI workflows); per-developer agent settings in an ignored `*.local.json`; the
`AGENTS.md` pre-push grep.

**Review question.** *Does any URL or command in this diff carry a credential inside it?*

**See also.** SECURITY § Secrets · `AGENTS.md` rules 5–7.

### BC-16 — Decryption that fails open

**Class.** A decrypt failure returns something that looks like success — the ciphertext itself, an empty string,
or `None` that a caller reads as "no secret needed".

**Shipped as.** A credential accessor returned the raw ciphertext when decryption failed, "so nothing looked
wrong", after a production dump encrypted under another environment's key was imported. Separately, every
environment shared one encryption key, so a restored production dump carried *working* production credentials into
staging with background jobs running.

**Django / Next form.** `try: return f.decrypt(v) except InvalidToken: return v`; a `None` secret compared with
`==` in an MFA check; a Fernet key derived from `SECRET_KEY` (rotating one bricks the other); a model field that
decrypts on attribute access, so every `repr()` and debugger is a disclosure.

**Guard.** `decrypt()` raises `DecryptionError`, tested with a wrong key; a boot check that the encryption key list
is dedicated and distinct from `SECRET_KEY`; a test that an undecryptable MFA secret refuses verification;
explicit decrypt calls only (no auto-decrypting field). JOBS_AND_INTEGRATIONS owns the service; OPERATIONS owns
per-environment keys and restore safety.

**Review question.** *When this value cannot be decrypted, does the caller find out?*

**See also.** JOBS_AND_INTEGRATIONS (encryption service) · CONFIGURATION (restore config safety).

### BC-17 — Per-user data in a shared cache

**Class.** A response or query result belonging to one user or tenant is stored where the next caller is served
it.

**Shipped as.** Frontend query caches keyed without the tenant bled one organisation's rows into another's view
after an organisation switch. Separately, documents cached without a `Cache-Control` header were reused by browsers
after deploys, which made staleness look random.

**Django / Next form.** A DRF view under `@cache_page`; an authenticated response without `Cache-Control:
no-store` (AUTH_BLUEPRINT § 6.4); a CDN in front of the API; **a Next.js server-side cache (`"use cache"`, a
cached `fetch`) keyed without the user** in a module that calls the authenticated API; frontend query keys without
the active tenant.

**Guard.** A middleware test that every authenticated response carries `no-store`; a scan banning `cache_page` on
API views; a lint rule banning server-side cache directives in modules that import the authenticated client;
FRONTEND_PLATFORM's tenant-in-key rule and test.

**Review question.** *If a second user made the same request a second later, could they get this user's answer?*

**See also.** AUTH_BLUEPRINT §§ 6.4, 17.2 · FRONTEND_PLATFORM.

---

## 5. Injection and untrusted input — **Process**

### BC-18 — Server-side template injection

**Class.** Text a user or tenant authored is treated as a *template* rather than as *data* in one.

**Shipped as.** Tenant-editable email templates rendered by a non-sandboxed template engine — remote code
execution, from a settings screen. Autoescaping did not help; escaping is about output, not about what the
template language may evaluate.

**Django / Next form.**
- `Template(user_text).render(Context({"user": user}))` — Django's template language runs no arbitrary code,
  but it **traverses attributes and calls zero-argument methods** not marked `alters_data`, and `{% debug %}` dumps
  the context. Passing a model object exposes whatever hangs off it.
- A non-sandboxed Jinja2 `Environment().from_string(user_text)` — code execution.
- **`user_format.format(obj=obj)`** — Python's format mini-language reaches `{obj.__class__.__init__.__globals__}`.
- `mark_safe()` / `|safe` on user content — stored XSS.

**Guard.** Operator-authored templates render through one service using a placeholder language
(`string.Template.safe_substitute`, or a sandboxed engine) over a **flat allowlisted dict of strings, never model
objects**; syntax validated at save time in the same sandbox; templates carrying security tokens (reset,
invitation, verification) cannot be overridden. A scan: no `Template(`, `from_string(` or `.format(` with a
non-literal template argument outside that service. A test renders `{{ user.password }}`-style and
attribute-traversal payloads and asserts nothing leaks.

**Review question.** *Who wrote the template this renders — and what can it reach?*

**See also.** NOTIFICATIONS_AND_ALERTING (templates) · REUSABLE_MODULES (templated documents).

### BC-19 — Open redirect

**Class.** A redirect target comes from the request, so a trusted domain forwards a victim anywhere.

**Shipped as.** A classic of sign-in flows; the variant that recurs is the one that "validated" by checking the
target starts with `/` — `//evil.example` and `/\evil.example` both start with a slash.

**Django / Next form.** The Next.js sign-in page doing `router.push(searchParams.get("next"))`; `redirect()` in a
Server Component with a query value; `HttpResponseRedirect(request.GET["next"])` without
`url_has_allowed_host_and_scheme()`; emailed links built from `request.get_host()` (a forged `Host` header points a
reset link at the attacker — AUTH_BLUEPRINT uses `FRONTEND_BASE_URL` for exactly this reason); an OAuth
`redirect_uri` matched by prefix.

**Guard.** One `safeNextPath()` helper accepting only same-origin paths (single leading `/`, no `//`, no `\`,
decoded once) with a payload table test; a lint rule banning `router.push`/`redirect` on a search-param value not
passed through it; a backend scan banning `get_host()`/`build_absolute_uri()` in link builders.

**Review question.** *Can the destination of this redirect be written by someone else?*

**See also.** FRONTEND_PLATFORM · AUTH_BLUEPRINT Ch. 18.

### BC-20 — Server-side request forgery

**Class.** The server fetches a URL that someone else chose — and reaches something only the server can reach.

**Shipped as.** Webhook URLs accepted `http://` and any host with no SSRF guard. Where a guard existed, it checked
at save time and connected by hostname later — a DNS-rebinding window. A server-side branding fetch built its URL
from the `Host` header; host matching with a substring test admitted `allowed.example.evil.test`.

**Django / Next form.** `requests.get(user_url)`; following redirects (the standard way around an allowlist); a PDF
renderer fetching `<img src>` from a template; "import image from URL"; a tenant-configurable SMTP host; a Next.js
server component fetching `https://${host}/…` from request headers; addresses in disguise — link-local metadata
addresses, IPv4-mapped IPv6, decimal-encoded IPs, userinfo (`http://allowed@evil`).

**Guard.** Every outbound call goes through JOBS_AND_INTEGRATIONS' safe client (resolve every address, refuse
non-global ranges, pin the vetted IP, no redirects, bounded timeout); a scan banning `requests.`, `httpx.` and
`urllib.request` outside `core/http/`; a hostile-URL table test; the PDF renderer's no-network fetcher tested; a
frontend lint rule banning request headers in server-side fetch URLs.

**Review question.** *Who chose the address this code connects to — and is it checked when the connection is
made, not only when it was saved?*

**See also.** JOBS_AND_INTEGRATIONS (safe HTTP client, webhooks) · DOMAIN_PRIMITIVES (PDF rendering).

### BC-21 — Upload type trusted from the client

**Class.** A file's type, size or name is taken from what the client said.

**Shipped as.** Support attachments and bug-report screenshots accepted with no validation; uploads served
publicly from the application's own origin by a storage mode nobody reviewed as a security setting.

**Django / Next form.** `file.name.endswith(".png")`; trusting `file.content_type`; Django's
`validate_image_file_extension` (it checks the **extension**); believing `FILE_UPLOAD_MAX_MEMORY_SIZE` is a cap (it
is the spool-to-disk threshold); storing under the client's filename; `MEDIA_ROOT` served by the proxy; SVG
accepted as an image.

**Guard.** API_PLATFORM §§ 18–19: `test_html_renamed_png_is_refused`, the pixel-bomb and oversize tests, SVG
refused, every `FileField`/`ImageField` bound to a registered upload policy (architecture test), no public
`/media/` in proxy config (OPERATIONS policy test).

**Review question.** *What decides what this file is — its bytes, or its name?*

**See also.** SECURITY § Input and output · API_PLATFORM §§ 18–19.

### BC-22 — Spreadsheet formulas and pattern escaping

**Class.** User text is embedded in a language that interprets it: a spreadsheet cell, a `LIKE` pattern, a regular
expression, raw SQL.

**Shipped as.** CSV exports carried user text beginning `=`, `+`, `-` or `@` into spreadsheets that evaluated it.
Separately, two drifted copies of a `LIKE`-escaping helper disagreed about the backslash.

**Django / Next form.** Writing user fields to CSV/XLSX without neutralising leading `= + - @ \t \r` (prefix `'`
for **user-text cells only** — never app-formatted numbers, or every negative amount breaks); hand-built
`LIKE %s` with user `%`/`_` (Django's `icontains` escapes them; hand-built SQL does not); `__regex`/`__iregex` with
user input (catastrophic backtracking); `.raw()`, `.extra()` or `RawSQL()` with an f-string.

**Guard.** `core.exports.safe_cell()` used by the export registry (DOMAIN_PRIMITIVES), with a test table; one
`escape_like()` helper; a scan banning `.raw(`, `.extra(` and `RawSQL(` with non-literal SQL, and `__regex` /
`__iregex` with a non-literal right-hand side, outside a reviewed allowlist.

**Review question.** *Is any user text in this change interpreted by something other than a human reader?*

**See also.** DOMAIN_PRIMITIVES (import/export) · SECURITY § Input and output.

### BC-23 — Untrusted text into AI agents

**Class.** Text a user controls reaches a model that has tools, credentials or data the user does not.

**Shipped as.** An anonymous bug report was dispatched to an autonomous coding agent running with its permission
prompts disabled and the worker's full environment — a prompt-injection path to every secret on the box.

**Django / Next form.** A support ticket, email body or uploaded document summarised by an agent with write tools;
`subprocess.run(agent, env={**os.environ})`; a database tool on the application's own connection; tools the user
may not use still described to the model; model output rendered as HTML or executed.

**Guard.** Agents on user text run only from an operator-triggered, permission-gated action behind a default-off
flag; the environment is built from an allowlist (a scan bans `os.environ` spreads in agent modules); tools are
filtered by the *user's* permissions **before** being described; database access through a read-only role over
allowlisted views; output treated as untrusted data (sanitised before render). `test_a_zero_permission_user_gets_no_tools`.

**Review question.** *If the text going into this model said "ignore your instructions", what could the model do?*

**See also.** REUSABLE_MODULES (AI assistant).

---

## 6. Money — **Process**

### BC-24 — Money as float and rounding in display layers

**Class.** Money is represented as a binary float somewhere, or rounded in more than one place.

**Shipped as.** A float in an admin "add funds" request schema reached a wallet debit unquantised. The same price
showed ±1 across five screens, because each rounded for display from a different intermediate.

**Django / Next form.** `FloatField` for an amount; DRF `DecimalField(coerce_to_string=False)` (a JSON float);
`Decimal(0.1)` from a float instead of a string; Python's `round()` (half-even) where invoices round half-up; summing
rounded line totals in one place and rounding the sum in another; money arithmetic in JavaScript numbers.

**Guard.** DOMAIN_PRIMITIVES' money type (amount + currency, one quantisation point, one rounding rule per currency);
a scan banning float types on fields named `amount · price · cost · total · balance · rate` in models, serializers
and schemas — with a self-test proving it catches a revert; frontend money as strings through one library.

**Review question.** *Where exactly is this amount rounded — and is that the only place?*

**See also.** DOMAIN_PRIMITIVES (money).

### BC-25 — Recomputation from the start

**Class.** A value accrued forward (usage, interest, time) is recomputed from its start instead of continued from
its last committed point.

**Shipped as.** Meter closers recomputed `rate × lifetime`, repricing history retroactively and double-billing
hours already charged; a later feature rewrite silently deleted the forward-only helper and reintroduced the
lifetime formula.

**Django / Next form.** `rate * (end_time - start_time)` at close; re-pricing on a rate change by recalculating
from `start_time`; `Sum` over the whole history compared with a ledger that was written incrementally.

**Guard.** One forward-only closer (from `last_accrued_at`); a scan banning the recompute pattern outside it; a
test that closing after partial accrual adds only the remainder — and proves red when the helper is bypassed.

**Review question.** *If this ran twice, or after a partial run, would it charge the same hour twice?*

**See also.** REUSABLE_MODULES (billing).

### BC-26 — Metered is not billed

**Class.** Something is measured but one of the pieces that turns a measurement into a charge is missing, so it is
free forever and nothing errors.

**Shipped as.** A resource type had meters and no collector, so it was never billed; nothing alerted, because
nothing failed.

**Django / Next form.** A billable type needs a rate resolver, a collector, a document line builder, an
unbilled-total aggregator and a tax classification; adding the model and the meter feels finished.

**Guard.** A billable-type registry whose entries must declare every hook; a test iterates the registry and fails
on any missing hook — so "done" means complete by construction.

**Review question.** *Show me the line on an invoice this change produces.*

**See also.** REUSABLE_MODULES (billing).

### BC-27 — Payment success from a client-reachable endpoint

**Class.** Something a client can call marks money as received.

**Shipped as.** An unknown `payment_method` fell through to an unconditional full-settlement branch — a
client-reachable "mark anything paid". A partial-wallet payment with an empty wallet settled an invoice for zero
cash.

**Django / Next form.** `POST /invoices/<id>/pay/ {"method": "card"}`; trusting a gateway redirect's
`?status=success`; a webhook processed before its signature is verified, or verified but not matched to the
account that owns the order; an `else:` settling by default.

**Guard.** One `settle(document, method, reference)` entrypoint with a server-side method allowlist; the customer
endpoint accepts internal-balance methods only; gateway success arrives only through verified callbacks; amount and
currency checked before credit. Tests: unknown method raises; a client call cannot settle with a gateway method;
an unsigned webhook changes nothing.

**Review question.** *Could a customer's own browser cause this record to say "paid"?*

**See also.** REUSABLE_MODULES (billing, payments) · JOBS_AND_INTEGRATIONS (inbound webhooks).

### BC-28 — Currency mismatch converted 1:1

**Class.** Amounts in two currencies are combined as if they were one.

**Shipped as.** A capture in one currency settled an invoice in another at face value — a charge roughly 80× wrong
in one direction.

**Django / Next form.** Settling without comparing currencies; `Sum("amount")` over rows with mixed currencies;
adding two `Decimal`s that came from different currency columns; a default currency filled in for a missing one.

**Guard.** The money type refuses cross-currency arithmetic (raises); settlement asserts currency equality;
aggregate helpers group by currency; without a real exchange-rate service, a mismatch is a hard reject — never a
conversion at 1.

**Review question.** *Can the two amounts in this operation be in different currencies?*

**See also.** DOMAIN_PRIMITIVES (money) · CONFIGURATION (currency settings).

### BC-29 — Money moved outside the single writer

**Class.** A balance or ledger is written from more than one code path.

**Shipped as.** Twelve paths mutated a wallet balance and built ledger rows by hand; credit buckets drifted from
the balance, and a promotion expiry clawed back real money. The same defect had been catalogued four times before
it was fixed.

**Django / Next form.** `wallet.balance -= x; wallet.save()` in a view or task; `LedgerEntry.objects.create(…)`
outside the ledger service; `F("balance") - x` updates scattered across services.

**Guard.** One service entrypoint; a source scan over **tokenised** source (so the rule's own prose does not trip
it) banning balance assignment and ledger construction outside it, with a **line-level** allowlist (a file-level
exemption once excused the highest-volume path); a nightly reconciler comparing the balance with its projection.

**Review question.** *Does this change move money through the ledger service, or around it?*

**See also.** DOMAIN_PRIMITIVES · REUSABLE_MODULES (ledger).

---

## 7. Concurrency and transactions — **Process**

### BC-30 — Check-then-act without a lock

**Class.** Code reads, decides, then writes — and two requests read the same state between.

**Shipped as.** Invoice numbering by `max() + 1` collided under concurrency; on a fresh install `SELECT … FOR
UPDATE` on an empty result locked nothing and two runs minted the same number. An idempotency implementation looked
the key up before locking, and the losing retry hit the unique constraint as a `500`. Two overlapping wallet
payments both debited, and inconsistent lock order elsewhere deadlocked.

**Django / Next form.** `if not Model.objects.filter(…).exists(): Model.objects.create(…)`; quota
check-then-create; `obj.balance = obj.balance - x; obj.save()` instead of an `F()` update;
`select_for_update()` expected to lock a row that does not exist yet; locks taken in different orders in different
services.

**Guard.** The database constraint is the authority (`UniqueConstraint`, `CheckConstraint`, partial uniques);
claim-by-insert for idempotency (API_PLATFORM § 11); advisory or sequence-row locks for numbering
(DOMAIN_PRIMITIVES); one documented lock order. **Concurrency tests run on PostgreSQL** — SQLite serialises writes
and makes these tests pass vacuously (ADR-0005, `TECH_DEBT` DB-12).

**Review question.** *What happens if two of these run at the same instant?*

**See also.** DOMAIN_PRIMITIVES (sequences) · DATABASE_MIGRATIONS.

### BC-31 — Side effects before commit

**Class.** An email, a task, a webhook or an external call is triggered inside a transaction that may still roll
back — or before the row it refers to is visible.

**Shipped as.** Workers picked up tasks for rows not yet committed and failed with "does not exist"; elsewhere a
side-effect task had to be moved strictly after the commit, and only when the state actually transitioned, after
it fired for no-op saves.

**Django / Next form.** `task.delay(obj.pk)` or `send_mail(…)` inside `transaction.atomic()`; a signal handler
enqueuing on every `post_save`, whether or not anything changed; notifying before the audit row exists.

**Guard.** `transaction.on_commit(lambda: …)` for every side effect, or the outbox (JOBS_AND_INTEGRATIONS); a scan
flagging `.delay(`, `.apply_async(` and `send_mail(` lexically inside `atomic()` blocks (ratchet); tests use
`captureOnCommitCallbacks` and assert a rolled-back request enqueued nothing.

**Review question.** *If the transaction around this rolled back, would the outside world already know?*

**See also.** JOBS_AND_INTEGRATIONS (outbox) · AUTH_BLUEPRINT Ch. 18.

### BC-32 — Unconditional actor stamping

**Class.** "Who did this" is overwritten with whoever — or nobody — is resolvable at save time.

**Shipped as.** A documented base-model sample set `updated_by = current user` unconditionally, which would have
written `NULL` over real attribution on every save from a job, seeder or scheduler. Elsewhere a thread-local request
binding, left over from a previous request, risked attributing a job's write to an unrelated user.

**Django / Next form.** `save()` overrides reading a thread-local user; middleware setting `threading.local` and
never clearing it; the same under ASGI, where thread-locals do not follow the request; system writes recorded as
"whoever is logged in" instead of `actor=None, source="job:<name>"`.

**Guard.** DATA_LIFECYCLE's base model: the actor comes from a `contextvars` value set by middleware, command and
task wrappers, reset in `finally`; `updated_by` is written only when an actor is known; tests: a job saving a row
preserves its `updated_by`; the contextvar is empty after the request.

**Review question.** *When this row is saved by a background job, what will it say about who changed it?*

**See also.** DATA_LIFECYCLE (audit engine, actor columns).

---

## 8. Background work and caches — **Process**

### BC-33 — A queue with no worker

**Class.** Work is routed somewhere nothing consumes, and the system looks healthy because nothing failed.

**Shipped as.** A set of tasks was re-routed to a new queue that no worker consumed; billing, reconcilers and
cleanups would have silently stopped. In another system thousands of jobs sat unprocessed for months while the
failed-jobs table stayed empty — "those jobs never failed, they were never picked up".

**Django / Next form.** `CELERY_TASK_ROUTES` naming a queue no worker's `-Q` includes; a task with a custom
`name=` bypassing a wildcard route; a beat entry naming a renamed or unimported task; Celery's built-in `celery`
queue with no consumer; `task_create_missing_queues` left on, so a typo creates a new, unconsumed queue; a hard
time limit without a soft one.

**Guard.** JOBS_AND_INTEGRATIONS' tests: every routed queue has a worker in the process definitions; every beat
entry names a registered task; `task_create_missing_queues=False`; the job-run monitor reports `never_run` and
"worker seen recently" (OBSERVABILITY).

**Review question.** *Which process picks this up — and what shows red if it never does?*

**See also.** JOBS_AND_INTEGRATIONS (job registry, queue invariants).

### BC-34 — A cached failure

**Class.** A miss, an empty result or an error from a lookup is cached as though it were an answer.

**Shipped as.** An integration's "contact not found" was cached for five minutes; the user created the contact a
minute later and the application kept saying it did not exist — "the app is not even making the call, so there is
no request to inspect".

**Django / Next form.** `cache.get_or_set(key, fetch)` where `fetch` returns `None` or `[]` on a miss, a timeout or a
`401`; memoising a settings read that failed while the database was unavailable at boot.

**Guard.** A `cache_hit_only(key, ttl, fn)` helper that stores only positive results; a scan banning `get_or_set`
in integration modules; a test: a miss followed by a hit returns the hit.

**Review question.** *If the first call to this failed, how long would the failure be remembered?*

**See also.** JOBS_AND_INTEGRATIONS · DOMAIN_PRIMITIVES (generation-counter caching).

### BC-35 — Per-process state across workers

**Class.** State that must be shared lives in one process's memory, so a change takes effect in one worker out of N.

**Shipped as.** Throttles, a permission-version counter and session liveness on a per-process cache would each have
become per-worker (AUTH_BLUEPRINT § 17.4); an unbounded module-level client cache held mutable per-tenant scope.

**Django / Next form.** `LocMemCache`; a module-level `_cache = {}`; `functools.lru_cache` on a function that reads a
setting, a flag or a permission; an in-memory lock for "single-flight" work; a scheduler started inside the web
process, which then runs once per worker.

**Guard.** `dbx.E005`; a scan banning `lru_cache`/`cache` decorators on functions that query the database and
module-level mutable caches outside a reviewed registry; single-flight locks on the shared store with a TTL
(JOBS_AND_INTEGRATIONS).

**Review question.** *With four workers, how many copies of this value exist — and who invalidates the other three?*

**See also.** AUTH_BLUEPRINT § 17.4 · `TECH_DEBT` DB-17.

---

## 9. Defaults, configuration and new guards — **Process**

### BC-36 — Fail-open defaults

**Class.** When the system does not know — an unknown flag, a missing setting row, a missing scope, an unavailable
dependency — it answers yes.

**Shipped as.** Webhook verification accepted unsigned deliveries whenever the signing secret was unset. A carve-out
flag's model default computed `True` for any constructor that omitted a field — a permanent governance bypass. A
credential with no liveness probe would have read "verified".

**Django / Next form.** `flags.get(key, True)`; a settings resolver returning the permissive branch when its row is
missing or the database is unreachable; `except Exception: return True` in a gate; a `BooleanField` named
`*_bypass`, `*_exempt` or `skip_*` with `default=True`; a registry lookup whose unknown key means "allowed".

**Guard.** Every registry documents its unknown-key default and a test pins it (EXTENSIBILITY); resolvers return
frozen, safe defaults and never raise (CONFIGURATION); a scan flagging exemption-shaped boolean fields with
`default=True`; a test per verifier that an unset secret refuses.

**Review question.** *When this lookup finds nothing, does the caller get the safe answer?*

**See also.** VISION principle 3 · CONFIGURATION · EXTENSIBILITY.

### BC-37 — Environment checks that a typo defeats

**Class.** A security decision compares an environment name as a literal, so a capital letter, an alias or a new
environment slips past it.

**Shipped as.** Operators deployed with `Production` (capital P) and with `staging`; both bypassed every check
written as `== "production"`. Even after a single predicate was introduced, two checks still keyed on the literal
and disagreed with it.

**Django / Next form.** `if settings.ENVIRONMENT == "production"`; `DEBUG = os.environ.get("DEBUG", False)` — **the
string `"False"` is truthy**; `env("DEBUG")` without a boolean cast; development-only features enabled by
`!= "production"`, which also turns them on in staging and in any misspelled environment.

**Guard.** One module, `core/env.py`, with `is_production_like()` (unknown ⇒ production) for security gates and
`is_development()` (exact allowlist) for conveniences; a scan banning comparisons against environment-name literals
elsewhere; Ruff's banned-API rule for `os.environ`/`os.getenv` outside settings; the import-time boot audit
(CONFIGURATION, `TECH_DEBT` DB-19).

**Review question.** *What does this check do on an environment called `Prod`?*

**See also.** CONFIGURATION (`APP_ENV`, boot refusal) · `TECH_DEBT` DB-7.

### BC-38 — A fail-closed gate armed without a census

**Class.** A new guard assumes data that only new rows have, and blocks every existing row the day it ships.

**Shipped as.** New fail-closed entitlement gates assumed limits that only newly onboarded accounts carried; every
older account was blocked from creating resources, with a message reading "None limit", for three days before
anyone connected the cause. One gate masked a second, hiding the blast radius.

**Django / Next form.** A new required relation or setting read with no data migration and no fallback; a gate that
treats "missing data" and "limit reached" as the same refusal; a guard that fuses "manage an existing thing" with
"create a new one".

**Guard.** New guards ship in `log_only` mode first (CONFIGURATION guard modes) with a metric per decision
(OBSERVABILITY); the enabling PR includes a census query — how many existing rows fail the predicate — and its
result; refusals distinguish missing data from a real limit.

**Review question.** *How many existing rows would this refuse on the day it turns on?*

**See also.** CONFIGURATION (guard modes) · OBSERVABILITY (gate metrics).

---

## 10. Migrations and data — **Process**

### BC-39 — Migrations that rewrite operator-authored content

**Class.** A data migration transforms rows that operators wrote, not rows the product shipped.

**Shipped as.** A regex migration fixing duplicated signature blocks matched every row on the one development
database and would have silently mangled production templates; its `RunPython.noop` reverse admitted it could not
be undone. It was stopped before it shipped.

**Django / Next form.** `RunPython` rewriting templates, saved filters, notification bodies or documents; any
`apps.get_model(...)` of an operator-editable model followed by `.save()` in a loop.

**Guard.** Migrations touch only system rows (`is_system=True`); operator-authored content gets a new default or an
in-app "upgrade this" action. A scan of migrations: a `RunPython` touching a model registered as authored requires
an `# authored-content-ok: <reason>` marker and a second reviewer.

**Review question.** *Did a person write the rows this migration changes?*

**See also.** DATABASE_MIGRATIONS · DATA_LIFECYCLE.

### BC-40 — Destructive migrations without expand/contract

**Class.** A schema change the currently running code cannot survive is applied while that code is still running.

**Shipped as.** New containers started against the old schema gave about a minute of `500`s on every
column-adding release, twice in one day. A migration no database had ever executed was merged and deployed.

**Django / Next form.** `RemoveField`, `RenameField`, `RenameModel` or `AlterField(null=False)` in the same release
as the code that stops using the old shape; `AddIndex` instead of `AddIndexConcurrently` (with `atomic = False`) on
a large table; a migration importing application models instead of `apps.get_model()`; squashing or renaming core
migrations once products depend on them by name.

**Guard.** A migration linter in CI flagging destructive operations without a `# contract-ok:` marker placed in a
*later* release than the expand step (OPERATIONS); `migrate` from an empty PostgreSQL database in CI; a test that
no migration imports application code; deploys migrate from the new image **before** the swap.

**Review question.** *Can the code running right now keep working after this migration, and before the new code
arrives?*

**See also.** DATABASE_MIGRATIONS · OPERATIONS (expand/contract, deploy order).

### BC-41 — Migrations faked past their data

**Class.** A database is marked as migrated without the migrations running, so data migrations — reference rows,
defaults, seeds — never happen.

**Shipped as.** A production table created outside the migration system was later reconciled by marking migrations
applied; its seed migration never ran, the allowed-values table stayed empty, and every signup was refused for five
days, invisible on every dashboard.

**Django / Next form.** `migrate --fake` or `--fake-initial` to "get past" a conflict; schema created by hand;
restoring a dump from a different migration state.

**Guard.** Data-plane self-checks for required rows at boot, in the readiness detail and as a metric
(OBSERVABILITY); a policy test that no deploy script contains `--fake`; a runbook step for reconciling a drifted
database that runs the data migrations explicitly.

**Review question.** *If this environment's migration table lied, what would tell us?*

**See also.** OBSERVABILITY (data-plane checks) · OPERATIONS.

---

## 11. Contracts and errors — **Process**

### BC-42 — Failure rendered as empty or zero

**Class.** "We could not find out" is displayed as "there is nothing".

**Shipped as.** 145 of 201 pages in one frontend hand-rolled their fetching, and a failed request fell through to
the empty state: "No invoices yet". An integration registry under-reported traffic 400:1 because an unmonitored
door read as zero; the busiest integration showed "never called" because recency was computed over a window.

**Django / Next form.** `data ?? []` on error; an API answering `200 []` when an upstream call failed; a dashboard
tile counting a table nothing writes to; "0 failed jobs" with no monitor behind it.

**Guard.** FRONTEND_PLATFORM's load-state contract (error disjoint from empty) with its ratchet test; the API
never returns an empty success for an upstream failure (`502`/`503`, API_PLATFORM § 3); OBSERVABILITY's "zero is
not a fact" state model (`live · quiet · never · off · untracked`).

**Review question.** *If the source of this number were down, what would the screen show?*

**See also.** FRONTEND_PLATFORM · OBSERVABILITY.

### BC-43 — Client and API drifting apart

**Class.** The frontend's idea of the API and the API disagree, and both typecheck.

**Shipped as.** An audit found a hand-written client calling endpoints that did not exist and sending parameter
names the backend ignored. Five backend call sites and the frontend held separate copies of one billing constant
that disagreed.

**Django / Next form.** Hand-written response types in `src/lib/` (`TECH_DEBT` DB-4); permission codes typed as
string literals in `can("…")`; enums duplicated in TypeScript; unknown filters silently ignored by the API.

**Guard.** API_PLATFORM § 17's three drift checks and the exported-constants test; unknown query parameters
answered `400` (API_PLATFORM § 2); a lint rule requiring generated permission constants.

**Review question.** *If the backend renamed this field tomorrow, which check would go red?*

**See also.** API_PLATFORM §§ 2, 17.

### BC-44 — Upstream errors mis-mapped

**Class.** An error from a third party is passed through as though it were the caller's own — or flattened so its
cause disappears.

**Shipped as.** A provider's `401` passed through made the frontend log the user out. Blanket `502` mapping hid the
real cause across many resource types.

**Django / Next form.** `return Response(status=upstream.status_code)`; `except Exception: raise APIException()`;
nine hand-written "if 401 or 403" helpers each with its own test.

**Guard.** One provider error hierarchy and one mapping (upstream `401`/`403` → `502`; `429` → `503` with
`Retry-After`; other `4xx` passed through with detail), owned by JOBS_AND_INTEGRATIONS; a table test over the
mapper; a scan banning upstream status codes copied into responses.

**Review question.** *If the provider rejected our credentials, what would the user be told?*

**See also.** JOBS_AND_INTEGRATIONS (provider error mapping) · API_PLATFORM § 3.

---

## 12. Tests — **Process**

### BC-45 — Tests that cannot fail

**Class.** A test, check or guard that passes whatever the code does.

**Shipped as.** A middleware probe saw every request as unauthenticated and reported "0 regressions over 1,007
routes" for both the old rule and the new one. A completeness test scanned a directory that a refactor had removed
and skipped on every run. A drift guard built on `git diff` passed unconditionally because the generated file was
never committed. A hallucinated client method passed its tests because an unspecced mock accepts any attribute. A
deployment assertion of the form `grep -ql … | wc -l` could only ever read zero.

**Django / Next form.** An authorization test acting as a superuser; a refusal-only test that passes against a rule
refusing everything; `Mock()`/`MagicMock()` without `spec`/`autospec`; a parity test that skips when the other tree
is absent; a test that reads ambient seeded rows and skips when they are missing; concurrency tests on SQLite;
tests run with `DEBUG=True`, seeing error pages production never serves.

**Guard.** ENGINEERING_PRACTICES: every guard proved red once and the PR says how; completeness tests `assert
universe` — they fail, never skip, on an empty enumeration; CI treats a skip in a parity or architecture test as a
failure; a lint rule banning unspecced mocks of typed dependencies; a positive control in every refusal test; an
`other_scope_actor` fixture for authorization.

**Review question.** *What change to the code under test would make this test fail — and did you try it?*

**See also.** ENGINEERING_PRACTICES · AUTH_FAILURE_MODES § 4 (rules for the tooling itself).

---

## 13. How a post-mortem feeds the register — **Process**

**What.** Every incident, and every bug fix in a trigger area, ends by citing an existing class or adding a new
one. The register is only worth reading while it is fed.

**Why.** A checklist of *your own* shipped bugs beats any generic list — but only if the next bug lands in it. The
failure this prevents is the incident fixed at the call site and forgotten, then reintroduced by a rewrite that
never heard of it.

**Rules.**

1. **Classify first.** Before the fix merges, the post-mortem names the class: `BC-nn`, or "new".
2. **Cite, don't copy.** An instance of an existing class adds a line to the class's *Shipped as* only if it teaches
   something new (a new form, a new stack-specific shape); otherwise it cites the ID.
3. **A new class needs all six parts** (§ 1) and a general name — "tenant scoping on bulk endpoints", not "the
   invoices export bug". It takes the next free number; numbers are never reused.
4. **Answer "why did the guard not catch it?"** Either the class had no guard (build one, or add a `TECH_DEBT` row),
   the guard had a blind spot (widen it), or the guard did not run (fix CI — BC-45).
5. **The guard lands with the fix and is proved red** against the pre-fix code. The regression test is named after
   the class — `tests/regressions/test_bc01_bulk_archive_unscoped.py` — and its docstring names the incident
   generically.
6. **Update the review question** if the incident shows the old one would not have caught it.
7. **Retire, never delete.** A class made impossible by construction (for example, a type that cannot represent the
   bug) is marked *Retired YYYY-MM-DD — reason*, and keeps its number and its text.
8. **Record it** in [`../DAILY_CHANGES.md`](../DAILY_CHANGES.md) with the class ID, what was verified and how.

**Post-mortem template (the minimum).**

```markdown
## <date> — <one-line summary>
- **Impact:** who saw what, for how long
- **Class:** BC-nn (or NEW → proposed name)
- **Root cause:** the mechanism, not the person
- **Why no guard caught it:** none existed · blind spot · did not run
- **Guard added:** <test/check name> — proved red against <commit>
- **Review question changed?** yes/no
```

**Enforced by.** The PR template below; a docs test that every `BC-nn` cited anywhere in the repository exists in
this file, and that IDs are unique and contiguous (retired ones included).

---

## 14. PR template checkbox block — **Process**

For `.github/PULL_REQUEST_TEMPLATE.md` (BUILD_ORDER 9.6). Tick what the change touches; answer the review
question for each ticked area in the PR description. "Not applicable" is a valid, honest answer — an unticked box
with no reason is not.

```markdown
### Bug-class review (documentation/system-design/BUG_CLASSES.md)
- [ ] This change touches none of the trigger areas below
- [ ] **Endpoints / querysets** — ids resolve through `visible_to()`; writes too; no sentinel means "all" (BC-01–BC-04)
- [ ] **Gates** — every action declares `required_permissions` or is in the public ledger (BC-05)
- [ ] **Roles / grants / tokens / `/me`** — ceiling enforced; no name-inferred authority; one bypass function (BC-06, BC-08, BC-09)
- [ ] **Payloads** — nothing sent that the screen does not show; no `__all__`; server-owned fields forced (BC-07, BC-12)
- [ ] **Sign-in paths** — ends in `complete_login()`; no enumeration (BC-10, BC-11)
- [ ] **Throttles** — keyed on verified identity or `client_ip()`; scope per view (BC-13)
- [ ] **Secrets** — none in logs, errors, URLs, tracked config; decryption fails closed (BC-14–BC-16)
- [ ] **Caching** — no per-user data in a shared cache; no cached failures; no per-process state (BC-17, BC-34, BC-35)
- [ ] **Untrusted text** — not a template, redirect target, fetched URL, formula, pattern or prompt (BC-18–BC-23)
- [ ] **Money** — Decimal + currency, one rounding point, single writer, forward-only, gateway-only success (BC-24–BC-29)
- [ ] **Concurrency / side effects** — constraint or lock backs every check; side effects `on_commit` (BC-30, BC-31)
- [ ] **Jobs** — every queue has a worker; actors not stamped unconditionally (BC-32, BC-33)
- [ ] **Defaults / environment / new guards** — unknown is safe; one env predicate; census + `log_only` first (BC-36–BC-38)
- [ ] **Migrations** — system rows only; expand/contract; nothing faked (BC-39–BC-41)
- [ ] **Display / contracts / upstream errors** — error ≠ empty; generated types current; provider errors mapped (BC-42–BC-44)
- [ ] **Tests** — each new guard was seen failing; nothing skips in CI (BC-45)
- Classes cited by this change: BC-__ · New class proposed: none / <name>
```

---

## 15. ⚠️ Conflicts with existing docs

Recorded, not edited. Each is an instance of a class above written into a standards document, which is the most
expensive place for one to live — agents and new developers copy standards examples verbatim.

| # | Existing doc says | Class it reproduces | Fix |
|---|---|---|---|
| 1 | [`DJANGO_STANDARDS.md`](DJANGO_STANDARDS.md) § 3 — *"A view should read like this"*: `EnquiryViewSet(viewsets.ModelViewSet)` with `permission_classes = [IsAuthenticated]` and `Enquiry.objects.for_user(…)` | BC-04, BC-05 — a gate-less, Layer-1-less view presented as the model to copy; contradicts AUTH_BLUEPRINT § 9.1 (`BaseViewSet`, `required_permissions`, `visible_to()`) | Replace the example with a `BaseViewSet` declaring `required_permissions` per action, `list_spec`, and `get_queryset()` returning `visible_to(self.request.user)` |
| 2 | [`DJANGO_STANDARDS.md`](DJANGO_STANDARDS.md) § 6 — *"Opening a view to the public is an explicit, per-view `permission_classes = [AllowAny]`"* | BC-05 — the scattered `AllowAny` that `dbx.E001` and the public ledger exist to prevent | Replace with "`public = True` plus a `PUBLIC_ROUTES` entry carrying a reason" (AUTH_BLUEPRINT § 9.2) |
| 3 | [`API_DESIGN.md`](API_DESIGN.md) § Checklist — *"`permission_classes` set — entity-level (Layer 1)"* | BC-05 — points at the mechanism the design replaced | "`required_permissions` declared for every action, or `public = True` with a ledger entry" |
| 4 | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 11 — `can()` alongside an `isSuperuser()` helper, and `/me` returning `permissions` without saying they are the effective set | BC-09 — a client that gates on `can(x) \|\| isSuperuser()` is a second bypass list | `/me.permissions` is the **effective** set computed by the backend's own function (a superuser's is the full catalog); `isSuperuser()` is for display only, and a lint rule keeps it out of gating expressions |
| 5 | [`RBAC_DESIGN.md`](RBAC_DESIGN.md) § Frontend — *"The API returns the current user's permission codes on `/me`"* | BC-09 (same) | Say "effective permission codes, bypasses expanded server-side" |

---

## Pending decisions (for the repository owner)

1. **Where post-mortems live.** Recommended: `documentation/incidents/YYYY-MM-DD-<slug>.md`, one per incident,
   indexed in `INDEX.md`; the alternative is a section of `DAILY_CHANGES.md`, which is harder to cite.
2. **Whether the PR checklist blocks merge.** Recommended: a CI check that the bug-class section is present and
   either "none of the trigger areas" or at least one box is ticked — it cannot check the answers, only that the
   question was faced.
3. **Regression-test location.** Recommended: `backend/tests/regressions/` and `frontend/tests/regressions/`, named
   by class ID, alongside (not instead of) the architecture tests.

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section. Framework behaviours cited in "Django / Next form" (DRF's
> `get_ident()` default, error reports including `POST` data, `validate_image_file_extension`,
> `FILE_UPLOAD_MAX_MEMORY_SIZE`, Server Actions reachable by direct `POST`) were checked against the installed
> Django 5.2, DRF 3.18.1 and the bundled Next.js 16 documentation on that date.
