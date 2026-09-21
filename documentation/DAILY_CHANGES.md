# Daily Changes

**The running log. One entry per task, written in the same change as the code** — not afterwards
(`AGENTS.md` § 1, rule 8).

**Why in the same change:** a log written later is a log written from memory, and the part that gets
forgotten is always the same part — *why*, and *what was tried and rejected*. That is the only part
worth reading six months on.

Newest first.

### Format

```markdown
## YYYY-MM-DD

### <Short title>
**What:** what changed, in one or two lines.
**Why:** the reason. If it fixes something, what was broken and how it showed up.
**Files:** the paths that changed.
**Verification:** the commands run, and their real result — including failures.
**Notes:** anything the next person would otherwise have to rediscover. Optional.
```

---

## 2026-09-21

### No other codebase is named anywhere in this repository
**What:** Removed every reference to other projects, products and modules from the working tree —
147 hits across 17 files. The reasoning they supported was kept and rewritten to stand on its own;
only the attribution is gone. Added `AGENTS.md` rule **5a** so it cannot creep back. The project no
longer describes itself as a sibling of anything: `README.md`, `AGENTS.md`, `CLAUDE.md` and
`ONBOARDING.md` now call it a Django + Next.js base project, and the two "parity" tables in
`README.md` and `ROADMAP.md` became plain capability tables. Example plugin names in
`CORE_ARCHITECTURE_PLAN.md`, `PLUGIN_DEVELOPMENT.md`, `DATA_MODEL.md` and `RBAC_DESIGN.md` are now
the generic `billing`.
**Why:** The owner's call: this repository is public and is copied into other repositories, so its
history should not record which codebases its design was informed by. Rule 5 already forbade
client names and internal URLs; 5a extends the same reasoning to any other codebase, for the same
reason — a name committed here is inherited by every product copied from it, long after anyone
remembers why it was there.
**Files:** `README.md`, `AGENTS.md`, `CLAUDE.md`, `backend/core/views.py`,
`documentation/{INDEX,ONBOARDING,DAILY_CHANGES}.md`,
`documentation/adr/{0002-api-first-drf-not-django-templates,0006-one-agent-contract}.md`,
`documentation/planning/{AUTH_RND,ROADMAP,TESTING_STRATEGY,PLUGIN_DEVELOPMENT,CORE_ARCHITECTURE_PLAN}.md`,
`documentation/system-design/{AUTH_BLUEPRINT,DATA_MODEL,RBAC_DESIGN}.md`.
**Verification:** A case-insensitive sweep of the whole working tree — every file type, not only
markdown, excluding `.git/` and `node_modules/` — returns **zero matches** for any of the removed
names. Every relative markdown link in the repository resolves; the only reported miss is the
`NNNN-….md` placeholder inside `adr/0000-template.md`, which is intentional. One Python file
changed (a docstring), so the § 2 gate was run in full: `ruff check` passed, `ruff format --check`
reported 13 files already formatted, `manage.py check` found no issues, and
`makemigrations --check --dry-run` detected no changes.
**Notes:** **History was rewritten too.** The working-tree fix alone would have left the names fully
readable in the five earlier commits already on the remote, so after the cleanup landed, all six
commits were rewritten with `git filter-branch` (file contents *and* commit messages) and
force-pushed. Every commit hash changed — the initial scaffold is now `cac0491`. A full mirror plus
a working-tree archive were taken first, to `~/djangobasex-backup-20260921-055737/`. Verified by
cloning the remote fresh and sweeping every commit and every message: zero matches.
⚠️ **Two limits remain, and neither is fixable from here.** Any clone or fork taken before the
rewrite still holds the old objects, and the host may keep unreferenced objects reachable by their
SHA for some time. What is gone is gone from the repository; it is not recalled from anyone who
already had it.
The auth research this design came from was moved out of the repository entirely rather than
anonymised in place — its substance now lives in `system-design/AUTH_FAILURE_MODES.md`, written as
a failure catalogue that needs no sources, because a failure mode is true or false on its own and
citing where it was observed adds nothing a reader can use.

### Auth, authorization and RBAC — design spec
**What:** Added two documents under `documentation/system-design/`.
`AUTH_FAILURE_MODES.md` (282 lines) catalogues the seventeen ways auth and RBAC systems fail —
the forgotten gate, the permission that does not exist, Layer 1 without Layer 2, implicit
route→permission resolution, revocation that is not revocation, and so on — each with how it
presents and what defends against it, plus a design checklist and four rules for the tooling
itself. `AUTH_BLUEPRINT.md` (1,420 lines, 15 chapters) is the build spec: 18 decisions with their
reversal costs; the three-app split (`core`/`users`/`rbac`); all 14 tables with every column, type,
index, constraint and foreign key; the ER map and an `on_delete` rationale; the full file tree; the
authentication flows; the authorization engine; RBAC roles and seeding; the fail-closed machinery;
the API surface; the frontend contract; settings; migration order; the test plan; and a build
sequence mapping each `BUILD_ORDER` Phase 1 task to its chapters. Cross-linked from `INDEX.md`,
`RBAC_DESIGN.md` and `BUILD_ORDER.md` § Phase 1.
**Why:** So that starting to code means opening the blueprint and typing, rather than designing at
the keyboard. The failure catalogue is separate on purpose: a spec that only says *what* to build
gets argued with, and the arguments are always about cost. Naming the failure each decision buys
protection from is what makes it possible to reopen one on the merits later instead of guessing
what it was protecting against.
**Files:** `documentation/system-design/AUTH_FAILURE_MODES.md`,
`documentation/system-design/AUTH_BLUEPRINT.md`, `documentation/INDEX.md`,
`documentation/system-design/RBAC_DESIGN.md`, `documentation/planning/BUILD_ORDER.md`.
**Verification:** Docs only — no code changed, so the `AGENTS.md` § 2 gate does not apply. All
relative links in both documents resolve; the blueprint's 15 chapter anchors match their heading
text. Checked for contradictions against the docs they must agree with: base model classes and the
`visible_to()` scoping rule come from `DATA_MODEL.md` §§ 2 and 5; the error shape, the 404-not-403
rule for invisible rows, pagination and the machine-caller posture from `API_DESIGN.md`; the
URL→view→service→model layering and the new-app checklist from `DJANGO_STANDARDS.md`; the
four-concept model, grant-only rule and frontend posture from `RBAC_DESIGN.md`. No second way of
doing anything was introduced.
**Notes:** Two `BUILD_ORDER` 🚧 decisions (`0.1` custom user, `0.2` auth model) remain the owner's
and are **not** decided — they are written as stated assumptions A1–A5 with their reversal costs,
and Chapter 13 says what has to restart if either flips. Chapter 9 is the part that makes this
stronger rather than merely complete: default-deny on the base viewset, so omitting a gate denies
instead of serves; system checks `dbx.E001`–`E004` that fail `manage.py check` — already in the § 2
gate — when a route declares no permission or names a code absent from the catalog; the
route-enforcement test; and a permissions doctor. Each turns a discipline into a mechanism, because
discipline does not survive scale, turnover or a deadline. Two deliberate trades are written down
rather than left to be discovered: session liveness is cached 60s, so revocation takes effect
within a minute rather than instantly; and the superuser bypass is kept but audited on every use,
because a bypass held by the people most likely to test a feature hides breakage from the people
most able to fix it.

### Build order resequenced — authentication, authorization, RBAC first
**What:** Reordered `BUILD_ORDER.md` on the repository owner's instruction: the platform now leads
and the tooling follows. The two 🚧 DECISION items became **Phase 0** (they gate the first
migration, so they cannot follow the auth work that writes it); authentication → authorization →
RBAC → Users CRUD → `core`/`project` split became **Phase 1**; the old Phase 0 (test stack,
architecture tests, CI) became **Phase 2**; plugins, reusability and the second-product test shifted
to Phases 3–5. Split the old single "RBAC" task into **1.2 Authorization** (the `Permission` models,
the code-declared catalog, `HasPermission` for Layer 1 and `visible_to()` for Layer 2) and **1.4
RBAC** (`Role`/`UserRole`, the seeded system roles, `/me` permission codes, the roles screen last),
which is the owner's stated authorization-then-RBAC order and also `RBAC_DESIGN.md`'s own build
order. Added a new "The order, and why it is this one" section recording the decision, its date and
its cost.
**Why:** Asked for by the repository owner. The previous order put enforcement tooling first on the
argument that no convention is real until something can fail a build; the owner's call is that the
platform is worth more first. Both are defensible and the decision is the owner's — but reordering
silently would leave the next reader unable to tell a deliberate sequence from an accidental one,
which is why the reason is now in the file.
**Files:** `documentation/planning/BUILD_ORDER.md`, `documentation/system-design/DATA_MODEL.md`.
**Verification:** Docs only — no code changed, so the `AGENTS.md` § 2 gate does not apply. Checked
every cross-reference to the file: `DATA_MODEL.md` § D1 said "`BUILD_ORDER` task 1.1" for the custom
user model and now says 0.1. The "Phase 0" mentions in `README.md`, `NEW_PROJECT.md`,
`UPGRADING.md` and `PLUGIN_DEVELOPMENT.md` refer to `CORE_ARCHITECTURE_PLAN.md`'s own phases, not
this file's, and were correctly left alone. `AGENTS.md` § 0 (start at the lowest unfinished task;
two tasks are 🚧) and `INDEX.md` still hold without edits. Relative links in the rewritten file
resolve.
**Notes:** The cost of the trade is written into the file rather than resolved quietly. Several
Phase 1 acceptance criteria say "and has tests" or name `test_route_enforcement.py`, and neither can
be satisfied until **2.1** installs `pytest`. The file recommends pulling 2.1 forward on its own —
it is a dependency-and-config task, not a feature — while leaving the choice with the owner. Already
tracked as `TECH_DEBT` **DB-5**/**DB-6**; no new debt row was added. Earlier entries in this log
that cite old task numbers (the 2026-09-16 entry's "task 1.1") were left as written — this is a
historical log, not a current-state doc.

## 2026-09-16

### System design completed — vision, data model, RBAC, API, security
**What:** Added `VISION.md` (what the project is for, the three properties in priority order, the
design principles, success criteria, and explicit non-goals) and four system-design documents:
`DATA_MODEL.md`, `RBAC_DESIGN.md`, `API_DESIGN.md`, `SECURITY.md`. Wired all five into `INDEX.md`,
`AGENTS.md` § 6, `README.md` and `BUILD_ORDER.md`.
**Why:** The docs covered *how to work* (standards, contract) and *what to build* (backlog) but not
*what the system is*. Those four are the parts that are brutal to retrofit: the schema, the
authorization model and the API contract all get fixed by the first module that touches them.
**Files:** `documentation/VISION.md`,
`documentation/system-design/{DATA_MODEL,RBAC_DESIGN,API_DESIGN,SECURITY}.md`,
`documentation/INDEX.md`, `documentation/planning/BUILD_ORDER.md`, `AGENTS.md`, `README.md`.
**Verification:** Docs only. All relative links across the repository resolve. Existing settings
claims re-checked against `backend/config/settings.py`.
**Notes:** `DATA_MODEL.md` § 1 raises **five decisions that must be ADRs before the first
migration** — custom `User`, primary key type, multi-tenancy, soft delete, change history. D1 and D3
are the expensive ones: `AUTH_USER_MODEL` cannot be changed cheaply once referenced, and retrofitting
tenancy is a rewrite rather than a migration. `BUILD_ORDER.md` task 1.1 now points at all five.
The recommendation on D3 is deliberately "no organisation model, but scope through
`visible_to()` from module one" — so adding tenancy later is one method per model, not every view.

### README rewritten, and an executable backlog added
**What:** Rewrote `README.md` against the current state — Documentation, Architecture, Project
Status, Using This As A Core and Contributing sections, an updated folder tree and table of
contents. Added `documentation/planning/BUILD_ORDER.md`: numbered tasks in dependency order, each
with acceptance criteria, across four phases. Wired it into `INDEX.md` and `AGENTS.md` §§ 0 and 6.
**Why:** The README was still the initial scaffold's and described none of the architecture, so the
repository's entry point understated it. And the plans said *what* to build without saying what to
do first or how to know a task was finished — which is the difference between a document an agent
can read and one it can execute.
**Files:** `README.md`, `documentation/planning/BUILD_ORDER.md`, `documentation/INDEX.md`,
`AGENTS.md`.
**Verification:** Docs only. All relative links across `README.md`, `AGENTS.md`, `CLAUDE.md` and
`documentation/**` resolve; README's table-of-contents anchors all match real headings. Audited every
doc for wrong-stack leakage (FastAPI, Alembic, Laravel, Composer).
**Notes:** `BUILD_ORDER.md` marks two tasks 🚧 DECISION — the custom `User` model and the auth model.
`AGENTS.md` § 0 now tells an agent arriving with no task to start at the lowest unfinished item and
to **ask** rather than answer a 🚧 by starting to code. Both are ordered first because both are
settled by accident otherwise, and `AUTH_USER_MODEL` in particular must be fixed before any
migration references it.

### Reusability, plugin and testing docs
**What:** Added `NEW_PROJECT.md` (clone-and-re-origin, the rename checklist, the decisions to settle
first), `UPGRADING.md` (how a product takes a core update, and what a conflict tells you),
`planning/PLUGIN_DEVELOPMENT.md` (the plugin contract, five enforced rules, the outside-contributor
sandbox branch), `planning/AUTH_RND.md` (session vs JWT — resolves DB-1) and
`planning/TESTING_STRATEGY.md` (the four tests to write first, coverage floors, CI shape).
**Why:** `CORE_ARCHITECTURE_PLAN.md` describes the design; these describe how a person actually uses
it — copying the boilerplate, taking updates, owning a plugin — plus the two gaps that block real
work: the undecided auth model and the absent test suite.
**Files:** `documentation/NEW_PROJECT.md`, `documentation/UPGRADING.md`,
`documentation/planning/{PLUGIN_DEVELOPMENT,AUTH_RND,TESTING_STRATEGY}.md`, `documentation/INDEX.md`.
**Verification:** Docs only. Relative links checked; none broken. Claims about the reference projects
were taken from their trees, read in the previous session.
**Notes:** `AUTH_RND.md` recommends JWT in `httpOnly` cookies — what both reference projects
converged on — but explicitly says staying with sessions is a respectable end state. It is a
recommendation, not a decision; the decision is still the owner's and still open.

## 2026-09-15

### Agent contract and documentation structure
**What:** Added the root `AGENTS.md` operating contract and `CLAUDE.md` entry point, plus this
`documentation/` tree — INDEX, ADR register with six records, architecture, Django and Next.js
standards, migrations, deployment, roadmap and tech debt.
**Why:** DjangoBaseX is a boilerplate, so its conventions are inherited by every product copied from
it. Nothing recorded them, and AI agents working in the repo had no contract at all. The structure
was adapted from an earlier core on a different stack and rewritten against this one — the original
was FastAPI/Alembic and its instructions would not have applied here.
**Files:** `AGENTS.md`, `CLAUDE.md`, `documentation/**`.
**Verification:** Documentation only — no code changed, so the § 2 gate was not applicable. Every
factual claim was read out of `backend/config/settings.py`, `backend/pyproject.toml` and
`frontend/package.json` rather than assumed.
**Notes:** The auth model is deliberately left open rather than invented (`TECH_DEBT` DB-1) — it is
the repository owner's call and settling it by accident is the failure to avoid.

### Core architecture plan — plugins and reusability
**What:** Added `documentation/planning/CORE_ARCHITECTURE_PLAN.md`: the design for a three-layer
core (`core/` · `project/` · `plugins/`), a boot-time registry seam, git-submodule plugins holding
both their backend and frontend halves, and the checks that enforce every boundary.
**Why:** DjangoBaseX should be copyable into a new project and extended by independent teams in their
own repos. The design combines a reusability mechanism (core/project split, SHA manifest,
clone-and-re-origin) with a parallel-team mechanism (one repo per plugin, prefixed namespaces, no
cross-plugin imports).
**Files:** `documentation/planning/CORE_ARCHITECTURE_PLAN.md`.
**Verification:** Plan only — no code written. Every mechanism described was read out of a working
implementation rather than recalled. Relative links checked; none broken.
**Notes:** Decisions taken: seams before features · plugins hold both halves · git submodules.
One deliberate divergence from the usual arrangement — plugin docs live in the plugin repo, not
centrally, because separate teams should not route doc changes through the core's review queue.

### Commit attribution decided
**What:** `AGENTS.md` § 4 now forbids AI attribution in commit messages, replacing the note that
left it open.
**Why:** Asked and answered by the repository owner. A permanent public history should not carry
trailers naming a tool that will outlive its relevance.
