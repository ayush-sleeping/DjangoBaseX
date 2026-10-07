# Extensibility — registries, plugins and seams

**How anything outside the core — the product's `project/` apps and every plugin — adds behaviour to
the platform without the platform ever learning its name: the app taxonomy, the registry primitive
and its complete catalogue, plugin discovery and lifecycle, the SDK plugins import, and the tests
that make every one of those boundaries go red when it is crossed.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

## Scope — read first

**This file deepens, and does not replace,**
[`../planning/CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md) (the three
ownership layers, the four collision prefixes, submodules, the sandbox-branch workflow) and
[`../planning/PLUGIN_DEVELOPMENT.md`](../planning/PLUGIN_DEVELOPMENT.md) (the plugin author's
checklist). Read those first; this file assumes them and adds the mechanisms they name but do not
specify.

**Owns:**
- The **app taxonomy** (platform · kernel · plugin), the `layer` declaration and the sanctioned-FK rule
- The rule **"every core literal that names models, paths, events or abilities is a registry"**
- The **registry primitive**: one uniform contribution shape, the registration rules, the sealing
  rule, per-registry unknown-key defaults, two-stage registration
- The **complete registry catalogue** — every seam, its shape, its unknown-key default and the sibling
  doc that owns what the registry *feeds*
- **Plugin discovery, loading and lifecycle**: `plugin.toml`, absent-vs-broken imports, defensive
  loading, runtime auto-disable, skew-aware liveness, the **soft-disable contract**
- The **versioned SDK facade** (backend `core.sdk`, frontend `@/core/sdk`) — the only import surface
  for plugins
- **Service contracts**, the **in-process event bus**, **capability switches**
- **UI slots** and the generated **component registry** on the Next side (the contract, not the
  rendering)
- **Shared base tables + 1:1 extension tables** instead of generic foreign keys
- **Boundary and architecture tests** beyond import scans; app-local change discipline; the
  scaffolding generator

**Does not own** (link, do not re-specify):

| Topic | Owner |
|---|---|
| Settings registry, feature flags, guard modes, lookups/vocabularies, project identity values, restore-config safety | [`CONFIGURATION.md`](CONFIGURATION.md) |
| Error envelope and code catalogue, abilities/tokens/scopes semantics, generic read API, throttling, OpenAPI | [`API_PLATFORM.md`](API_PLATFORM.md) |
| Jobs, schedules, run monitor, **the outbox**, webhooks, integration registry, credential and usage probes | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| Notification purposes, the event × channel matrix, preferences | [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md) |
| Health endpoints, data-plane checks, metrics, doctors, System Health page | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
| Activity/audit engine, retention, recycle bin, provenance, row scoping | [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) |
| Import/export, bulk actions, document sequences | [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) |
| Search, knowledge base, AI assistant, alert rules, automation engine | [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) |
| Nav rendering and route gate, `<Slot>` rendering, shell/bootstrap payload, CSP, design tokens | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) |
| Release images, rolling deploy, restore procedure | [`OPERATIONS.md`](OPERATIONS.md) |
| The RBAC model itself — permissions, roles, the two layers | [`RBAC_DESIGN.md`](RBAC_DESIGN.md), [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) |

**The division of labour with the siblings:** each sibling doc specifies *what a registry's entries
do*. This file specifies *that the registry exists, what one entry looks like, what an unknown key
means, and how a plugin gets an entry in without editing the core.*

---

## 0. The rules in one screen

1. **Every app declares a `layer`** — `platform`, `kernel` or `plugin` — as a literal on its
   `AppConfig`; every boundary test reads the declaration, never a hand-kept list. → [§ 1](#1-the-three-tier-app-taxonomy--tier-1--core)
2. **A plugin may FK a platform table and its own tables — nothing else.** Never another plugin's,
   and a kernel table only through the 1:1 extension pattern. → [§ 1](#1-the-three-tier-app-taxonomy--tier-1--core), [§ 21](#21-shared-base-tables--11-extension-tables--tier-2--core)
3. **Any collection literal in the core that names models, URLs, events, abilities, roles or tools
   is a registry**, not a literal. An AST test enforces it. → [§ 2](#2-every-core-literal-that-names-something-is-a-registry--tier-1--core)
4. **One contribution shape everywhere:** `key` · `owner` · `permission` · `flag` · `order` ·
   `component` · `props`. The permission has **no default** — omission is a `TypeError`. → [§ 3](#3-the-registry-primitive-and-the-uniform-contribution-shape--tier-1--core)
5. **Register only inside `AppConfig.ready()`, through the app's bound registrar.** No unregister.
   Duplicates raise. Reads return immutable copies. → [§ 4](#4-registration-rules--tier-1--core)
6. **`ready()` touches no database.** Anything DB-dependent is a callable evaluated at use. A test
   boots with the database unreachable. → [§ 4](#4-registration-rules--tier-1--core)
7. **Every registry documents what an unknown key means, and the answer is the safe direction** —
   pinned by a test that can fail. → [§ 5](#5-unknown-keys-fail-in-a-chosen-safe-direction--tier-1--core)
8. **Vocabulary modules import nothing that reads the registry.** Stage 1 declares, stage 2 wires;
   nothing imports back into the materialiser. → [§ 6](#6-two-stage-registration--vocabulary-then-wiring--tier-1--core)
9. **Plugins are discovered from `plugin.toml` without importing them**, in a deterministic order, and
   every `url_prefix` is unique and non-overlapping. → [§ 12](#12-plugin-discovery--tier-1--core)
10. **"Absent" and "broken" are different.** A `ModuleNotFoundError` is swallowed only when
    `exc.name` is the optional module itself. A bare `except ImportError` around a load is a bug. → [§ 13](#13-absent-vs-broken--tier-1--core)
11. **One switch per plugin gates every surface** — routes, registries, tasks, subscribers, KB,
    search, exports. Disabling never unloads and never touches data. → [§ 15](#15-the-soft-disable-contract--tier-2--core)
12. **Plugins import the core only through `core.sdk`** (and `@/core/sdk` on the frontend). The SDK is
    versioned; its surface is snapshotted; changing it without a version bump fails. → [§ 16](#16-the-versioned-sdk-facade--tier-1--core)
13. **A plugin never imports another plugin** — except a `TYPE_CHECKING`-only import of its
    `contracts` module. Collaboration is a service contract, an event, or a registry. → [§ 18](#18-service-contracts--tier-2--core), [§ 19](#19-the-in-process-event-bus--tier-2--core)
14. **A service contract has exactly one provider.** A second provider raises at boot; a caller
    either checks `has_service` or handles the error. → [§ 18](#18-service-contracts--tier-2--core)
15. **The event bus isolates failures and is not durable.** Anything that must survive a crash goes
    through the outbox. → [§ 19](#19-the-in-process-event-bus--tier-2--core)
16. **No `GenericForeignKey` for domain links.** Shared base table + per-app 1:1 extension table. → [§ 21](#21-shared-base-tables--11-extension-tables--tier-2--core)
17. **Deleting `project/` and every plugin leaves a working platform** — proven by a CI job that
    literally deletes them, not by a mock. → [§ 24](#24-boundary-and-architecture-tests--tier-1--core)
18. **A completeness test derives its universe from the code and fails — never skips — when that
    universe is empty.** → [§ 24](#24-boundary-and-architecture-tests--tier-1--core)
19. **Seam first, consumer second, one app per commit.** → [§ 25](#25-app-local-change-discipline--process)
20. **The generator's output is the reference plugin**, byte for byte, checked in CI. → [§ 26](#26-the-scaffolding-generator-and-the-reference-plugin--process)

---

## 1. The three-tier app taxonomy — **Tier 1 · Core**

**What.** `CORE_ARCHITECTURE_PLAN.md` § 1 splits the tree by **ownership** — `core/` (the
maintainer), `project/` (the product team), `plugins/` (one team per repo). That axis answers *who may
edit this file*. It does not answer *what may this code depend on*, and the second question is the
one that decides whether a plugin can be switched off, removed, or deployed without another. So every
Django app also declares a **layer**:

| Layer | Examples | Always on? | May import | May FK | Others may FK it? |
|---|---|---|---|---|---|
| **`platform`** — identity and shared reference data | `core`, `users`, `rbac`; a product's own reference-data app (`customers`, `organisations`) | **Yes.** Never toggleable, never discovered — hard-listed | lower `platform` apps only | `platform` | **Yes — the sanctioned FK** |
| **`kernel`** — reusable, domain-agnostic mechanisms | `notifications`, `webhooks`, `kb`, `search`, `alerts`, `automation`, `dataio` | Yes, when installed | `platform`, other `kernel` (acyclic) | `platform` | Only via the 1:1 extension pattern (§ 21) |
| **`plugin`** — one business capability each | `billing`, `crm`, `inventory` | **Toggleable** (§ 15) | `core.sdk` only (§ 16), its own package | `platform`, itself | **Never** |

Ownership and layer are orthogonal. A product's `project/customers/` app is owned by the product team
and declares `layer = "platform"` because several of its plugins reference customers. A core-owned
`notifications` app is `kernel`. A feature built inside the product repo rather than as a separate
repo is still `layer = "plugin"` and obeys every plugin rule — which is what lets it be extracted to
its own repo later without a rewrite.

**Why.** Plugins own their persistence so that a bug in one cannot reach another's data, and so a
plugin can be disabled or removed without dangling references. **The FK exception for platform apps
is deliberate:** forcing every consumer of plain reference data (a user, a customer, a currency)
through events or contracts is pure ceremony, and it throws away referential integrity. The exception
is safe *only because* platform apps are always on — a FK to something that can be switched off is a
FK to something that can vanish from under you.

**Rules.**
- **`layer` is a class-level string literal on the `AppConfig`** — `layer = "plugin"` — so it can be
  read by `ast` before Django is set up (§ 12). A computed value is rejected by the conventions test.
- **Promoting an app to `platform` is an ADR**, never a refactor. It makes the app un-removable and
  every plugin may start depending on it; that is a one-way door.
- **Kernel apps are domain-agnostic.** A kernel app never contains a business noun; plugins
  *contribute into* its registries (a plugin registers an alert source; the alert engine never knows
  what a server or an invoice is).
- **A kernel app never imports a plugin**, and never reads a plugin's tables. It learns about plugin
  data only through what the plugin registered.
- **Platform apps are hard-listed** in `settings.PLATFORM_APPS` so a missing one fails loudly at boot.
  Only plugins are discovered. Kernel apps are listed in `settings.KERNEL_APPS` — optional ones may be
  absent, and the SDK degrades (§ 16).
- **Third-party apps** (`rest_framework`, `corsheaders`) carry no layer and are ignored by the
  boundary tests; the conventions test applies to every app whose module lives under `backend/`.

**Django + Next shape.**

```python
# core/apps.py
class CoreConfig(AppConfig):
    name = "core"
    label = "core"
    layer = "platform"                 # literal — read by ast before django.setup()

# plugins/billing/djx_billing/apps.py
class BillingConfig(AppConfig):
    name = "djx_billing"
    label = "billing"                  # == plugin.toml name == url_prefix == prefix everywhere
    layer = "plugin"
```

`core/layers.py` exposes `layer_of(app_config) -> Literal["platform", "kernel", "plugin"]` and
`apps_in_layer(layer)`, both reading the declared attribute. The frontend mirrors the three layers as
directories (`src/core/`, `src/project/`, `src/plugins/<name>/`) with ESLint boundaries (§ 16).

**Enforced by.**
- `tests/architecture/test_layers.py::test_every_first_party_app_declares_a_literal_layer` — walks
  `apps.get_app_configs()`, filters to modules under `backend/`, and `ast`-parses each `apps.py` to
  prove the value is a literal, not only present.
- `test_layer_imports` — AST import scan per module, rules from the table above, universe from the
  declarations. Fails on an empty universe (§ 24 rule).
- `test_fk_targets_respect_layers` — for every model, every `ForeignKey`/`OneToOneField`/`ManyToMany`
  target's app layer is permitted by the table. **Must be able to fail:** a fixture plugin with a FK to
  another fixture plugin is part of the test's own positive control.
- `test_layer_sets_are_disjoint` — no label appears in two layers (a copy-paste `layer` is the typo
  this catches).

**Configurable, not hard-coded.** `PLATFORM_APPS`, `KERNEL_APPS` (settings lists, owned by
`config/settings.py`); the layer itself is declared by each app, never listed centrally.

---

## 2. Every core literal that names something is a registry — **Tier 1 · Core**

**What.** The rule: **any dict, list, tuple, set or frozenset literal in core (platform or kernel)
code whose members name models, URL paths or names, events, permissions, abilities, roles, tools,
queues or settings keys is a registry read, not a literal.**

**Why.** Count the places a product reaches into a platform and they are almost always literals: a
search allowlist of model classes, a recycle-bin list of types, a token-ability catalogue, a table of
"sensitive" paths for the rate limiter, a webhook event list, a notification-purpose list, a nav
builder that names every module's items, a list of route prefixes to skip in error alerting, a map of
routes to permissions for "bypass" roles. Each one is **the next product's first core edit** — which
is exactly the drift `core-guard.yml` exists to catch, found only after the fact. A real incident:
removing one plugin from a mature platform needed edits to roughly twenty core files, and a core page
that imported a plugin's model crashed outright on every install where that plugin was absent.

**Rules.**
- **"Core holds no table of plugin anything."** A plugin supplies its own refusal text, its own admin
  URL, its own labels. If core needs to say "manage this at …", the plugin registered the "…".
- **Role-name literals outside seeding code are banned.** "Who bypasses" is one function
  (`is_superuser`, per `AUTH_BLUEPRINT.md` A12); a second list of role names is the drift that makes
  the frontend show a senior role everything the backend refuses.
- **The literal may exist in the core if every member is core-owned** (core's own permission codes in
  `users/permissions.py`). The test judges members, not the existence of a literal.

**Django + Next shape.** `tests/architecture/test_core_literals_are_registries.py`:

```python
SHAPES = [
    re.compile(r"^[a-z_]+\.[A-Z]\w+$"),          # "app_label.Model"
    re.compile(r"^/"),                           # a URL path
    re.compile(r"^[a-z_]+:[a-z0-9_-]+$"),         # a URL name
    re.compile(r"^[a-z_]+\.[a-z0-9_]+\.[a-z0-9_]+"),  # permission / event / ability code
]
# For each module-level Assign in platform+kernel modules whose value is a collection literal:
#   member is a Name imported from a `.models` module  -> offence
#   member is a str matching SHAPES and its first segment is not the module's own app -> offence
```

Offences not yet fixed go in `tests/architecture/baselines/core_literals.txt` as
`path::NAME  — reason`. **The baseline is a two-way ratchet:** a new offence fails, and an entry that
no longer offends also fails ("delete me"), so the list can only shrink and never becomes decoration.

**Enforced by.** The test above, with a positive-control fixture module (`fixtures/offending_literal.py`)
it must flag, so a scanner that silently finds nothing is itself a failure.

**Configurable, not hard-coded.** Everything the rule touches becomes a registry in § 7.

---

## 3. The registry primitive and the uniform contribution shape — **Tier 1 · Core**

**What.** One generic `Registry[T]` class, and one base `Contribution` that every UI and behaviour
seam extends. About fifteen UI seams and twenty behaviour seams, **all the same shape**, so the gating
rules (owner enabled? flag on? permission held?) are implemented once and identical everywhere.

**Why.** When every "add X to another app's screen" need gets its own ad-hoc hook, each hook grows its
own gating — one checks the permission, one forgets the flag, one ignores the plugin switch — and the
soft-disable guarantee (§ 15) becomes only as strong as the least careful hook. One shape makes
"hidden when the plugin is off" a property of the primitive.

**Rules.**
- **The base shape** (every field is keyword-only):

  | Field | Meaning | Default |
  |---|---|---|
  | `key` | Namespaced id, `"<owner>.<thing>"`. Stable forever — it is stored (preferences, layouts, grants) | **required** |
  | `owner` | App label of the registrant. **Filled by the registrar**, never typed | automatic |
  | `permission` | RBAC code, a tuple meaning *any of*, or the sentinel `ANY_AUTHENTICATED` | **required — no default** |
  | `flag` | Feature-flag key ([`CONFIGURATION.md`](CONFIGURATION.md)); unknown flag = off | `None` |
  | `order` | Sort position; **gaps of 10**, so a newcomer slots in at 15 without renumbering | `100` |
  | `component` | Frontend component name, resolved by the generated component registry (§ 11) | `None` |
  | `props` | `Callable[[RequestContext], Mapping]` evaluated per request, server-side | `None` |

- **`permission` has no default, on purpose.** A contribution that forgot its gate fails to construct
  (`TypeError`), exactly as `required_permissions = None` denies in `AUTH_BLUEPRINT.md` § 9.1.
  Visible-to-everyone-signed-in is spelled `ANY_AUTHENTICATED` — greppable, reviewable, and never the
  accident.
- **Batch-shaped providers for anything per-row:** `row_data(row_ids, ctx) -> dict[id, Mapping]`,
  called **once per page**, never once per row. It is the N+1 guard, and a row missing from the
  mapping simply gets nothing.
- **Provider failures are isolated.** A `props`/`row_data`/badge provider that raises drops *that
  contribution* for *that request*, logs with the owner, and reports to error tracking. It never 500s
  the page or the shell. (Boot-time registration failures are the opposite — loud; § 4.)
- **Serialisation returns plain dicts**, never the registry objects, so nothing downstream can mutate
  shared state and responses are safe across threads.
- **Registries do not import what they reference.** Models are referenced as `"app_label.Model"`
  strings and resolved lazily with `apps.get_model`; callables are referenced directly (the registrant
  passes its own function). Core never imports a plugin to register it.

**Django + Next shape.**

```python
# core/registry/base.py — imports nothing from core
@dataclass(frozen=True, kw_only=True)
class Contribution:
    key: str
    permission: str | tuple[str, ...] | _AnyAuthenticated
    owner: str = ""                      # set by the registrar; empty = programming error
    flag: str | None = None
    order: int = 100
    component: str | None = None
    props: Callable[["RequestContext"], Mapping] | None = None

class Registry(Generic[T]):
    unknown_key_policy: ClassVar[UnknownPolicy]      # § 5 — required on every subclass
    def register(self, item: T) -> None: ...          # raises Duplicate / Sealed
    def get(self, key: str) -> T | None: ...          # applies unknown_key_policy
    def all(self) -> tuple[T, ...]: ...               # sealed, sorted by (order, key)
    def for_request(self, ctx: "RequestContext") -> tuple[T, ...]: ...  # owner enabled, flag, permission
    def serialize(self, ctx: "RequestContext") -> list[dict]: ...       # props evaluated, isolated
```

`RequestContext` carries the user, the per-request plugin-state snapshot (§ 15), the flag evaluator
and a memo so ten registries asking "is billing enabled?" cost one lookup.

**The bound registrar** is how `owner` is filled without stack inspection:

```python
# djx_billing/apps.py
def ready(self):
    from core.sdk import registrar
    from . import vocab, wiring
    r = registrar(self)            # binds owner="billing"; refuses keys not starting "billing."
    vocab.register(r)              # stage 1 (§ 6)
    wiring.register(r)             # stage 2
```

The registrar also refuses a key whose prefix is not the owner's label — the permission-prefix rule
of `PLUGIN_DEVELOPMENT.md`, generalised to every registry.

**Enforced by.** `tests/core/registry/test_contribution_shape.py` — constructing any contribution
without `permission` raises; a registrar refuses a foreign prefix; `for_request` hides an item whose
owner is disabled, whose flag is off, and whose permission is missing (three separate assertions, each
proven red by flipping the one input). `test_provider_failure_is_isolated` — a raising `props` drops
one item and the other items still serialise.

**Configurable, not hard-coded.** Order, gates and component are data on each contribution.

---

## 4. Registration rules — **Tier 1 · Core**

**What.** The lifecycle every registry obeys. These extend `CORE_ARCHITECTURE_PLAN.md` § 2
"Registration rules" and `AUTH_BLUEPRINT.md` § 7.2 (lazy seal), which remain correct.

**Why.** Registries only work if everything that *writes* them finishes before anything *reads* them,
and if the answer to "what is registered?" does not depend on when you ask. Every rule below closes a
way that assumption broke somewhere.

**Rules.**
1. **Only in `AppConfig.ready()`, through the registrar.** `register()` raises `RegistrationClosed`
   once `django.apps.apps.ready` is `True` (Django sets it after the last `ready()` returns — the one
   reliable "boot finished" fact).
2. **Boot-time and one-way.** No `unregister`. A disabled plugin is *filtered*, never removed (§ 15).
3. **Duplicates raise** `DuplicateRegistration`, naming both owners. Never last-write-wins — with
   last-write-wins, which plugin "won" depends on `INSTALLED_APPS` order, and changes silently when a
   plugin is added. URLconf mounts are also **identity-checked** (the same module mounted twice under
   two prefixes is a duplicate too).
4. **Seal lazily on first read** (per `AUTH_BLUEPRINT.md` § 7.2). **Add:** a read *before*
   `apps.ready` raises `RegistryNotReady` ("a registry was read during app loading — make this lazy"),
   so a `ready()` that reads a half-built catalogue fails at once instead of caching an incomplete one.
5. **Reads return immutable copies** — tuples of frozen dataclasses, sorted by `(order, key)`.
6. **DB-dependent values are callables**, evaluated at call time (`enabled=lambda: get_setting(...)`).
   Registration must work during `migrate`, `makemigrations`, `collectstatic` and against an empty
   schema.
7. **`ready()` touches no database.** Not a query, not a `get_or_create`, not a cache warm.
8. **Registration is order-independent.** Nothing may depend on which app's `ready()` ran first;
   reads sort, and cross-app references (an item into another app's nav section, a grant to another
   app's role) resolve at read time.
9. **`core/registry/` imports nothing from `core`** (existing rule) — contribution dataclasses and
   sentinels live there so vocabulary modules can import them without pulling the app registry in.
10. **Test isolation is named so it cannot be mistaken for runtime API:** `registry.reset_for_tests()`
    and the context manager `registry.isolated()`. Both raise unless running under pytest.

> ⚠️ **The `override_settings(INSTALLED_APPS=...)` trap.** Changing `INSTALLED_APPS` in a test
> re-runs `apps.populate()`, which re-runs every `ready()`, which re-registers everything — and rule 3
> raises. Tests that change the app set must wrap it in `registry.isolated()`, which snapshots, clears
> and restores. Re-importing a registering module with `importlib.reload` is **not** a substitute: a
> package already in `sys.modules` re-runs none of its side effects.

**Django + Next shape.** `core/registry/state.py` holds the seal flag per registry; `register()`
checks `apps.ready` and the seal; `all()` checks `apps.ready` then seals. The whole family lives in
one package; `core.sdk` re-exports the registrar and the contribution classes, never the registry
instances' mutating methods.

**Enforced by.**
- `test_ready_touches_no_database` — subprocess: `DATABASES` points at an unreachable host,
  `connection.ensure_connection` is patched to raise, `django.setup()` must succeed. Plus pytest
  `filterwarnings = error::RuntimeWarning` so Django's "accessing the database during app
  initialization" warning is a failure.
- `test_registration_after_boot_raises`, `test_read_during_loading_raises`,
  `test_duplicate_names_both_owners` (the message is asserted, because a duplicate error that does not
  say *who* costs an afternoon).
- `test_registration_is_order_independent` — boot twice in subprocesses, once with plugins in
  discovery order and once reversed; the serialised output of every registry must be identical.
- `test_reset_for_tests_refuses_outside_pytest`.

**Configurable, not hard-coded.** Nothing — these are invariants.

---

## 5. Unknown keys fail in a chosen, safe direction — **Tier 1 · Core**

**What.** Every registry declares `unknown_key_policy` — what `get()` and every consumer do with a key
nobody registered — **and a docstring saying why that direction is the safe one.**

**Why.** Several real incidents were "a check that cannot fail": a registry lookup that returned a
permissive answer for a key that was mistyped, not yet registered, or belonged to an absent plugin.
The direction is not the same for every registry, so it cannot be a global default — it has to be
chosen, per registry, on purpose.

**Rules.**
- **The deciding question: which failure gets reported?** A wrongly *denied* thing is reported by the
  blocked user within days. A wrongly *allowed* thing is reported by nobody. Choose the direction whose
  failure is visible.
- **The exception proves the rule.** For a capability **branch** switch (§ 20), *unregistered = on*
  (governed by its parent only) is the safe answer — because *off* would silently mute a plugin that
  has not yet learned switches exist, and a silently muted feature is the unreported failure there.
- **"Unknown" is never rendered as a good value.** No probe is `unverifiable`, not `verified`; no
  usage data is `untracked`, not `0`; a badge provider that failed shows no badge, not `0`
  ([`OBSERVABILITY.md`](OBSERVABILITY.md) "zero is not a fact").
- **The policy vocabulary is closed:** `DENY` · `OFF` · `RAISE` · `DROP` · `KEEP` · `STRICTEST` ·
  `UNVERIFIABLE` · `UNTRACKED` · `INHERIT` · `DORMANT`. A new policy is a change to this doc.

**Django + Next shape.** `class UnknownPolicy(StrEnum)`; each `Registry` subclass sets
`unknown_key_policy` and documents it; § 7's catalogue has the column.

**Enforced by.** `tests/core/registry/test_unknown_key_policies.py` — parametrised over **the registry
of registries** (every registry instance registers itself in `core.registry.catalogue`, so the test's
universe is derived, not typed). For each: the policy is declared, and a behavioural assertion for that
policy runs against a fresh key (`"nonexistent.key"`) and passes. A registry with no behavioural case
fails the test.

**Configurable, not hard-coded.** No — a policy is a design decision recorded in code.

---

## 6. Two-stage registration — vocabulary, then wiring — **Tier 1 · Core**

**What.** A registering app splits what it registers into two modules:

| Stage | Module | Registers | May import |
|---|---|---|---|
| **1 — vocabulary** | `<app>/vocab.py` (and `permissions.py`) | permission groups, roles, grants, default roles, nav sections, event declarations, setting and flag definitions, lookup kinds, activity verbs, abilities, error codes, slot declarations | `core.sdk.vocab` only — dataclasses and sentinels. **No models, no services, nothing from its own app beyond other vocab** |
| **2 — wiring** | `<app>/wiring.py` | URL mounts, jobs, event subscribers, service providers, UI contributions with `props`, probes, doctors | its own services, lazily |

Both run from `ready()`, stage 1 first. **The materialisers** — `rbac.seeding.sync_catalog()`, the
nav builder, the settings resolver — only ever *read* registries, lazily, after boot.

**Why.** Registries work only if the reader imports after every writer. The trap is a convenient
import from a vocabulary module *back into the materialising module* — e.g. a plugin's
`permissions.py` importing a constant from `rbac.catalog` "to avoid a typo". That import either
reintroduces the cycle or, worse, reads a half-built catalogue and caches it. The rule is blunt so it
can be tested: **vocabulary writes literals.** A typo in a literal is caught by `dbx.E002`; a cycle is
caught by nobody until it deadlocks an import.

Stage 1 also has to be importable **without the app registry** — by `manage.py export_contracts`
(§ 23), the scaffolding generator, doc generation and the core-only assembly test. A vocabulary module
that imports a model raises `AppRegistryNotReady` in exactly those tools.

**Rules.**
- A stage-1 module **never imports** `rbac.catalog`, `rbac.models`, `core.navigation.builder`, its own
  `models`/`services`, or anything that reads a registry.
- `config/urls.py` iterating `registry.api_routes` is safe: Django loads the URLconf after `ready()`.

**Enforced by.** `tests/architecture/test_vocabulary_modules.py` — AST scan of every `vocab.py` and
`permissions.py`; the only permitted `core` import is `core.sdk.vocab`; a positive-control fixture
that imports `rbac.catalog` must be flagged. Plus `test_vocab_imports_without_django` — import every
vocab module in a subprocess **without** `django.setup()`; it must succeed.

**Configurable, not hard-coded.** No.

---

## 7. The registry catalogue — **Tier 1 · Core**

**What.** Every seam the platform offers. The **Tier** column is when the registry must exist; the
**Owner doc** column is where the behaviour its entries drive is specified. **Shape** lists fields
beyond the base contribution shape (§ 3). Rows marked *(shape)* carry the full base shape; others are
plain registrations (`key` + `owner` + the listed fields).

> Build the generic `Registry[T]` first, then add registries as their consumers land. **Do not build a
> registry before its first real consumer** — a registry nobody reads is speculative machinery, and a
> registry nobody *writes* "sweeps nothing and reports success" (see § 24).

### 7.1 Access and routing

| Registry | A contributor registers | Unknown key → | Tier | Owner doc |
|---|---|---|---|---|
| `permissions` | permission group + permissions (`AUTH_BLUEPRINT.md` § 7.1) | **DENY**, logged as a bug; `dbx.E002` at boot | 1 | RBAC_DESIGN |
| `roles` | `RoleSpec(slug, label, description, grants: tuple \| ALL, is_system)` | **RAISE** at boot (a grant naming an unknown role is a typo) | 1 | § 8 |
| `role_grants` | `RoleGrant(role, permissions)` — **additive only** | **RAISE** for an unknown role; a grant to an `ALL` role is a no-op | 1 | § 8 |
| `default_roles` | `DefaultRole(slot="external"\|"internal", role)` | falls back to the core's zero-permission `staff` role | 1 | § 8 |
| `public_routes` | `PublicRoute(url_name, reason)` | **DENY** — not public; `dbx.E007` if a name does not resolve | 1 | § 9 |
| `api_routes` | `ApiMount(prefix, urlconf)`; prefix **must equal** the owner's label | route not mounted | 1 | § 9 |
| `external_callbacks` | `FrozenPath(url_name, path, reason)` — URLs registered in a third party's dashboard | **RAISE** in the test: `reverse(name) == path` must hold | 2 | § 9 |
| `scopes` | `Scope(model, owner_field, public_predicate=None)` — row scoping registration | **RAISE** `LookupError` — never an unfiltered queryset | 1 | DATA_LIFECYCLE |
| `throttle_scopes` | `ThrottleScope(key, default_rate, sensitive: bool)` | **STRICTEST** configured rate | 1 | API_PLATFORM |
| `api_abilities` | `Ability(code, label, group, sensitivity: low\|medium\|high, description)` — prose shown at grant time: what it exposes *and what it cannot do* | **DENY**; validation error when written onto a token | 2 | API_PLATFORM |
| `api_resources` | generic read-API resource: model, field allowlist, filterable, sortable, ability, page cap | **DROP** — not exposed; an unregistered related model serialises as its PK only | 2 | API_PLATFORM |
| `error_codes` | `ErrorCode(code, http_status, default_message)` | converted to `internal_error` 500 and logged | 1 | API_PLATFORM |
| `switches` | capability switches with parent/child (§ 20) | **OFF** for an unknown key; **INHERIT** for an unregistered branch | 2 | § 20 |

### 7.2 The shell and UI

| Registry | A contributor registers | Unknown key → | Tier | Owner doc |
|---|---|---|---|---|
| `nav_sections` *(shape)* | `NavSection(label, icon_key, collapsible)`, order in gaps of 10 | an item targeting it is **DROP**ped with `dbx.W103` | 1 | § 10 |
| `nav_items` *(shape)* | `NavItem(section, label, route, icon_key, badge=None)` | — | 1 | § 10 · FRONTEND_PLATFORM |
| `nav_badges` *(shape)* | `NavBadge(provider(ctx) -> int \| None, cache_seconds)` | no badge (never `0`) | 1 | § 10 |
| `dashboard_sections` *(shape)* | `DashboardSection(label, hint, loader(ctx))` — `hint` says what the section discloses, shown on the roles screen | **404**; a withheld section is *absent*, not empty | 2 | FRONTEND_PLATFORM |
| `widgets` *(shape)* | dashboard widget + grid geometry (`w`, `h`, `min_w`) | **DROP** from saved layouts; layout re-validated on save | 2 | FRONTEND_PLATFORM |
| `settings_tabs` *(shape)* | a tab on the Settings page + **its own** endpoint | **DROP** | 2 | CONFIGURATION |
| `slots` | `SlotSpec(slot_id, context: TypedDict)` — declared by the **host** page | a card for an undeclared slot is **DROP**ped, `dbx.W103` | 2 | § 11 |
| `detail_cards` *(shape)* | a card in another app's slot | **DROP** | 2 | § 11 |
| `card_actions` *(shape)* | a button inside another app's card | **DROP** | 2 | § 11 |
| `table_columns` *(shape)* | a column on another app's list, batched `row_data` | **DROP** | 2 | § 11 |
| `row_actions` *(shape)* | an action on another app's rows, batched `row_data`, optional per-row label | a row absent from `row_data` gets **no** action | 2 | § 11 |
| `form_extensions` *(shape)* | a section of fields on another app's form + `save()` | **DROP**; hidden when no user is passed (fail closed) | 2 | § 11 |
| `quick_actions` *(shape)* | palette / quick-create entries (`href` or action) | **DROP** | 2 | FRONTEND_PLATFORM |
| `frontend_pages` | plugin pages, generated (`registry.generated.ts`) | catch-all returns `notFound()` | 1 | § 11 · FRONTEND_PLATFORM |
| `frontend_components` | component names, generated (`components.generated.ts`) | "unavailable" boundary + CI failure | 2 | § 11 |
| `icon_keys` | frontend icon map keys (frontend-side) | neutral placeholder + logged; **CI failure** | 1 | § 10 |
| `csp_origins` | `CspOrigin(directive, origin, reason)` | **DENY** — default CSP | 2 | FRONTEND_PLATFORM |
| `cache_tags` | frontend data-layer tag types (frontend-side) | type error at build | 2 | FRONTEND_PLATFORM |
| `kb_pages` | discovered from `<app>/kb/**/*.md`, bound to routes by glob | no help page for that route | 2 | REUSABLE_MODULES |
| `getting_started` | via `nav_items` + `frontend_pages` (§ 10) | — | 1 | § 10 |

### 7.3 Data and lifecycle

| Registry | A contributor registers | Unknown key → | Tier | Owner doc |
|---|---|---|---|---|
| `activity_verbs` | `Verb(code, label, tone)`, **tone from a closed set**: `neutral · info · success · warning · danger` — never raw CSS | written anyway (audit never fails) with `meta.unregistered=True`; the test fails | 1 | DATA_LIFECYCLE |
| `data_sources` | provenance codes (`manual`, `import.csv`, `sync.<name>`) | **RAISE** at write (validation); displayed as "unknown" if found in old rows | 2 | DATA_LIFECYCLE |
| `retention_policies` | table, age, row cap, evidence opt-in | **KEEP** — never deleted; the doctor reports ungoverned growth | 1 | DATA_LIFECYCLE |
| `recyclable_types` | models that go to the recycle bin | **DENY** — not binnable, not restorable through the bin | 2 | DATA_LIFECYCLE |
| `extensible_bases` | a kernel/platform base table that accepts 1:1 extensions (§ 21) | a 1:1 onto an undeclared base fails `test_fk_targets_respect_layers` | 2 | § 21 |
| `search_sources` *(shape)* | `SearchSource(group, search(ctx))` | **DROP** | 2 | REUSABLE_MODULES |
| `export_specs` | `ExportSpec(model, natural_key, requires, exclude_columns)` | not exportable | 2 | DOMAIN_PRIMITIVES |
| `import_adapters` | row adapters attached to an export spec | not importable | 2 | DOMAIN_PRIMITIVES |
| `number_sequences` | document-number sequence kinds | **RAISE** | 2 | DOMAIN_PRIMITIVES |
| `demo_seeders` | `DemoSeeder(seed(), depends_on)` — per app, through services | skipped | 2 | ENGINEERING_PRACTICES |
| `install_config` | `InstallConfig(model, kind: singleton\|scoped\|schedule\|credential)` — how restore treats the model | treated as **data**; the test requires every model with an encrypted field or a schedule to be registered | 2 | CONFIGURATION · OPERATIONS |

### 7.4 Behaviour, integration and operations

| Registry | A contributor registers | Unknown key → | Tier | Owner doc |
|---|---|---|---|---|
| `events` | `EventSpec(name, payload: TypedDict, description, durable, webhook)` | publishing: **RAISE**; subscribing: **DORMANT** + `dbx.W104` | 2 | § 19 |
| `event_subscribers` | handlers by name or `"*"` | — | 2 | § 19 |
| `services` | one provider per contract name | **RAISE** `ServiceContractError`; `has_service` → `False` | 2 | § 18 |
| `webhook_events` | derived: every `EventSpec` with `webhook=True` | **DENY** at subscription and at emit (logged, 0 queued) | 2 | JOBS_AND_INTEGRATIONS |
| `notification_purposes` | purpose codes (`<owner>.<event>`) + default channels | **DROP** — not sent, logged loudly; never a default destination | 2 | NOTIFICATIONS_AND_ALERTING |
| `notification_events` | event × channel catalogue + preview function | **DROP** | 2 | NOTIFICATIONS_AND_ALERTING |
| `jobs` | `JobSpec(name, task, queue, lock, timeout)` | **RAISE** at enqueue | 1 | JOBS_AND_INTEGRATIONS |
| `schedules` | periodic entries referencing a job | **RAISE** at boot for an unknown job | 1 | JOBS_AND_INTEGRATIONS |
| `integrations` | every API relationship in or out | shown as "undeclared" | 2 | JOBS_AND_INTEGRATIONS |
| `credential_probes` | liveness probe per provider slug | **UNVERIFIABLE** — never "verified" | 2 | JOBS_AND_INTEGRATIONS |
| `usage_probes` | usage reader per integration | **UNTRACKED**, with a reason | 2 | JOBS_AND_INTEGRATIONS |
| `health_probes` | readiness component checks; data-plane (required-row) checks | a raising probe reports **down**, never ok | 1 | OBSERVABILITY |
| `doctors` | `manage.py doctor` sections, hard vs advisory | a raising doctor is a **failure** | 2 | OBSERVABILITY |
| `metrics` | counters/gauges with a **closed label universe**, pre-initialised at zero | label value coerced to `other` + a rejection counter (tests run strict) | 2 | OBSERVABILITY |
| `settings` | typed `SettingDef`; key namespace must equal owner | read of an unknown key **RAISE**s; an unknown DB row is reported by the doctor | 1 | CONFIGURATION |
| `feature_flags` | `FlagDef(key, description)` | **OFF** — a typo must never ship a feature | 1 | CONFIGURATION |
| `lookup_kinds` | admin-editable vocabularies (stable key + editable label) | **RAISE** | 2 | CONFIGURATION |
| `ai_tools` | assistant tools, each with a permission | **DROP** | 3 | REUSABLE_MODULES |
| `alert_sources`, `automation_triggers`, `automation_actions`, `document_templates` | owned by their kernel modules, same shape | **DROP** | 3 | REUSABLE_MODULES |

### 7.5 The plugin system itself

| Registry | Holds | Unknown key → | Tier | Owner doc |
|---|---|---|---|---|
| `plugins` | `PluginMeta` built from `plugin.toml` (§ 17) | "not installed" | 1 | § 17 |
| `catalogue` | every registry instance (the registry of registries) | — | 1 | § 5 |

**Enforced by.** Each registry ships `tests/core/registry/test_<name>.py` (shape, duplicates,
unknown-key behaviour); § 24 lists the cross-cutting tests.

**Configurable, not hard-coded.** The whole point: each row replaces a literal the core would
otherwise hold.

---

## 8. RBAC contributions — roles, additive grants, default roles — **Tier 1 · Core**

**What.** `RBAC_DESIGN.md` and `AUTH_BLUEPRINT.md` § 8.1 say "products add their own roles" but give
no mechanism. Three registries supply it without a core edit:

- `roles.register(RoleSpec(slug, label, description, grants=(...) | ALL, is_system=False))`
- `role_grants.register(RoleGrant(role="staff", permissions=("billing.invoices.view",)))`
- `default_roles.register(DefaultRole(slot="external", role="billing_customer"))`

**Why.**
- **Additive only**, because restating a role's list is a silent revert: a plugin that declares
  "staff = X, Y, Z" undoes every grant the core or another plugin adds to staff later. A plugin says
  "staff may *also* do X", never "staff is X".
- **An `ALL` role is left alone** — a role that holds everything must not be frozen at today's
  catalogue, which is also why `administrator` is recomputed on every seed.
- **Default roles are slots, not literals.** "Which role does a self-registered external account get"
  and "which role does a first-time single-sign-on internal user get" are product decisions. Unset
  falls back to the core's `staff` (holds nothing), which is the fail-closed answer.

**Rules.**
- **Grants apply once, then belong to the administrator.** A seeder that re-syncs role grants on
  every deploy wipes grants an administrator removed or added on the roles screen. A real incident: a
  re-sync seeder destroyed most of a live system's permissions and thousands of role assignments per
  run, with an empty intermediate state. So: `rbac_default_grant_ledger(role_slug, permission_code,
  applied_at)` — a registered default grant is applied **once per (role, permission)**, recorded, and
  never reapplied. An administrator's later removal sticks. (The seeding rules in `AUTH_BLUEPRINT.md`
  § 7.3 — never delete, deprecate — are unchanged.)
- **`is_system` roles registered by a plugin** are undeletable while that plugin is installed; when
  the plugin is removed, the role is marked deprecated by the seeder, never deleted (it holds
  assignments).
- **A role slug is namespaced** unless it is a core slot: plugin roles are `<owner>_<name>`.
- **The elevated-role guard** (`AUTH_BLUEPRINT.md` § 8.2) applies to plugin roles unchanged; a
  registered role that holds an `is_elevated` permission is itself elevated.
- **A default-role slot has exactly one registrant.** Two plugins claiming `external` is a conflict,
  and raises.

**Django + Next shape.** `rbac/seeding.py::sync_roles()` runs after `sync_catalog()` in the same
`post_migrate` hook: create registered roles, apply unapplied ledger grants, recompute `ALL` roles.
`rbac/selectors.py::default_role(slot)` reads the registry, falling back to `staff`.

**Enforced by.**
- `test_a_plugin_can_only_extend_a_role_never_replace_it` — registering a grant set for `staff` and
  then a core grant leaves both.
- `test_admin_removal_of_a_default_grant_survives_reseed` — apply, remove via the service, reseed,
  assert still removed.
- `test_unknown_role_in_grant_raises_at_boot` (`dbx.E105`).
- `test_default_role_slot_falls_back_to_staff`.

**Configurable, not hard-coded.** Roles, grants and default roles are registrations; the core's own
list stays at two (`AUTH_BLUEPRINT.md` § 8.1).

---

## 9. Public routes and API mounts — **Tier 1 · Core**

**What.**
- **`public_routes`** turns `AUTH_BLUEPRINT.md` § 9.2's `core/routes.py::PUBLIC_ROUTES` dict into the
  *core's own registrations* into a registry, so a plugin adds its anonymous surface
  (`PublicRoute("billing:payment-callback", "Signed by the provider; verified before any read.")`)
  without editing core and without an `AllowAny` scattered on a view.
- **`api_routes`** mounts each app's URLconf at `/api/<label>/`. The core mounts its own through the
  same registry (dogfooding), which is what lets the uniqueness test (§ 12) cover core prefixes too.
- **`external_callbacks`** freezes URLs a third party has stored in its own dashboard (payment
  webhooks, identity-provider redirects). Moving one breaks an integration silently, so each is a
  named frozen path with a reason, and a test asserts `reverse(name) == path`.

**Why.** A public allowlist that lives only in core forces a plugin either to edit core or to open
its own route inline — and the second is exactly what the exemption ledger exists to stop.

**Rules.**
- `dbx.E001`, `dbx.E007` and the route-enforcement test read **the union** of registered public
  routes, never a core-only constant.
- **Asserted in both directions:** no route is unexpectedly public, *and* every registered public
  route exists (rot detection).
- **A public route's reason is a sentence a reviewer can disagree with** (unchanged from § 9.2).
- **URL prefixes are reserved in one place:** the core registers `auth`, `users`, `rbac`, `health`,
  `schema`, `docs`, `me`, `meta`, `extensions` as its own mounts; a plugin named `health` fails the
  uniqueness test rather than shadowing a core path.
- **An API mount's prefix equals its owner's label.** No second spelling.

**Django + Next shape.**

```python
# config/urls.py — a composition point (§ 24); iterates, never enumerates
urlpatterns = [
    path(f"api/{m.prefix}/", include((m.urlconf, m.owner), namespace=m.owner))
    for m in registry.api_routes.all()
]
```

**Enforced by.** `test_route_enforcement.py` (existing) reading the union;
`test_every_registered_public_route_resolves`; `test_external_callbacks_are_frozen`;
`test_api_mount_prefix_equals_owner_label`.

**Configurable, not hard-coded.** Every public route and mount is a registration.

---

## 10. Navigation, badges and the first-run page — **Tier 1 · Core**

**What.** The nav tree is **built and filtered on the server** from `nav_sections` and `nav_items`,
and served to Next already filtered (endpoint and rendering: [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)).

**Rules.**
- **Order in gaps of 10.** Core sections sit at 10, 20, 30 …; a product's section at 15 lands under
  Dashboard without renumbering anything. Items inside a section follow the same convention.
- **An item may target a section it does not own** (a plugin adds "Invoices settings" to the core
  Settings section). If the target section is unknown — its owner is absent — the item is dropped with
  `dbx.W103`. If the owner is disabled, the section and its foreign items drop out together.
- **A section with no visible item is dropped.** An empty accordion is a disclosure that something
  exists and a click that leads nowhere.
- **Longest-prefix active match**, so exactly one leaf is highlighted for any path.
- **Collapsible sections register into the per-role collapse-preference catalogue automatically**
  (no second list to keep in step).
- **Icons are string keys** resolved by a frontend icon map. An unknown key renders a neutral
  placeholder *and logs*, and CI fails first (`test_every_registered_icon_key_exists`) — because an
  unknown icon otherwise renders as nothing, with no error, forever.
- **Nav visibility is presentation, not access control.** The route carries its own gate. The nav
  manifest *also* drives the frontend route gate so the sidebar and the page can never disagree, and
  an orphan route with no manifest entry is denied (FRONTEND_PLATFORM owns that gate).
- **A badge is a disclosure.** A count on a nav item tells the reader how many rows exist; its
  provider counts through `visible_to(user)` ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)), its
  permission defaults to the item's and may be stricter, it is cached per user
  (`NAV_BADGE_CACHE_SECONDS`, default 90), and a failed provider shows **no badge**, never `0`.

**The first-run page.** The `project/` skeleton ships **one** registration: a section "Project" at
order 15 with a "Getting started" item and page that says, in the product's voice, "your screens go
here — this is how this page got here", and names the nine lines that put it there. Why: an empty
section is dropped, so a newcomer otherwise sees a complete platform and no clue where their work
goes; it is also the shortest worked example of the seam, and it proves on the very first sign-in
that `project/` registration works with zero core edits. Placeholder copy announces itself as
placeholder. Deleting it is the product's first commit. **A plugin may register the same kind of
landing page** for its own section, and the generator emits one (§ 26).

```python
# project/vocab.py — the whole first-run example
def register(r):
    r.nav_sections.register(NavSection(key="project.main", label="Project", order=15,
                                       icon_key="folder", permission=ANY_AUTHENTICATED))
    r.nav_items.register(NavItem(key="project.getting_started", section="project.main",
                                 label="Getting started", route="/project/getting-started",
                                 icon_key="sparkles", order=10, permission=ANY_AUTHENTICATED))
```

**Enforced by.** `test_empty_section_is_dropped`, `test_item_into_unknown_section_is_dropped_with_warning`,
`test_longest_prefix_highlights_one_leaf`, `test_every_registered_icon_key_exists` (backend keys
exported by `export_contracts`, compared by a frontend test against the icon map),
`test_badge_failure_renders_no_badge`, `test_getting_started_is_registered_through_the_seam` (the
page appears, and `core_doctor` reports zero core drift).

**Configurable, not hard-coded.** Sections, items, badges, icons, order — all registrations.
`NAV_BADGE_CACHE_SECONDS` is a setting.

---

## 11. UI slots and the component registry — **Tier 2 · Core**

**What.** A host page declares named **slots**; other apps contribute cards, card actions, table
columns, row actions and form sections into them. The backend sends, per page or per shell response,
`{slot_id: [{key, component, props}]}`; Next resolves `component` through a **generated** component
registry and renders it in a `<Slot id="…" />`.

**Why.** Every "add X to another app's screen" need either becomes a registry entry or becomes an edit
to the host app — and the second is a cross-app change that couples owners (§ 25). With slots, the host
names only a slot id; it never learns which plugin fills it.

**Rules.**
- **The host declares its slots** (`SlotSpec("users.user.detail.sidebar", context=UserDetailCtx)`),
  with a typed context. A card for an undeclared slot is dropped with `dbx.W103` — the host may simply
  be absent.
- **Props are computed server-side and scoped.** A card's `props(ctx)` receives the host object's id
  and must re-read through `visible_to(user)`; the slot context is not authority.
- **Batched row providers.** `table_columns` and `row_actions` use `row_data(row_ids, ctx)` once per
  page. A row missing from the mapping gets no cell value and no action. A per-row `label` override
  is reserved (Assign/Unassign).
- **The contributor executes; the host never does.** A row action posts to the contributing
  plugin's own endpoint with the row id; the host renders a button and nothing more.
- **Form extensions and mass assignment.** Hiding a section in the UI does not stop a hand-crafted
  POST. `form_extensions.denied_field_names(form_id, instance, user)` returns the field names of every
  section the user was *not* shown, and the host serializer strips them before validation. A section
  with a permission is hidden when no user is passed (fail closed). **Extension fields persist in the
  contributor's own 1:1 extension table** (§ 21), saved by the section's `save()` inside the host's
  transaction — never as new columns on the host.
- **Settings tabs save to their own endpoint** and never write core configuration.
- **Dashboard sections are gated one by one.** A withheld section is not computed and not sent — a
  real incident: a dashboard payload carried a full organisation tree and a list of recent users'
  names and emails that no component rendered, invisible on screen and fully readable in devtools.
  "Absent" and "empty" are different answers.
- **Why the component registry is generated:** the bundler must see literal import paths. A runtime
  string passed to `import()` is not something Turbopack can split, so
  `frontend/src/plugins/components.generated.ts` holds one literal
  `dynamic(() => import("@/plugins/billing/components/InvoiceCard"))` per component, written by the
  generator from filename convention (`src/plugins/<name>/components/<Name>.tsx` → key
  `"<name>.<Name>"`).

**Django + Next shape.**

```tsx
// src/core/slots/Slot.tsx — renders only what the server sent; knows no plugin
export function Slot({ id, items }: { id: string; items: SlotItem[] }) {
  return items.map((it) => {
    const C = componentRegistry[it.component];
    return C ? <ErrorBoundary key={it.key} fallback={<Unavailable />}><C {...it.props} /></ErrorBoundary>
             : <Unavailable key={it.key} />;
  });
}
```

Backend: `core/ui/slots.py::serialize_slots(ctx, slot_ids)`; host serializers inherit
`ExtensibleSerializerMixin` (`form_id = "users.user"`) which calls `denied_field_names`.

**Enforced by.** `test_row_data_called_once_per_page` (a counting provider), `test_row_absent_from_mapping_gets_no_action`,
`test_denied_fields_are_stripped` (POST a hidden section's field as a user without its permission;
the value must not persist), `test_form_section_with_permission_hidden_without_user`,
`test_withheld_dashboard_section_absent_from_payload` (walk the JSON; no unregistered or withheld key
appears), frontend `components.test.ts` — every component name the backend registered (from
`export_contracts`) exists in `componentRegistry`.

**Configurable, not hard-coded.** Slot ids are declared by hosts; everything in them is contributed.

---

## 12. Plugin discovery — **Tier 1 · Core**

**What.** `core/plugins.py::discover(PLUGINS_DIR)` runs **inside `config/settings.py`**, before
`django.setup()`, and appends discovered plugin packages to `INSTALLED_APPS` (BUILD_ORDER 3.1).

**Why read without importing.** Settings run before the app registry exists. Importing plugin code
there touches the registry (`AppRegistryNotReady`), runs arbitrary top-level code during settings
load, and turns one plugin's syntax error into a settings-import failure with a misleading traceback.
So discovery reads **declarations**, never code: `plugin.toml` with the stdlib `tomllib`, and — for
the `layer` of in-repo apps — the `AppConfig` class body with `ast`. And it removes the unowned parent
edits: adding a plugin used to mean editing a settings list, a URL line and a permissions merge, all
of which authors forgot and no plugin test could catch.

**Rules.**
- **`plugin.toml` is the manifest** (§ 17). Discovery reads `name`, `package`, `order`; nothing else
  is needed at settings time.
- **Deterministic order:** sort by `(order, name)`. `order` defaults to 100. Nothing may *depend* on
  it (§ 4 rule 8); it exists so tie-breaks and logs are stable.
- **Accessibility, not import:** `importlib.util.find_spec(package)` on the **top-level** package
  (which does not execute it). Resolvable → installed. Unresolvable → `settings.MISSING_PLUGINS`, a
  `dbx.W101` warning, and an error row on the Extensions page. A submodule that was never initialised
  is the usual cause.
- **`PLUGINS_EXPECTED`** (env list, set in production) turns a missing *expected* plugin into
  `dbx.E103` — a deploy that lost a plugin must not boot quietly without it.
- **`url_prefix` is unique and non-overlapping** across core and every plugin: no duplicates, no
  prefix that is a path-prefix of another (`bill` vs `billing`), none in the reserved core set (§ 9).
- **The `AppConfig` must agree with the manifest:** `label == name`, `layer == "plugin"`, and the
  package matches. Two sources of truth that disagree is the conventions test's job to catch.
- **Import path.** How `djx_<name>` becomes importable — `sys.path` insertion of each plugin root, or
  a `uv` workspace member per plugin — is a **pending decision** (below), because it decides where a
  plugin's own third-party dependencies are declared.

**Django + Next shape.**

```python
# core/plugins.py — imported by config/settings.py; imports nothing from Django apps
def discover(root: Path) -> list[Discovered]:
    found = []
    for toml_path in sorted(root.glob("*/plugin.toml")):
        meta = tomllib.loads(toml_path.read_text())["plugin"]      # a malformed file raises, with its path
        spec = importlib.util.find_spec(meta["package"])
        found.append(Discovered(meta=meta, root=toml_path.parent, accessible=spec is not None))
    return sorted(found, key=lambda d: (d.meta.get("order", 100), d.meta["name"]))
```

The same declarations feed the frontend generator (`scripts/plugins.py generate` →
`registry.generated.ts`), so the backend and frontend plugin lists cannot disagree.

**Enforced by.** `tests/architecture/test_plugin_discovery.py` —
`test_url_prefixes_unique_and_non_overlapping`, `test_every_discovered_plugin_is_mounted`,
`test_every_plugin_contributes_permissions_under_its_prefix`, `test_appconfig_agrees_with_manifest`,
`test_discovery_survives_a_broken_file` (a fixture directory with a malformed `plugin.toml` and one
with a Python syntax error: discovery reports the first with its path and is unaffected by the second,
because it never imports it), `test_discovery_order_is_deterministic`.

**Configurable, not hard-coded.** `PLUGINS_DIR` (default `backend/plugins`), `PLUGINS_EXPECTED`.

---

## 13. Absent vs broken — **Tier 1 · Core**

**What.** One function, `core/composition.py::import_optional(module, *, package)`, is the **only**
place the core imports something that may legitimately not exist: the `project` package, an optional
kernel app behind the SDK (§ 16), an optional conventional submodule. Every composition point goes
through it.

**Why.** A bare `except ImportError` makes *"this module has a typo on line 40"* indistinguishable
from *"this module is not installed"*. The whole module silently vanishes from the catalogue, and the
only symptoms are missing permissions and 404s — which look like an RBAC bug and cost a day. This was
verified for real by deleting a package directory, not by reasoning about it.

**Rules.**
- **Swallow `ModuleNotFoundError` only when `exc.name` is the optional module itself or its
  package.** Any other missing name — a dependency imported *inside* the module — is "broken", and
  re-raises.
- **Never swallow `ImportError` in general.** `from x import y` with `y` missing raises plain
  `ImportError`; a present module with a bad import is broken, and must fail loudly.
- **Loud at boot is safe** because boot happens in the deploy gate: `manage.py check` runs in the new
  image before it receives traffic ([`OPERATIONS.md`](OPERATIONS.md)), so a broken plugin fails the
  deploy and the old containers keep serving. The only failure boot cannot see is a lazy import at
  request time — § 14 handles that.

```python
def import_optional(module: str, *, package: str) -> ModuleType | None:
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name in {module, package}:
            return None          # absent — a legitimate state
        raise                    # something INSIDE it is missing — broken, not absent
```

**Enforced by.** `tests/core/test_composition.py` — `test_absent_package_returns_none`,
`test_absent_submodule_returns_none`, `test_broken_module_raises` (a fixture module that imports a
nonexistent dependency), `test_import_error_inside_present_module_raises`, and
`test_it_is_not_a_bare_except` (inspects the source). Plus
`tests/architecture/test_no_import_swallow.py` — AST scan of platform and kernel code: any
`except ImportError`/`except ModuleNotFoundError` outside `core/composition.py` fails.

**Configurable, not hard-coded.** `PROJECT_PACKAGE = "project"` — the one name the core knows, and it
is generic on purpose.

---

## 14. Defensive loading, runtime auto-disable, skew-aware liveness — **Tier 2 · Core**

**What.** Three layers that stop one broken plugin from taking the site down, each catching what the
previous cannot.

| Moment | Mechanism | Catches |
|---|---|---|
| **Settings** | `find_spec` at discovery (§ 12) → `MISSING_PLUGINS`, warning, Extensions error row | a plugin whose package is not on disk |
| **Boot** | absent-vs-broken (§ 13); a plugin's `ready()` raising fails boot | a present-but-broken plugin — fails the deploy gate |
| **Request** | `PluginImportFailureMiddleware.process_exception` | a **lazy** import inside a plugin view that fails at request time |
| **Liveness** | a skew check contributed to `/health/live` | a live process whose plugin package vanished under it |

**Why.** The "live process, vanished files" state — a plugin still in `INSTALLED_APPS` whose files
were removed by an in-place update — makes every lazy import 500 on every hit, forever, while the
process looks healthy.

**Rules.**
- **Request-time:** an `ImportError` raised from a view whose module belongs to a `plugin`-layer app
  (resolved by `apps.get_containing_app_config(view_module)`) auto-soft-disables that plugin (§ 15),
  raises an ops alert ([`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md)), and returns
  **503** `plugin_unavailable`. The next request is short-circuited by the soft-disable middleware
  before the lazy import runs. **Platform and kernel import errors remain ordinary 500s** — they are
  not switchable and must not be hidden.
- **The auto-disable is scoped to the release that failed.** `PluginState.auto_disabled_release` holds
  the `RELEASE_ID` of the process that hit the error; a process running a different release ignores
  it. Why: during a rolling deploy, a broken new image must not switch the plugin off for the old
  containers still serving it correctly — and a fixed next release comes up with the plugin on,
  without anyone remembering to flip it back. A human-set disable is unscoped.
- **Liveness is skew-aware.** `/health/live` returns 503 when an installed plugin's package no longer
  resolves (`importlib.invalidate_caches()` then `find_spec`). The orchestrator restarts the process;
  on restart, discovery drops the plugin as missing — so there is no restart loop.
- **The frontend equivalent:** a generated import that fails to load (a chunk missing after a deploy)
  renders a "module unavailable — reload" boundary, never a crashed route tree (FRONTEND_PLATFORM).

**Django + Next shape.** `core/middleware/plugins.py` (both middlewares), `core/health/plugin_skew.py`
registered into `health_probes` with `liveness=True`.

**Enforced by.** `tests/core/test_extension_resilience.py` — settings guard drops an inaccessible
plugin; the Extensions endpoint shows it as an error row; a view raising `ImportError` auto-disables
and returns 503, the next request never reaches the view; a kernel view raising `ImportError` returns
500 and disables nothing; an auto-disable recorded under release A is ignored by a process on release
B; the liveness check goes 503 when `find_spec` returns `None`.

**Configurable, not hard-coded.** `RELEASE_ID` comes from the release image (OPERATIONS).

---

## 15. The soft-disable contract — **Tier 2 · Core**

**What.** Every `plugin`-layer app can be switched off at runtime from the Extensions page. **One
switch governs every surface.** Disabling never unloads the app, never runs a migration, never deletes
or hides data at rest, and needs no restart. Platform and kernel apps always report enabled, and the
API refuses to toggle them.

**Why.** "Disabled" drifts unless it is a stated contract: the ungated surface is always the one
nobody thought of — a nav item missing its owner, a search source still answering, a nightly task
still emailing customers about a feature that was switched off. Uninstall-on-disable was rejected
because it destroys data and needs a restart.

**Rules — every surface, and what "off" means there:**

| Surface | When the owning plugin is disabled | Mechanism |
|---|---|---|
| HTTP API + pages | **403** `plugin_disabled` | `PluginEnabledMiddleware.process_view` resolves the owner from the view's module (`func.cls.__module__` for DRF viewsets, `func.view_class` for `APIView`), so it covers **any** URL, whatever its prefix |
| Every UI registry (§ 7.2) | hidden | `Registry.for_request` filters by `owner` |
| Search sources, export specs, import adapters, KB pages | skipped / hidden | same filter |
| Event subscribers | not called | the bus filters by subscriber `owner` (§ 19) |
| Signal receivers | not called | `@plugin_receiver(signal)` wrapper — the only way a plugin connects a signal |
| Celery tasks and schedules | **skipped at run time**, recorded as `skipped: plugin_disabled` in the run monitor | `@plugin_task` decorator ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)) |
| Service contracts it provides | `has_service` → `False`; `call_service` raises `ServiceUnavailable` | the services registry filters by provider owner |
| Rows it owns in shared base tables (§ 21) | excluded from host lists by default | base manager filters `source_app` against the disabled set |
| Its permissions | **stay in the catalogue**, grants intact, shown as "plugin disabled" on the roles screen | nothing removed — so re-enabling restores access exactly |
| Frontend routes | catch-all returns `notFound()` | the shell payload lists disabled plugins |

- **Why 403 and not 404:** the route-enforcement test calls every route unauthenticated and accepts
  only 401/403; a 404 would read as "the handler ran a lookup first". And a disabled feature is "not
  permitted now", not "does not exist".
- **Why the decorator is checked at run time, not at enqueue:** a task enqueued before the switch and
  run after it must still no-op.
- **One lookup per request.** The disabled set is read once into `RequestContext` and cached in the
  shared cache behind a generation counter bumped on toggle (`PLUGIN_STATE_CACHE_SECONDS`, default
  300, as a backstop). An uncached `is_enabled()` per registry item is a query per contribution per
  request.
- **Missing row = enabled.** Installing a plugin makes it live; turning it off is the explicit act.
- **Toggling is audited** (`extensions.plugin.disabled|enabled`, with reason) and needs its own
  permission, `core.extensions.manage`, separate from `core.extensions.view`.

**Django + Next shape.** `core_plugin_state(label PK, enabled, reason, changed_by, changed_at,
auto_disabled_release NULL)`; `core.sdk.plugin_enabled(label)`; the two decorators; the middleware;
`/api/extensions/` for the page.

```python
@plugin_task(queue="default")          # owner inferred from the task's module
def send_overdue_reminders(): ...

@plugin_receiver(user_logged_in)
def warm_billing_cache(sender, user, **kw): ...
```

**Enforced by.**
- `test_every_plugin_celery_task_is_gated` — enumerate `celery_app.tasks`, map each `task.__module__`
  to its app's layer; every plugin-layer task must carry the decorator's marker. Fails on an empty
  universe.
- `test_every_plugin_signal_receiver_is_gated` — AST scan of plugin modules: `receiver(` and
  `.connect(` are banned; only `plugin_receiver` is allowed.
- `test_disabled_plugin_every_surface` — one parametrised test over the table above, driven by a
  fixture plugin that contributes to every registry: disable it, assert each surface is off; enable
  it, assert each is back. **This is the contract's executable form.**
- `test_disabled_state_is_one_query_per_request` (`django_assert_max_num_queries`).
- `test_platform_and_kernel_cannot_be_disabled`.

**Configurable, not hard-coded.** The switch is runtime data; `PLUGIN_STATE_CACHE_SECONDS` is a
setting.

---

## 16. The versioned SDK facade — **Tier 1 · Core**

**What.** `backend/core/sdk/` is **the only module a plugin imports from the core**, and
`frontend/src/core/sdk/` (`@/core/sdk`) the only one its frontend imports. It re-exports the stable
contracts and adds almost nothing of its own.

| Backend `core.sdk` exports | Frontend `@/core/sdk` exports |
|---|---|
| `registrar`, every contribution class, `ANY_AUTHENTICATED` | `Slot`, `DataTable`, form primitives, `Unavailable` |
| `BaseViewSet`, `BaseAPIView`, `HasPermission`, `HasAbility` | `api` client, typed error classes |
| base model mixins, the `visible_to` queryset base | `usePermissions`, `can`, `useFlag`, `useShell` |
| `log_activity`, `get_setting`, `flag_enabled`, `project()` | design-token helpers, `statusTone` |
| `emit`, `subscribe`, `call_service`, `has_service`, `provide` | `defineCacheTags` |
| `plugin_task`, `plugin_receiver`, `plugin_enabled` | |
| `ServiceError` family, `safe_http` client | |
| `notify`, `enqueue_job` (optional kernel pieces) | |
| `core.sdk.testing` — factories, `registry.isolated`, API client | `@/core/sdk/testing` |

**Why.** Without a facade, plugins reach into kernel internals, and every internal refactor in the
core breaks a plugin owned by a team that never opened the core — the opposite of VISION property 2.
A versioned surface is also what makes "this plugin was built against core X" a checkable statement
instead of folklore.

**Rules.**
- **`SDK_VERSION = (major, minor)`** with **`SDK_CHANGELOG`** in code — one entry per minor saying what
  was added and why. Adding an export is a minor bump; removing, renaming or changing a signature is a
  major bump, preceded by one minor that emits `DeprecationWarning`.
- **`is_compatible(target)`** — same major, and current minor ≥ target minor.
  **`require_version("1.3")`** raises `SDKVersionError` at plugin import so an incompatible plugin fails
  fast at boot, not at the first call.
- **`capabilities()`** reports what is actually live: registered service contracts, declared events,
  which optional kernel pieces are installed. Served (behind `core.extensions.view`) at `/api/meta/`
  with the SDK version and plugin statuses; **never public** — a version string is reconnaissance.
- **Optional kernel pieces degrade to inert stubs.** If the notifications app is not installed,
  `notify(...)` raises `NotInstalled("notifications")` with a clear message, while *registering* a
  notification purpose still works (it is stored, dormant). Lazy query facades return empty values
  (`[]`, `0`) when their app is absent. All of this goes through `import_optional` (§ 13) — absent is
  degraded, broken is loud.
- **Plugins import only `core.sdk`.** Enforced, not advised: a plugin reaching `core.navigation`
  directly works today and breaks silently the day it is refactored.
- **The `project/` apps obey the same rule.** They live in the core's repo, but the product team owns
  them, and a core update that breaks them is a merge conflict the product pays for. Importing core
  internals from `project/` is allowed only through a ratcheted baseline, which can only shrink.

**Django + Next shape.** `core/sdk/__init__.py` with an explicit `__all__`;
`core/sdk/api_snapshot.txt` (sorted `__all__` plus each callable's `inspect.signature`);
`frontend/src/core/sdk/index.ts` with explicit named exports and an equivalent
`api_snapshot.txt` produced by `tsc --declaration`.

**Enforced by.**
- `tests/architecture/test_plugins_import_only_sdk.py` — AST: from a plugin-layer module, any
  `import core…` / `from core… import` other than `core.sdk` fails; so does `from users…`/`from rbac…`.
- ESLint `no-restricted-imports` in `frontend/eslint.config.mjs`, scoped to `src/plugins/**` and
  `src/project/**`: forbid `@/core/*` except `@/core/sdk`, forbid `@/plugins/*` from another plugin,
  forbid `@/project/*`.
- `test_sdk_surface_matches_snapshot` — a changed surface fails unless the snapshot is updated…
- …and `test_snapshot_change_bumps_version` — the snapshot's hash is recorded in the latest
  `SDK_CHANGELOG` entry, so updating the snapshot without a version bump and a changelog line fails.
- `test_optional_kernel_absent_degrades` — with `notifications` absent, registration succeeds and
  `notify` raises `NotInstalled`.

**Configurable, not hard-coded.** The version is a constant — correctly, because it describes the
contract, not the environment.

---

## 17. The plugin manifest and `validate_plugins` — **Tier 2 · Core**

**What.** `plugin.toml` is the single declaration of a plugin; `PluginMeta` is built from it (never
re-declared in `ready()`), and `manage.py validate_plugins` reports the health of the whole set.

```toml
[plugin]
name        = "billing"            # == label == url_prefix == every prefix
package     = "djx_billing"
version     = "1.4.0"
sdk_target  = "1.3"
order       = 100
description = "Invoices, credit notes and payment allocation."
requires    = ["crm>=1.0"]         # other plugins, by name + version specifier
provides    = ["billing.invoice_totals.v1"]   # service contracts (§ 18)
consumes    = ["crm.customer_lookup.v1"]
[plugin.frontend]
root = "frontend"
```

**Why.** Dependency and compatibility problems must be visible before the first user trips them, and
visible **without importing anything** — `provides`/`consumes` let the tool answer "consumes X, but no
installed plugin provides X" from declarations alone.

**Rules.**
- **`list_plugins()` never raises.** It computes a status per plugin — `ok`, `disabled`,
  `auto-disabled (release …)`, `missing`, `sdk-incompatible`, `requires-unsatisfied` — for the
  Extensions page, even when several are broken at once.
- **Severity, deliberately:**

  | Finding | Level | Why |
  |---|---|---|
  | SDK major differs, or `sdk_target` minor newer than the core | **`dbx.E102`** — refuse | it *will* crash, at a call site nobody can predict |
  | Expected plugin missing (`PLUGINS_EXPECTED`) | **`dbx.E103`** — refuse | a deploy lost a feature |
  | `requires` unsatisfied | `dbx.W102` — warn | consumers degrade through `has_service` |
  | `consumes` with no provider | `dbx.W106` — warn | same |
  | A plugin auto-disabled for the running release | `dbx.W105` — warn | someone must look |

- **`validate_plugins` prints a table and exits non-zero on any Error**, so it is a CI step and a
  pre-deploy step. It is also a registered doctor section ([`OBSERVABILITY.md`](OBSERVABILITY.md)).
- **Plugin docs live in the plugin repo** (`README.md` next to `plugin.toml`, per
  `CORE_ARCHITECTURE_PLAN.md` § 0); `docs_url` is relative to the plugin root.

**Enforced by.** `tests/core/test_plugin_manifest.py` — schema validation (unknown keys in
`plugin.toml` are an error, so a misspelt `sdk_taget` is not silently ignored), each severity row with
a fixture, `validate_plugins` exit code.

**Configurable, not hard-coded.** Declarative per plugin.

---

## 18. Service contracts — **Tier 2 · Core**

**What.** The synchronous, request/response companion to the event bus: a **named** contract with
**exactly one provider**. `provide(name, impl)` in wiring; `call_service(name, **kwargs)` anywhere;
`has_service(name)` to guard. The name plus the agreed arguments and return shape *is* the interface;
neither side imports the other at run time.

**Why.** Some cross-plugin needs require an answer — "resolve this customer's billing account, then
charge it" — which a fire-and-forget event cannot give. Without a contract registry the answer is a
cross-plugin import, which breaks the day the other plugin is absent.

**Rules.**
- **A second provider raises at boot.** Two providers mean two plugins fighting over one contract;
  "whichever registered last" is not a resolution.
- **Every caller degrades or fails deliberately:** it checks `has_service(name)` first, or it handles
  `ServiceContractError` (`ServiceUnavailable` when the provider's plugin is disabled, `NoProvider`
  when none is installed).
- **Types live with the provider, and are imported for type-checking only.** The provider publishes a
  `Protocol` and `TypedDict`s in `djx_<name>/contracts.py` (pure typing, imports nothing but `typing`
  and `core.sdk.vocab`). A consumer imports it **only** under `if TYPE_CHECKING:` — so the type
  checker verifies both sides while the runtime has no dependency and survives the provider's
  absence. This is the single sanctioned exception to the cross-plugin import ban.
- **Platform-wide contracts** (render a PDF, send a notification, resolve an actor's display name)
  live in `core/contracts/` and are named for the capability, never for a plugin.
- **Contracts are versioned in the name** — `billing.invoice_totals.v1`. Changes are additive (new
  optional argument, new result key); a breaking change is a new name, and the provider serves both
  for a deprecation period.
- **Arguments and results are plain data** (ids, scalars, `TypedDict`s) — never model instances. A
  model instance couples the caller to the provider's schema.

```python
# consumer — djx_crm/services.py
if TYPE_CHECKING:
    from djx_billing.contracts import InvoiceTotals
INVOICE_TOTALS = "billing.invoice_totals.v1"

def account_summary(customer_id: int) -> dict:
    if not has_service(INVOICE_TOTALS):
        return {"billing": None}                     # degrade: the panel says "billing not installed"
    totals: "InvoiceTotals" = call_service(INVOICE_TOTALS, customer_id=customer_id)
    return {"billing": totals}
```

**Enforced by.**
- `test_every_called_contract_has_exactly_one_provider` — AST-collect every `call_service(<const>)`
  name across all installed apps; with all plugins installed, each has one provider. Universe must be
  non-empty once any contract exists.
- `test_every_caller_guards_or_handles` — AST heuristic: each `call_service` call sits in a function
  that also calls `has_service` for that name or is inside `try/except ServiceContractError`; offences
  go to a ratcheted baseline.
- `test_provider_matches_protocol` — for each provided contract with a `Protocol`, the implementation's
  `inspect.signature` matches.
- `test_duplicate_provider_raises`, `test_disabled_provider_is_unavailable`.
- `test_no_cross_plugin_imports` allows exactly `TYPE_CHECKING`-guarded imports of `djx_<other>.contracts`.

**Configurable, not hard-coded.** The provider is chosen by what is installed.

---

## 19. The in-process event bus — **Tier 2 · Core**

**What.** `core/events.py`: a frozen `DomainEvent(name, aggregate_id, payload, metadata)` and a
dispatcher with **failure isolation**, **wildcard subscribers**, and **handler errors returned to the
publisher**. It is how plugins react to facts without depending on each other.

**Why a bus and not Django signals for collaboration.** Signals re-raise a receiver's exception into
the sender unless every sender remembers `send_robust`; they have no wildcard (which the automation
engine needs); they are not declared, so "what events exist?" has no answer; and model signals fire on
raw saves but not on `bulk_create`/`update()`, so they describe the ORM, not the domain. The bus fixes
all four. Django's own framework signals (`post_migrate`, `user_logged_in`, `request_finished`)
remain fine for framework hooks — through `plugin_receiver` when a plugin connects one (§ 15).

**Rules.**
- **Declared vocabulary.** `EventSpec(name, payload, description, durable=False, webhook=False)`
  registered in stage 1. Names are `<owner>.<aggregate>.<past-tense verb>` (`billing.invoice.issued`),
  exported as module constants. The payload is a `TypedDict` — **ids and small scalars only**, JSON-safe,
  never model instances — so the same payload can go to the outbox and to webhooks unchanged.
- **Publishing an undeclared name raises.** Subscribing to an undeclared name is **dormant** with
  `dbx.W104`, because the declaring plugin may simply be absent.
- **Dispatch order:** name-specific handlers, then `"*"` handlers, de-duplicated, sorted
  deterministically by `(owner order, handler qualname)`. `handlers_for(name)` **excludes** wildcards,
  so "does anyone actually listen for this?" gets an honest answer.
- **Isolation:** each handler's exception is caught, logged with the owner and event, reported to
  error tracking, and returned as a `HandlerError` in the list `publish()` returns. One bad subscriber
  never breaks the publisher or the other subscribers.
- **Subscribers of disabled plugins are skipped** (§ 15).
- **Not durable, not retried, not replayable, not ordered across processes.** Say so in the module
  docstring. **Anything that must survive a crash** — a webhook delivery, an email, a sync to another
  system — is an `EventSpec(durable=True)`, and `emit()` then writes an outbox row in the *current*
  transaction as well as scheduling in-process dispatch. Outbox, relay and retries:
  [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md).
- **Never dispatch a fact that may roll back.** `emit()` schedules in-process dispatch with
  `transaction.on_commit(..., robust=True)`. `publish_now()` exists for tests and for code outside a
  transaction; called inside an atomic block it raises in `DEBUG` and tests (`connection.in_atomic_block`).

```python
# djx_billing/services.py
with transaction.atomic():
    invoice = Invoice.objects.create(...)
    emit(INVOICE_ISSUED, aggregate_id=invoice.pk, payload={"invoice_id": invoice.pk, "customer_id": c.pk})
    # durable spec → outbox row in THIS transaction; handlers run after COMMIT
```

**Enforced by.** `tests/core/test_events.py` — isolation (a raising handler, the next still runs, the
error is returned), wildcard dispatch, `handlers_for` excludes wildcards, undeclared publish raises,
`publish_now` inside `atomic` raises, rollback means no dispatch and no outbox row.
`tests/architecture/test_event_catalogue.py` — **both directions**: every declared event has an
`emit(<const>)` call site, and every emitted constant is declared; payload keys of each call site's
literal dict match the `TypedDict` (AST). Fails, not skips, when no event is found.

**Configurable, not hard-coded.** Subscriptions are by name; the catalogue is registered.

---

## 20. Capability switches — **Tier 2 · Core**

**What.** A small registry of **hierarchical kill switches keyed on the caller**, for integration
surfaces shared by several consumers: `Switch(key, parent=None, label, applies_to(principal) -> bool)`.
Evaluation returns `(allowed, reason_code, effective_path)`. Example: an external-agent connector has a
core master switch, and each plugin registers a branch under it for its own ability namespace.

**Why.** Gating the *endpoints* would take down unrelated consumers of the same endpoints (a public
feed, a partner push) silently; gating on the *caller* does not. And a hierarchy creates a failure
mode of its own: a branch that reads "active" while its parent is off, so nothing works and every
screen looks fine.

**Rules.**
- **Keyed on a property of the caller** (a column on the machine principal), never a name match — no
  consumer's name goes into code.
- **Unknown key → OFF; unregistered branch → INHERIT** (§ 5 explains the asymmetry).
- **Distinct refusal codes per level** (`connector_disabled` vs `connector_branch_disabled`); the
  outermost cause is reported first.
- **The admin screen shows own state and effective state** — "on, but not in effect: parent off".
- **A status endpoint stays readable while switched off**, so a consumer can tell "off" from "broken".
- Switches are not feature flags ([`CONFIGURATION.md`](CONFIGURATION.md) owns those): a flag rolls a
  feature out to people; a switch cuts a surface off for callers.

**Enforced by.** `test_switch_outer_cause_first`, `test_effective_state_reports_parent_off`,
`test_unregistered_branch_inherits`, `test_unknown_switch_is_off`.

**Configurable, not hard-coded.** Switch state is runtime data; the hierarchy is registered.

---

## 21. Shared base tables + 1:1 extension tables — **Tier 2 · Core**

**What.** When several apps need "the same kind of thing" — a task, a comment, a note, an attachment —
the platform or a kernel app owns **one base table with only the common columns** plus a `source_app`
discriminator (and an optional `source_ref`). An app that needs more fields adds **its own one-to-one
extension table** in its own migrations.

```python
# djx_billing/models.py
class InvoiceTask(models.Model):
    task = models.OneToOneField("core.Task", primary_key=True, on_delete=models.CASCADE,
                                related_name="+")          # no reverse accessor named after a plugin
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE)
    class Meta:
        db_table = "billing_invoice_tasks"
```

**Why.** The two alternatives both fail:
- **A `GenericForeignKey`** has no referential integrity, no database cascade, no efficient join, and
  keys on content-type ids that **differ between databases** — so exports, restores and fixtures
  silently point at the wrong type.
- **A wide shared table** that every plugin adds columns to makes the core's schema depend on which
  plugins are installed, which is the boundary this whole design exists to keep.

With the pattern, the shared schema never changes as apps join, app fields stay strongly-typed FKs,
and deleting the base row cascades correctly.

**Rules.**
- **The base table never gains a plugin column** and holds no plugin-specific logic.
- **A base table opts in** by registering in `extensible_bases`; a 1:1 onto an undeclared kernel table
  fails `test_fk_targets_respect_layers`. (Platform tables need no opt-in — the sanctioned FK.)
- **`related_name="+"`** — the core model gains no attribute named after a plugin, and core code
  cannot accidentally reach into one. (Django's deletion collector still follows hidden relations.)
- **`source_app` is validated** against installed labels at write, and host lists exclude rows whose
  `source_app` is disabled (§ 15).
- **Form extensions persist here** (§ 11): a plugin's extra fields on a host form are its extension
  row, saved in the host's transaction.
- **Exemption — the audit log.** An append-only audit row must outlive its target and is never joined
  for business logic, so a content-type + id reference **plus a denormalised label** is correct there
  ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)). That is the only sanctioned generic reference.

**Enforced by.** `tests/architecture/test_no_generic_foreign_keys.py` — no `GenericForeignKey` field
on any model except the audit log (an allowlist of one, pinned by its own test);
`test_extension_tables_are_one_to_one_primary_key`; `test_fk_targets_respect_layers` (§ 1).

**Configurable, not hard-coded.** Which bases are extensible is registered.

---

## 22. Project identity injection — **Tier 1 · Core**

**What.** Reusable apps (platform and kernel) never contain the product's identity. They read it
through `core.sdk.project()` → `ProjectIdentity(slug, name)`, whose values and derivations
(cookie names, compose project name, export envelope stamp) are specified in
[`CONFIGURATION.md`](CONFIGURATION.md).

**Why.** The moment a core module says the product's name, a domain, a dial code, a time zone or a
support address, it stops being copyable — and the leak happens through channels an import scan cannot
see: a route string in a layout, an icon name, an enum spelling, a leftover setting key in a seeder, a
header name or token prefix made of the product's initials.

**Rules.**
- **One accessor.** No module reads `settings.PROJECT_…` directly; `project()` is the seam and the
  thing a test can stub.
- **Branding is data, not identity** — a display name for the chrome comes from the branding row
  ([`CONFIGURATION.md`](CONFIGURATION.md)), not from `project().name`.
- **Stamps use the slug.** Exports, audit rows and webhooks stamp `project().slug` so an import can
  tell "our bundle" from a foreign one.

**Enforced by.** The vocabulary scan in § 24 bans, inside platform and kernel code, every installed
plugin name **and the running copy's own project slug and name** — so in a product copy the product's
name cannot creep into `core/`.

**Configurable, not hard-coded.** Everything; see CONFIGURATION.

---

## 23. Cross-stack generated artefacts — **Tier 2 · Core**

**What.** Every value the frontend must agree with the backend on is **generated from the backend's
registries**, committed, and checked. `manage.py export_contracts` writes
`frontend/src/generated/contracts.json`:

| Section | From | Consumed by |
|---|---|---|
| `permissions` | `registry.permissions` | typed `can()` codes |
| `nav.icon_keys` | every registered `icon_key` | the icon-map test |
| `components` | every registered `component` | the component-registry test |
| `events`, `error_codes`, `flags` | their registries | typed unions |
| `plugins` | `registry.plugins` | `registry.generated.ts` |
| `csp_origins` | `registry.csp_origins` | `proxy.ts` CSP builder |

`scripts/plugins.py generate` writes `frontend/src/plugins/registry.generated.ts` (pages) and
`components.generated.ts` (§ 11) from the same declarations.

**Why.** Five places holding the same table drift apart one at a time — a real incident: backend and
frontend each held their own copy of a per-period constant, and quotes disagreed with invoices. A
generated file with a "generated == generator" test cannot drift, because regenerating is the only way
to change it.

**Rules.**
- **Generated files are committed** (reviewable diffs, no build-order dependency for `next dev`) and
  carry a header saying so and naming the command.
- **Never hand-edited.** The test regenerates into a temp dir and diffs; a hand edit fails.
- **Stage-1 importable.** `export_contracts` must run without a database (§ 6).

**Enforced by.** `test_generated_contracts_are_current` (backend) and
`src/generated/contracts.test.ts` + `src/plugins/generated.test.ts` (frontend), each regenerating and
diffing. CI runs both.

**Configurable, not hard-coded.** Nothing to configure; everything is derived.

---

## 24. Boundary and architecture tests — **Tier 1 · Core**

**What.** The tests that make every boundary above go red. They extend `CORE_ARCHITECTURE_PLAN.md`
§ 6 and `BUILD_ORDER` 2.2/3.2. **Import scans alone are not enough:** in practice the coupling that
survives an import scan travels as strings, schema, tests and vocabulary.

**Rules for every test in this section.**
- **Derive the universe from the code** — `apps.get_app_configs()`, `apps.get_models()`,
  `get_resolver().url_patterns`, `celery_app.tasks`, the registry catalogue — never a hand-typed list.
- **Fail, never skip, on an empty universe.** `assert_universe(items, "plugin Celery tasks")` raises
  "enumeration found nothing — the test is looking in the wrong place". A real incident: a completeness
  test kept scanning a directory that a refactor had removed, and skipped silently on every run from
  then on.
- **Ship a positive control.** Each scanner runs against a checked-in offending fixture under
  `tests/architecture/fixtures/` and must report it. A scanner that finds nothing anywhere is broken.
- **Baselines are two-way ratchets**: new offences fail; entries that no longer offend fail too.
- **Messages name the fix**, not just the fault.

**The catalogue.**

| # | Test | Asserts |
|---|---|---|
| 1 | `test_core_imports_no_project_or_plugin` | AST: no platform/kernel module imports `project` or a plugin — including `importlib.import_module("<literal>")` |
| 2 | `test_layer_imports` | § 1 import rules, from declared layers |
| 3 | `test_plugins_import_only_sdk` | § 16 |
| 4 | `test_no_cross_plugin_imports` | no plugin imports another, except `TYPE_CHECKING`-guarded `.contracts` (§ 18); no plugin imports `project` |
| 5 | `test_core_vocabulary_scan` | **AST identifiers, attribute names and module file names** in platform/kernel code contain no plugin name, project slug or product name. Comments, docstrings and `str`/`bytes` literals are **excluded** — a text scan once flagged a key-derivation info constant, and "tidying" it would have made every encrypted value undecryptable. Its exception list is pinned **empty** by its own test |
| 6 | `test_core_strings_name_no_plugin_namespace` | the complement to 5: a string literal in core shaped like a namespaced code (`"<plugin>.…"`, `"<plugin>:…"`) fails — catches a plugin permission or event hard-coded in core without flagging free-form strings |
| 7 | `test_core_literals_are_registries` | § 2 |
| 8 | `test_core_fk_targets_core_tables` | every FK on a platform/kernel model targets a platform/kernel table — a copied core must create its schema alone |
| 9 | `test_fk_targets_respect_layers` | § 1 |
| 10 | `test_core_tests_import_no_plugin` | the core's own test suite imports no `project` or plugin — copy-and-run holds for tests too |
| 11 | `test_vocabulary_modules` · `test_vocab_imports_without_django` | § 6 |
| 12 | `test_no_import_swallow` | § 13 |
| 13 | `test_ready_touches_no_database` | § 4 |
| 14 | `test_registration_is_order_independent` | § 4 |
| 15 | `test_unknown_key_policies` | § 5 |
| 16 | `test_url_prefixes_unique_and_non_overlapping` | § 12 |
| 17 | `test_every_plugin_celery_task_is_gated` · `…_signal_receiver_is_gated` | § 15 |
| 18 | `test_disabled_plugin_every_surface` | § 15 |
| 19 | `test_sdk_surface_matches_snapshot` · `test_snapshot_change_bumps_version` | § 16 |
| 20 | `test_every_called_contract_has_exactly_one_provider` | § 18 |
| 21 | `test_event_catalogue` (both directions) | § 19 |
| 22 | `test_no_generic_foreign_keys` | § 21 |
| 23 | `test_generated_contracts_are_current` | § 23 |
| 24 | frontend `boundaries.test.ts` — imports | `src/core/` imports no `src/project/` or `src/plugins/` (existing plan) |
| 25 | frontend `boundaries.test.ts` — **route strings** | derive every plugin and project URL from `registry.generated.ts` and the `(project)` route directories; any quoted occurrence inside `src/core/**` fails. Import suites can be green while a core layout file holds two product URLs |
| 26 | frontend icon-key and component-name tests | § 10, § 11 |
| 27 | `test_composition_points_are_a_named_set` | only `config/settings.py`, `config/urls.py`, `config/celery.py` (backend) and `src/app/(plugins)/[plugin]/[[...slug]]/page.tsx` plus the `*.generated.ts` files (frontend) may reference both core and plugins/project. **Adding to the set is a decision, not a fix** |
| 28 | `test_generator_output_equals_reference_plugin` | § 26 |

**The two CI jobs that prove the headline property.** A test that mocks the absence of `project/`
proves the mock. These delete it:

1. **`core-only`** — copy the checkout, `rm -rf backend/project frontend/src/project backend/plugins/*
   frontend/src/plugins/*`, then run `manage.py check`, `makemigrations --check --dry-run`, `migrate` on
   an empty database, the core test suite, `npx tsc --noEmit` and `npm run lint`. **"Deleting
   `project/` leaves a working platform" (VISION principle 1) is this job going green.**
2. **`plugin-alone` matrix** — core plus **one** plugin at a time: `manage.py check` and that plugin's
   tests. Proves no plugin silently depends on another being installed.

Plus a fast in-process **core-only assembly** test for local runs: inside `registry.isolated()`, load
only platform + kernel vocab modules and assert a complete catalogue — the core's permission groups,
its two roles, default roles falling back to `staff`.

**Configurable, not hard-coded.** Banned-token lists and layer sets are derived; nothing is typed.

---

## 25. App-local change discipline — **Process**

**What.** A change for app *X* creates or edits files **only under *X*** (plus its docs and tests).
Anything cross-app goes through an existing seam — a registry, a service contract, an event.

**Rules.**
- **Seam first, consumer second, as separate changes.** If the seam does not exist, land the seam
  (in the owning app, with its test) as its own PR; then build the consumer against it. A PR that adds
  a seam and its only consumer at once hides whether the seam is general.
- **Editing another app's files is an architecture change**, and needs its owner's review — not a
  drive-by in a feature PR.
- **One app per commit.** Reviewable by one owner, revertable without collateral.
- **A core edit carries the `core-change` label** (existing `core-guard.yml`, BUILD_ORDER 4.3), and
  needs a reason that applies to more than one product (VISION principle 4).
- **A product's `project/` never patches core to make its feature work** — it asks for a seam
  upstream, and every product gets it.
- **When a reusable thing is born inside a plugin**, promote it to the core **stripped of the
  plugin's concepts** (colour maps become props, hard-coded keys become parameters) as its own
  change, then switch the plugin to it.

**Enforced by.**
- `CODEOWNERS` with one entry per app and per plugin root.
- A PR check (`.github/workflows/app-scope.yml`) that maps changed paths to apps and **requires the
  `cross-app` label** when a PR touches more than one; the label needs every touched owner's approval.
- `core-guard.yml` + `core_doctor.py` (existing plan).

**Configurable, not hard-coded.** Ownership is `CODEOWNERS` data.

---

## 26. The scaffolding generator and the reference plugin — **Process**

**What.** `scripts/plugins.py new <name>` (BUILD_ORDER 3.3) writes a complete, passing plugin:

```
plugins/<name>/
├── plugin.toml                     name, package, version 0.1.0, sdk_target = current SDK
├── README.md                       the plugin's own docs, in its own repo
└── djx_<name>/
    ├── apps.py                     label, layer = "plugin", ready() → registrar → vocab, wiring
    ├── vocab.py                    permission group, nav section + landing item, event specs
    ├── wiring.py                   api mount, (empty) subscribers and providers
    ├── contracts.py                empty Protocol module (§ 18)
    ├── models.py                   one model, base mixins, db_table = "<name>_…"
    ├── services.py · selectors.py · serializers.py · views.py (BaseViewSet) · urls.py
    ├── demo.py                     demo seeder through services
    ├── kb/overview.md              route-bound help page
    ├── migrations/0001_initial.py
    └── tests/                      smoke, conventions, route enforcement for its routes
└── frontend/
    ├── index.ts                    exports
    ├── pages/index.tsx             the landing page the nav item opens
    └── components/
```

**Why.** With forty-odd registries, a new plugin has many touch points, and the audience for a base
does not read documentation first — people, and the agents they drive, **imitate whatever they find**.
So the correct thing must be the easiest thing: generated, not described.

**Rules.**
- **The generator's output *is* the reference plugin.** `tests/fixtures/reference_plugin/` is
  committed; CI runs `plugins.py new example --out <tmp>` and diffs against it. The example never
  drifts from the generator, and a generator change shows up as a reviewable diff to the reference.
- **The reference plugin passes the full gate** — its own tests, the architecture tests with it
  installed, and `validate_plugins`. It is the acceptance test of BUILD_ORDER 3.4.
- **Generated code uses only `core.sdk`.** If the generator needs to import something else, the SDK
  is missing an export.
- **The landing page is included** (§ 10), so a freshly generated plugin shows up in the nav with a
  page that says where its screens go.

**Enforced by.** `test_generator_output_equals_reference_plugin`; the reference plugin in the
`plugin-alone` matrix (§ 24).

**Configurable, not hard-coded.** Templates live in `scripts/templates/plugin/`.

---

## 27. ⚠️ Conflicts with existing docs

Not edited here — each needs the owner's fix in its own file.

| # | File · § | Says | Should say | Why |
|---|---|---|---|---|
| 1 | `AUTH_BLUEPRINT.md` § 7.2 (last callout) | "**only `ImportError` is swallowed**; any other exception inside a present module propagates" | "Only a `ModuleNotFoundError` whose `exc.name` is the plugin's own package is swallowed (§ 13 of EXTENSIBILITY). Any other `ImportError` — including one raised *inside* a present module — propagates and fails boot." | Swallowing every `ImportError` is exactly the swallow that turns a typo into "plugin missing": permissions vanish, routes 404, and it reads as an RBAC bug |
| 2 | `CORE_ARCHITECTURE_PLAN.md` § 1 layer table, and `PLUGIN_DEVELOPMENT.md` § "Your entire integration surface" | plugin "may import Django, third-party, `core.*`"; the example writes `from core import registry` | plugin may import Django, third-party and **`core.sdk` only**; the example becomes `from core.sdk import registrar` + `r = registrar(self)` | An unversioned `core.*` import surface breaks plugins on every internal refactor (§ 16) |
| 3 | `CORE_ARCHITECTURE_PLAN.md` § 1 layer table (`project` row) | project "may import everything, including `core.*`" | project apps import `core.sdk`; core internals only through a shrinking baseline; plugins only through contracts/events | A project importing a plugin breaks when that plugin is disabled or removed; importing core internals makes every core update a product conflict |
| 4 | `CORE_ARCHITECTURE_PLAN.md` § 4 and `PLUGIN_DEVELOPMENT.md` rule 5 | first preference: "**A Django signal** B emits and A receives" | first preference: **a declared event on the core event bus** (§ 19); Django signals only for framework hooks, via `plugin_receiver` | Signals re-raise receiver errors into the sender, have no wildcard, are undeclared, and model signals skip bulk operations |
| 5 | `CORE_ARCHITECTURE_PLAN.md` § 4 option 2, `PLUGIN_DEVELOPMENT.md` rule 5 | "A contract in `core/contracts/` that B implements" | platform-wide contracts in `core/contracts/`; **plugin-to-plugin contracts in the provider's `contracts.py`, imported by the consumer under `TYPE_CHECKING` only** (§ 18) | A plugin contract in core puts the plugin's vocabulary in core (fails the vocabulary scan) and every new contract through the core's review queue — the bottleneck VISION property 2 removes |
| 6 | `CORE_ARCHITECTURE_PLAN.md` § 2 rule 4 | "A registry holds a key, a label, and a callable — never a plugin's model, schema or vocabulary" | "A registry holds **values the registrant supplies** — keys, labels, callables, `"app_label.Model"` strings resolved lazily. Core never *imports* a plugin's model, and never *names* one in a literal." | Several required registries (search sources, export specs, scopes, API resources) must reference a model; the rule's intent is "core never learns it", which lazy strings preserve |
| 7 | `CORE_ARCHITECTURE_PLAN.md` § 2 table, `BUILD_ORDER.md` 1.3 | eight registries (permissions, navigation, api_routes, events, jobs, search, settings, health) | the generic `Registry[T]` + the catalogue in § 7, built as consumers land; Phase 1 needs at least `roles`, `role_grants`, `default_roles`, `public_routes`, `error_codes`, `feature_flags` | Each missing registry is a literal the second product must edit core to extend (§ 2) |
| 8 | `AUTH_BLUEPRINT.md` § 9.2 (`core/routes.py`) | `PUBLIC_ROUTES: dict[str, str]` — a core-only constant | the core's entries become registrations into `registry.public_routes`; `dbx.E001`, `dbx.E007` and the route test read **the union** (§ 9) | A plugin's anonymous endpoint (a provider callback) otherwise needs a core edit or an inline `AllowAny` |
| 9 | `AUTH_BLUEPRINT.md` § 8.1 · `RBAC_DESIGN.md` § "Seeded roles" | "Products add their own [roles]" — no mechanism | roles, additive `role_grants` and `default_roles` registries, with a grant ledger so default grants apply once (§ 8) | Without additive grants a plugin must restate a role's list, silently reverting later grants; a re-syncing seeder wipes administrators' edits |
| 10 | `AUTH_BLUEPRINT.md` § 7.2 (`seal()` callout) | seal lazily on first read | keep, **and** raise `RegistryNotReady` on a read before `apps.ready`, and `RegistrationClosed` on a register after it (§ 4) | Lazy seal alone lets a `ready()` read — and cache — a half-built catalogue |
| 11 | `CORE_ARCHITECTURE_PLAN.md` § 5 (symlink `src/plugins/<name>` → `backend/plugins/<name>/frontend`) | the symlink is sufficient | the symlink target is **outside `frontend/`**, and Turbopack does not resolve files outside its root (`node_modules/next/dist/docs/01-app/03-api-reference/05-config/01-next-config-js/turbopack.md` § "Root directory"). It needs `turbopack.root` set to the repository root in `next.config.ts` (a **protected file**), verified by the example plugin (BUILD_ORDER 3.4–3.5) | Otherwise the first plugin page fails to resolve, and the reflex fix — copying the files — breaks one-repo-per-plugin |

**Not a conflict, stated so it is not "fixed" by mistake:** `DATA_MODEL.md` and `AUTH_BLUEPRINT.md`
§ 3.12 give `ActivityLog` a generic (content-type) target. § 21 bans generic FKs for *domain* links and
names the audit log as the one sanctioned exemption.

---

## Pending decisions (for the repository owner)

1. **How a plugin's Python package becomes importable, and where its own dependencies go.**
   (a) `sys.path` insertion of each plugin root at discovery — simple, but a plugin needing a
   third-party library must add it to the core's `backend/pyproject.toml` (protected; a core edit per
   plugin dependency). (b) A `uv` workspace with `members = ["plugins/*"]` set once in the core's
   `pyproject.toml` — each plugin declares its own dependencies in its own `pyproject.toml`, and
   `uv sync` resolves them together. **Recommendation: (b)** — it is the only option where a plugin
   team adds a dependency without a core PR. The same question applies to the frontend (npm
   workspaces vs the core's `package.json`, also protected).
2. **`turbopack.root` in `next.config.ts`** (conflict 11) — approve the protected-file edit, or move
   plugin frontends under `frontend/` (breaking one-repo-per-plugin).
3. **Soft-disable for platform-layer apps owned by the product** (`project/customers`) — the
   recommendation is **never**: platform means always on, which is what makes its FKs safe. Confirm.
4. **Whether `project/` apps must import only `core.sdk`** (conflict 3) — recommended with a
   shrinking baseline rather than a hard ban from day one.
5. **403 vs 404 for a disabled plugin's routes** — § 15 recommends 403 `plugin_disabled`; 404 hides
   existence but conflicts with the route-enforcement test's "404 is a failure" rule.
6. **`import-linter` as an additional dependency** — the AST tests in § 24 need none; import-linter
   gives nicer contract output and a CLI but adds a dev dependency (protected `pyproject.toml`).
   Recommendation: AST tests first, import-linter only if they prove hard to maintain.
7. **SDK starting version** — `1.0` at the first plugin (BUILD_ORDER 3.4), or `0.x` (no compatibility
   promise) until the second product (BUILD_ORDER 5.1). Recommendation: `0.x` until 5.1, because the
   first product is when the surface is learned.

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section.
>
> Stack facts checked on that date against the tree: Django `>=5.2,<6`, DRF, drf-spectacular,
> django-environ (`backend/pyproject.toml`); Next.js 16.3.4, React 19.2.8, ESLint 9 flat config
> (`frontend/package.json`, `frontend/eslint.config.mjs`); `@/*` → `./src/*` (`frontend/tsconfig.json`);
> Next 16 renamed Middleware to **Proxy** (`proxy.ts`) and Turbopack does not resolve files outside its
> root (both from `frontend/node_modules/next/dist/docs/`). Celery, `tomllib` (stdlib) and `uv`
> workspaces are assumed by this spec but not yet installed or configured.
