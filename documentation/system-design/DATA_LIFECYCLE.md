# Data Lifecycle

**How a row is born, attributed, changed, recorded, hidden, retained and finally destroyed — the base
models, the audit engine, state history, retention, soft delete, provenance, the data-modelling
conventions every model follows, and the object-scoping rules that decide who may see any of it.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

---

## Scope — read first

**Owns:** the base model set and the actor context that stamps it · optimistic locking · the
activity/audit engine (row shape, write path, auto-capture and diffs, provenance of the write,
vocabulary, read side) · state-transition history · the retention engine · soft delete and the
recycle bin · record provenance (`created_via`, `source_ref`) · the data-modelling conventions
(declared vs reported, event date vs recorded-at, durable identity, inclusive dates, length caps) ·
invariants in the model **and** the database · the rule for data migrations over authored content ·
the extensions to RBAC Layer 2 object scoping · the optional tenant safety net · delegation grants.

**Does not own:**

| Topic | Owner |
|---|---|
| The five 🚧 schema decisions (custom user, PK type, tenancy, soft delete, history) | [`DATA_MODEL.md`](DATA_MODEL.md) § 1 — this file extends, never re-decides |
| Migration routine, three-step non-null fields, merge conflicts | [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md) |
| Auth tables, the security event list, the superuser bypass audit | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) §§ 3, 9.5 |
| Registry mechanics (shape, `ready()`, duplicates raise) | `EXTENSIBILITY.md` |
| Settings registry, currency/locale/timezone settings, lookups | `CONFIGURATION.md` |
| List pipeline, error envelope and code catalogue, files/storage | `API_PLATFORM.md` |
| Jobs, schedules, outbox, reconcilers, locks | `JOBS_AND_INTEGRATIONS.md` |
| The one scrubber, metrics, request id | `OBSERVABILITY.md` |
| Money, numbering, state-machine helper, bulk actions, import/export, findings queue | [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) |
| The organisations / tenancy / white-label **module** | `REUSABLE_MODULES.md` |
| DataTable, `?highlight=` rendering, toasts, the audit screen UI | `FRONTEND_PLATFORM.md` |

---

## 0. The rules in one screen

1. **One base model set lives in `core`, and every concrete model inherits it.** Copy-pasting a base
   per app is how columns drift. → § 1
2. **Actor attribution comes from one `ActorContext` contextvar**, bound by middleware, the command
   base class and the task base class — never `threading.local`, never "whoever is resolvable". → § 2
3. **`updated_by` is overwritten only when a human actor is known.** Machine work records actor
   `NULL` with a `system:<task>` label in the audit row. → § 2
4. **Optimistic locking is opt-in per model and returns `409`** — never a silent last-write-wins on
   an admin form. → § 3
5. **The audit log is append-only by structure** — no write routes, model guards, and a database
   trigger. A permission someone could widen is not immutability. → § 4.7
6. **An audit write never raises into the action it observes**, and always runs in its own savepoint.
   → § 4.2
7. **Security events survive the rollback of the request that produced them**; model-change events
   do not. → § 4.2
8. **The audit target is a snapshot (`type`, `id`, `repr`) with no foreign key.** History must not
   cascade, block a delete, or turn into "unknown". → § 4.1
9. **Secrets are masked at any depth of a diff**, by the one shared scrubber. → § 4.3
10. **Nothing happened → nothing recorded; one run → one feed row.** → § 4.8
11. **Audit where a human reads a secret, never on every machine read.** → § 4.8
12. **Every write path records a state change** — a model mixin, not a service convention. Never
    compute a duration from `updated_at`. → § 5
13. **Retention is one engine with registered policies.** Age then cap, batched, committed per batch,
    floors so `0` cannot wipe a table, evidence tables opt-in and never capped. → § 6
14. **A package default never decides retention.** Every third-party cleaner is disabled or pointed at
    the engine. → § 6.4
15. **Soft-deletable models never use `unique=True`** — uniqueness is a partial constraint
    `WHERE deleted_at IS NULL`, and restore checks conflicts. → § 7
16. **A request string never becomes a class.** Recycle-bin types resolve through an allow-listed
    registry key. → § 7.4
17. **Provenance is set from the authenticated principal, never from input**, and `NULL` means
    *unknown* — never backfilled as "manual". → § 8
18. **Every invariant has a `clean()` validator *and* a database constraint**, and a test proves the
    database rejects a `QuerySet.update()` bypass. → § 10
19. **A data migration may rewrite system content, never operator-authored content.** → § 11
20. **Every listable model is registered for scoping, reads *and* writes are narrowed, and a scope
    resolver never returns a value meaning "all".** → § 12

---

## 1. The base model set — **Tier 1 · Core**

**What.** One module, `core/models/base.py`, holding the abstract bases every model in core, project
and plugins inherits. It extends [`DATA_MODEL.md`](DATA_MODEL.md) § 2 rather than replacing it.

**Why.** A studied codebase copy-pasted its UUID-and-timestamps base into five apps; another had 189
model files each redeclaring `id`, `created_at` and `updated_at`, with soft delete applied ad hoc in
23 of them and no lost-update protection anywhere. The columns drifted, and every cross-cutting
feature (audit, retention, export) had to special-case the drift.

**Rules.**

- **One base, from the first model.** Not "once a second model needs it" — by the second model the
  first has already shipped a migration with its own columns.
- **The PK type is `DATA_MODEL.md` D2's decision**, made once in the base. The base exposes
  `core.ids.new_id()` as the only id generator, so switching a *future* model's strategy is one
  function. If D2 chooses UUIDv7: Python 3.12/3.13 has no `uuid.uuid7()` (it arrives in 3.14), so the
  generator wraps a vetted library behind that one function — never scattered `uuid4()` defaults,
  which fragment B-tree indexes on every insert.
- **Timestamps are always timezone-aware UTC.** `USE_TZ = True`. Naive `datetime.utcnow()` /
  `datetime.now()` are banned by Ruff's `DTZ` rules (a studied codebase had a tz-aware helper and 37
  files still calling the naive one). Enabling `DTZ` edits `backend/pyproject.toml`, a protected
  file — the owner approves it once.
- **`created_at` uses `default=timezone.now, editable=False`, not `auto_now_add=True`.**
  `auto_now_add` overwrites any value supplied, including in `bulk_create()`, so an import that must
  preserve original timestamps (§ 6 of [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md)) cannot. Only
  import mode may pass an explicit value; everything else gets `now`.
- **`updated_at` does not move on `QuerySet.update()`.** `auto_now` fires in `save()` only. A service
  that bulk-updates sets `updated_at=Now()` explicitly; a source-scan test flags `.update(` on
  `TimeStampedModel` subclasses whose kwargs omit it (ratchet allow-list, may only shrink).
- **Every field carries `db_comment=`** (Django 4.2+). A DBA, a restore operator or a BI tool reading
  the schema without the code then knows what `is_customised` means.
- **Every index and constraint is named explicitly** (`name="crm_contact_email_live_uq"`). Django's
  generated names change when fields are reordered, which produces a migration that drops and
  recreates a hot index for no reason. Names are ≤ 30 characters (Django system check `models.E034`).
- **When the database is right about an index the model forgot, fix the model** — never let
  `makemigrations` "helpfully" drop a deliberate index inside a migration named after something else.

**Django + Next shape.**

```python
# core/models/base.py  (sketch — the stamping lives in § 2)
class BaseModel(models.Model):
    id = models.BigAutoField(primary_key=True)          # or UUIDField(default=new_id) per D2
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True,
                                      db_comment="When the row was recorded (UTC)")
    updated_at = models.DateTimeField(auto_now=True, db_comment="Last write by anyone (UTC)")

    class Meta:
        abstract = True

class AuditedModel(BaseModel):                           # adds created_by / updated_by, § 2
    ...
```

The full set: `BaseModel` · `AuditedModel` · `VersionedMixin` (§ 3) · `SoftDeletableModel` (§ 7) ·
`StatefulMixin` (§ 5) · `ProvenanceMixin` (§ 8). Mixins compose; none of them imports a plugin.

**Enforced by.**

- `tests/architecture/test_base_models.py::test_every_concrete_model_inherits_the_base` — iterates
  `apps.get_models()`, excludes Django/third-party apps by an explicit allow-list, fails on any project
  or plugin model that does not inherit `BaseModel`. **Must fail on an empty universe** (if it finds
  zero models to check, it fails rather than passes).
- `test_every_field_has_a_db_comment` and `test_every_index_and_constraint_is_named` — same walk.
- Ruff `DTZ` in CI.

**Configurable, not hard-coded.** `CORE_ID_STRATEGY` (`bigint` · `uuid7`) is read by `new_id()` only;
changing it affects new models, never existing tables.

---

## 2. The actor context — **Tier 1 · Core**

**What.** One request/task-scoped `contextvars.ContextVar[ActorContext]` that answers "who, as what,
from where" for every consumer: base-model stamping, the audit log, state transitions, provenance.

**Why.** Three failures seen across the studied codebases: (1) a documented base sample set
`updated_by = auth()->id()` unconditionally, which would have written `NULL` over real attribution on
every save from a job, seeder or scheduler; (2) CLI writes left empty actors, so a change made from a
shell was unattributable; (3) a thread-local request binding, which misattributes actors under ASGI
and async code.

**Rules.**

- **`contextvars`, never `threading.local`.** Django runs sync views inside `sync_to_async` threads
  under ASGI; `asgiref` propagates contextvars correctly and does not propagate thread-locals.
- **Set and reset in the same place, in a `finally`, with the token** —
  `token = var.set(ctx) … var.reset(token)`. Never set it inside a view; never rely on "the next
  request overwrites it". A studied core leaked a per-request context twice because it was reset in a
  different task context than the one that set it.
- **Three binders, one shape:** the request middleware (after authentication), the
  `AuditedCommand` base class for management commands, and the Celery task base class (`__call__`).
  A task receives its actor **explicitly in its arguments** from the enqueuing code — it never infers
  one.
- **The actor kinds are closed:** `user` · `machine` (an API consumer) · `system` (a scheduled job,
  migration, boot) · `anonymous`. `system` carries a label (`system:retention.enforce`), never a user.
- **`updated_by` means "last known *human* editor".** It is overwritten only when
  `ctx.kind == "user"`. A machine or system save leaves it unchanged and moves `updated_at` — the
  audit row (§ 4) says which machine did it. This is stated in the column's `db_comment`, because the
  name alone suggests otherwise.
- **`created_by` is set once, on insert, and only from a human actor.** A machine-created row has
  `created_by = NULL` and a `created_via` (§ 8).
- **Impersonation is part of the context**, not a separate lookup: `impersonator_id` and label ride
  in `ActorContext`, so every write while impersonating carries both.
- **No per-save schema introspection.** A studied base checked `hasColumn()` on every save; the mixin
  knows its own fields.

**Django + Next shape.**

```python
# core/actor.py
@dataclass(frozen=True, slots=True)
class ActorContext:
    kind: Literal["user", "machine", "system", "anonymous"]
    user_id: int | None = None
    label: str = ""                    # "a.person@example.com" · "system:retention.enforce"
    consumer_id: int | None = None     # machine principal (API_PLATFORM.md)
    impersonator_id: int | None = None
    impersonator_label: str = ""
    source: str = "web"                # web · api · command · seeder · job · import · system
    via: str = ""                      # inline · form · api · bulk · import
    request_id: str = ""

current_actor: ContextVar[ActorContext] = ContextVar("current_actor", default=SYSTEM_UNKNOWN)
```

`SYSTEM_UNKNOWN` is `kind="system", label="system:unbound"` — so a write with no binder is still
attributable to *something*, and a test can assert no production write path hits it.

**Enforced by.**

- `test_actor_context.py::test_middleware_resets_the_context_after_the_response` (including when the
  view raises).
- `test_a_task_save_does_not_overwrite_updated_by` — a human edits, a task re-saves, `updated_by` is
  still the human.
- `test_no_write_path_runs_unbound` — the suite runs with a flag that makes `SYSTEM_UNKNOWN` raise; any
  test hitting it names the unbound path.
- A source scan forbidding `threading.local` in `core/` and plugins.

**Configurable, not hard-coded.** Nothing — this is mechanism.

---

## 3. Optimistic locking — **Tier 1 · Core**

**What.** `VersionedMixin` adds `version = PositiveIntegerField(default=1)`; updates are conditional on
the version the client last saw.

**Why.** Without it, two admins editing the same record in two tabs silently lose one edit, and the
audit trail shows two "updated" rows as though both stuck. One studied codebase relied on hundreds of
`FOR UPDATE` call sites, which protect a transaction but not a *form* held open for ten minutes.

**Rules.**

- **Opt-in per model.** Human-edited configuration and documents want it; append-only and
  machine-written tables do not.
- **The client supplies the version it read** — an `If-Match: W/"<version>"` header *or* a `version`
  field in the body. Retrieve responses carry `ETag: W/"<version>"` and the field.
- **Mismatch → `409` with code `stale_version`**, the current version and, when the caller may read
  it, the current representation, so the UI can offer "review their change". `409` rather than `412`:
  [`API_DESIGN.md`](API_DESIGN.md) already defines `409` as a real state clash, and one status for one
  situation means one client handler.
- **The check is in the `UPDATE`, not a read-then-write.**
  `filter(pk=pk, version=v).update(..., version=F("version") + 1)` returning `0` rows is the conflict.
  A read-compare-save has a race window exactly as wide as the bug it prevents.
- **A missing version on a model that requires one → `428`** (`precondition_required`), per model via
  `VERSION_REQUIRED = True`. Default is lenient so machine clients are not broken by adding the mixin.
- **Bulk and state-transition services bump `version` too** — otherwise a form saved after a status
  change silently reverts the status.

**Django + Next shape.** `core.api.mixins.VersionedUpdateMixin` on the viewset reads the header/field
and calls `services.save_versioned(obj, changes, expected_version)`. Next: the form hook keeps the
`ETag` from the load and sends it back; on `stale_version` it shows a non-dismissable "someone else
changed this" panel (`FRONTEND_PLATFORM.md` owns the component).

**Enforced by.** `test_versioned.py::test_concurrent_saves_one_wins_one_409s` (two clients, same
version) and `test_a_status_transition_bumps_version`.

**Configurable, not hard-coded.** `VERSION_REQUIRED` per model; nothing global.

---

## 4. The activity / audit engine — **Tier 1 · Core**

**What.** One append-only table, `core_activity_log`, with one writer (`core.audit.record()`), an
opt-in automatic capture engine for model changes, and a structurally read-only read side. It extends
[`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 3.12 (which stays authoritative for the list of security
events that must be logged).

**Why.** "Who granted this user Admin, and when?" was unanswerable in one studied codebase. In others:
plugins flooded the feed with "Updated X" rows that said nothing about what changed; password-reset
takeovers and 2FA disablement left no trace; a change made from a shell had no actor; four overlapping
audit schemas grew in one product because nothing in core offered one good one.

### 4.1 The row

| Column | Type | Notes |
|---|---|---|
| `id` | `BigAutoField` | **The sort key.** Rows written in one transaction share a timestamp; `id` does not tie |
| `created_at` | `DateTimeField` | Indexed for retention and range filters |
| `channel` | `CharField(32)` | Registered: `auth` · `security` · `settings` · `rbac` · `data` · per-plugin. A security screen reads `auth`+`security`+`settings` |
| `action` | `CharField(64)` | Registered verb, `module.entity.verb` (`rbac.role.updated`, `crm.deal.won`) |
| `event` | `CharField(24)` | `created` · `updated` · `deleted` · `restored` · `status_changed` · `roles_changed` · `custom` · `run_summary` |
| `description` | `CharField(255)` | Human sentence, "<title> — <event>" |
| `actor_id` | FK-shaped, **`db_constraint=False`, `on_delete=DO_NOTHING`** | See § 4.1 note and ⚠️ C3 |
| `actor_kind` · `actor_label` | `CharField` | Snapshot. Survives the actor's deletion *and* renames |
| `consumer_id` | same shape | The machine principal, when there is one |
| `impersonator_id` · `impersonator_label` | same shape | The real operator |
| `target_type` | `CharField(100)` | `"app_label.model_name"`, **no FK to `django_content_type`** |
| `target_id` | `CharField(64)` | Holds an int **or** a UUID |
| `target_repr` | `CharField(255)` | `str(obj)` at write time |
| `changes` | `JSONField` | `{field: {"old": …, "new": …, "old_label": …, "new_label": …}}`, § 4.3 |
| `meta` | `JSONField` | Anything else, scrubbed |
| `batch_id` | `UUIDField(null)` | One bulk action, one import, one command run — reads as one thing |
| `source` · `via` | `CharField` | From `ActorContext`, § 4.4 |
| `origin_os_user` · `origin_host` · `origin_command` | `CharField` | CLI provenance, § 4.4 |
| `request_id` · `method` · `path` · `ip` · `user_agent` | | `path` without the query string; `ip` from the trusted-proxy helper (`AUTH_BLUEPRINT.md` § 17.3); UA truncated |
| `tenant_id` | nullable | Only if `DATA_MODEL.md` D3 introduces tenancy |

Indexes (named): `(target_type, target_id, -id)` for a record's history · `(actor_id, -id)` ·
`(channel, -id)` · `(action)` · `(batch_id)` · `(created_at)`.

> **Why no foreign keys on an evidence table.** A generic FK to `django_content_type` with
> `SET_NULL` issues an `UPDATE` against the audit table when a content type is removed (a plugin
> uninstalled, `remove_stale_contenttypes` run) — which a database-level immutability trigger must
> refuse, and which erases the type of every affected row if it doesn't. An actor FK with `SET_NULL`
> does the same on a user hard-delete and turns "who did this" into "unknown" for exactly the accounts
> that were removed. Snapshots plus `db_constraint=False` keep the id for joining while the label
> guarantees the row still reads correctly. A GenericForeignKey was never going to cascade anyway —
> it just looked like integrity.

### 4.2 The write path

**Rules.**

- **One writer: `core.audit.record(action, target=None, *, changes=None, meta=None, description=None,
  batch_id=None, independent=False)`.** Nothing else inserts into the table; a source scan proves it.
- **It never raises.** It catches everything, logs through the scrubbed logger and increments
  `audit_write_failures_total`. An audit failure must not break the action it observes — and a
  failure that nobody can see is also unacceptable, hence the metric.
- **It always writes inside its own savepoint** (`with transaction.atomic():` *inside* the `try`).
  In Django, catching a database error inside an `atomic` block without a savepoint leaves the outer
  transaction unusable (`TransactionManagementError` on the next query) — so a bare `try/except` around
  an insert is not "never breaks the request"; it moves the break to the next line.
- **Two modes, chosen by the event, not the caller's mood:**

  | Mode | Used for | Behaviour |
  |---|---|---|
  | **transactional** (default) | model changes, business events | Same transaction as the change. A rolled-back change leaves **no** row claiming it happened |
  | **independent** | `auth.login_failed`, `auth.token_reuse_detected`, denied re-auth, rate-limit lockouts, `security.*` | Written on a **separate database connection** (a second `DATABASES` alias pointing at the same database), so it commits even though the request that produced it rolls back |

  **Decision recorded here:** failed-login and other security rows **survive rollback**. The request
  that triggers them usually fails by design; an audit row that vanishes with it records nothing about
  the attack. The alias is `DATABASES["audit"]`, configured from the same `DATABASE_URL`; on SQLite a
  second connection can hit `database is locked` while the first holds the write lock, so development
  on SQLite falls back to transactional mode with a logged warning (⚠️ C10).
- **Side effects of an audited change (webhooks, notifications) are emitted `on_commit`**, never from
  inside `record()`.
- **Every row is enriched centrally** from `ActorContext`: actor, impersonator, consumer, source, via,
  request metadata. Callers pass only what they know that the context does not.
- **Superuser bypass rows** (`authz.superuser_bypass`, `AUTH_BLUEPRINT.md` § 9.5) go through the same
  writer, independent mode.

### 4.3 Automatic capture and diffs

**What.** An opt-in engine that turns model saves and deletes into audit rows with field-level diffs,
so a plugin does not hand-write "Updated X" for every model.

**Rules.**

- **Opt-in by allow-list, never global.** A global ORM hook buries a role grant under ten thousand
  `last_seen_at` touches. An app opts in with `registry.audit.capture_app("crm")` and may exclude
  models; a model refines with an inner `AuditMeta` (`fields` · `exclude` · `secret_fields` ·
  `preference_fields` · `state_fields` · `title_field` · `show_route` · `index_route`). Core opts in
  users, rbac, settings, flags, webhook endpoints, credentials and grants. **High-volume tables
  (deliveries, request logs, login attempts) are deliberately not captured** — they are their own
  record.
- **Opt-in is also what prevents recursion**: `core_activity_log` is never capturable.
- **Snapshot on load, diff on save, no extra query.** For models we own, the mixin overrides
  `from_db()` to keep the loaded values (the approach Django's documentation recommends); for models
  we do not own (third-party) a `post_init` receiver does it, registered only for captured models.
  **Deferred fields are skipped** — reading a field deferred by `.only()` inside a snapshot issues one
  query per instance, which turns a 1,000-row list into 1,001 queries.
- **Diff rendering stores machine values and display labels side by side.** A foreign key records the
  id *and* `str(related)` at the time; a choice field records the value *and* its label; dates and
  datetimes are stored as ISO-8601 (UTC for instants) and **formatted by the viewer's locale at read
  time**, never baked into the log — locale is a setting from day one (`CONFIGURATION.md`).
- **`JSONField` is diffed per key**, recursively, with **scalar coercion** so `"16384"` → `16384`
  records nothing. A config blob with one changed key produces one entry, not "settings: {…} → {…}".
- **Secrets are masked at any depth** — the key matches the shared scrubber's name rules (password,
  secret, token, api_key, private_key, credential, otp, recovery, encrypted, signature …) or is
  declared in `AuditMeta.secret_fields`, or the field is an encrypted field type. The entry records
  that the field changed, with both values as `"*****"`. **One scrubber**, owned by
  `OBSERVABILITY.md`; a second list here would drift from the logs' list.
- **Noisy fields are skipped**: `updated_at`, `created_at`, `version`, `last_seen_at`, `*_last_sync`,
  search vectors. **A save whose only changes are noisy or `preference_fields`** (a dashboard layout,
  a remembered filter, a last-selected scope) **writes no row at all.**
- **A status-only change becomes `status_changed`** with `from`/`to` — when every non-noisy changed
  field is in `state_fields` (default `status`, `state`, `is_active`). The feed then reads "Deal
  moved Open → Won", not "Deal updated".
- **Role and grant changes become `roles_changed`** with `granted: [...]` and `revoked: [...]` — written
  semantically by the RBAC service (`AUTH_BLUEPRINT.md` § 8.4), not reconstructed from M2M signals.
- **Long values are truncated for the diff** at `AUDIT_DIFF_VALUE_MAX` characters with an explicit
  `"truncated": true` marker — never silently.
- **`QuerySet.update()`, `bulk_create()` and `bulk_update()` fire no signals.** Services that use them
  on captured models call `audit.record(...)` themselves with a shared `batch_id`. A source-scan test
  flags bulk ORM calls on captured models outside an allow-list (ratchet).
- **Import mode** is a contextvar context manager, `with audit.importing(batch_id=…)`: captures are
  relabelled "Imported …", `source="import"`, and the empty follow-up saves an import typically makes
  are dropped.

```python
# plugin model opting in
class Contact(AuditedModel):
    class AuditMeta:
        title_field = "name"
        secret_fields = ("portal_token",)
        preference_fields = ("list_columns",)
        show_route = "crm:contact-detail"      # deep link, § 4.5
        index_route = "crm:contact-list"
```

### 4.4 Provenance of the write — source, via, CLI origin

**Rules.**

- **`source`** is one of `web` · `api` · `command` · `seeder` · `job` · `import` · `system`, set by the
  binder (§ 2), never by the caller. **Only sources that actually occur are offered as filters** — a
  "job" filter option when nothing runs as a job is a promise the data cannot keep.
- **`via`** refines web writes: `inline` (a cell edit) · `form` · `bulk` · `api`.
- **CLI writes record `origin_os_user`, `origin_host` and `origin_command`** (argv, **scrubbed** —
  a `--password` argument must not land in the audit log). A change made from `manage.py shell` or a
  one-off command is then attributable to a person on a machine.
- **Machine calls record both the consumer and, when present, the acting user** (the person carried on
  top of a machine token — `API_PLATFORM.md`). A row naming only the person for a machine call
  misleads; naming only the machine loses the human.

### 4.5 Vocabulary, tone and deep links

**Rules.**

- **Actions are registered**: `registry.audit_actions.register(key="crm.deal.won", label="Deal won",
  tone="success", channel="data")`. **Tone is a closed set** — `neutral` · `info` · `success` ·
  `warning` · `danger` · `security` — so the UI has one colour map and a plugin cannot invent a
  fourteenth shade of red.
- **An unregistered action still logs**, with a fallback label derived from the key and a development
  warning. Losing an audit row because a label was missing is the wrong trade.
- **Every action string used in code is registered** — a source scan collects `record("…")` literals
  and compares them with the registry; it **fails when it finds zero literals** (a completeness test
  that passes on an empty universe proves nothing).
- **Deep links:** a row links to the record via `AuditMeta.show_route`, or to the list via
  `index_route` with `?highlight=<id>` so the list opens on the page containing the row
  (`API_PLATFORM.md` computes the page; `FRONTEND_PLATFORM.md` scrolls and flashes). A deleted target
  links to the recycle bin (§ 7) if the viewer may see it, otherwise renders the snapshot as plain
  text. **The link goes to a page that enforces its own permission** — the audit screen never
  renders the record inline.

### 4.6 The read side

**Rules.**

- **Read-only by construction**: a `ReadOnlyModelViewSet` plus an `export` action; every write verb
  answers `405`. There is no permission that grants writing, because a permission is something an
  administrator can widen.
- **Reading is itself gated and scoped**: `core.audit.view` for the full log; every user may read the
  `security`-channel rows where they are the actor or the target ("your recent sign-ins") through the
  same `visible_to()` rule (§ 12).
- **Sorted by `id`**, never `created_at` alone.
- **CSV export is streamed** (`StreamingHttpResponse` over `.iterator(chunk_size=…)`), oldest-first,
  filtered by the same list pipeline as the screen, `changes`/`meta` as compact JSON in one column
  each, CSV-injection escaped (`DOMAIN_PRIMITIVES.md` § 6), filename carrying the UTC timestamp. **The
  export is audited** — a human reading the evidence in bulk is itself an event.
- **Per-record history** (`GET /api/<module>/<resource>/<id>/history/`) reads the same table filtered
  by target, with the resource's own permission, so a plugin does not build a second history table.

### 4.7 Structural immutability

**Rules.** Four layers, because each one alone has a hole:

| Layer | Stops | Hole it leaves |
|---|---|---|
| No write routes (`405`) | the API | the shell, admin, a management command |
| `save()` refuses when not adding; `delete()` raises | ORM instance writes | `QuerySet.update()` / `.delete()` |
| Custom `QuerySet.update()` / `.delete()` raise | ORM bulk writes | raw SQL, `_base_manager` |
| **PostgreSQL `BEFORE UPDATE OR DELETE OR TRUNCATE` trigger raising** | everything | — |

- **The trigger allows `DELETE` only inside the retention engine**, which runs
  `SET LOCAL core.retention_purge = 'on'` in its own transaction; the trigger checks
  `current_setting('core.retention_purge', true)`. `UPDATE` is never allowed. This is why § 4.1 has
  no `SET_NULL` foreign keys — they would be `UPDATE`s.
- **The trigger is installed by a vendor-guarded `RunSQL`** (`schema_editor.connection.vendor ==
  "postgresql"`); SQLite development gets layers 1–3 only (⚠️ C10).
- **The same four layers protect every append-only table** a module declares (ledgers, state
  transitions, event ledgers) — via `core.models.AppendOnlyModel` and a migration helper
  `append_only_trigger(model)`.

### 4.8 Hygiene rules

- **Nothing happened → nothing recorded.** A sync, reconciler or command that applied, staged and
  changed nothing writes **no** row. Feeds that drown in no-op rows get muted, and a muted feed hides
  the one row that mattered.
- **One run → one feed row** with counts (`event="run_summary"`); per-entity detail stays on each
  entity's own history with the same `batch_id`.
- **Seeder and command summaries**: `AuditedCommand` wraps `handle()`, collects created/updated/deleted
  counts in a contextvar, and writes one row — "demo seeder ran by an operator on a host: 27 created,
  4 updated" — only if a count is non-zero.
- **Audit where a human reads a secret, not on every machine read.** The reveal endpoint for a
  credential or token writes `security.secret_revealed`; a model-retrieval observer would log
  thousands of machine reads a day and bury the one event that matters.
- **A failed login has no actor and no target** — the attempted identifier and address go in `meta`.
  Inventing a subject for an unauthenticated request is fiction.
- **What is audited, stated**: settings, flags, grants, roles, credentials, webhook endpoints,
  retention changes, recycle-bin actions, imports, exports of evidence. **What is not**: deliveries,
  request logs, login attempts (their own tables), preference saves.

**Django + Next shape (engine).** `core/audit/{models,record,capture,diff,registry,commands}.py`;
`registry.audit.capture_app()`, `registry.audit_actions.register()`; `AuditedCommand(BaseCommand)`;
`core.models.AppendOnlyModel`. Endpoints: `GET /api/core/activity/`, `GET /api/core/activity/export/`,
`GET /api/<module>/<resource>/<id>/history/`. Next: an activity table using the tone map, filters from
the registries (channels, actions, sources that occur), and the deep-link column.

**Enforced by.**

- `test_audit_record.py::test_record_never_raises_and_counts_the_failure` (force an insert error).
- `test_a_failed_insert_does_not_break_the_outer_transaction` — the outer atomic block still commits.
- `test_failed_login_row_survives_request_rollback` (independent mode, Postgres CI).
- `test_model_change_row_rolls_back_with_the_change`.
- `test_diff.py` — FK label, choice label, JSON per-key, scalar coercion, secret masked at depth 3,
  noisy-only save writes nothing, status-only rewrite, deferred field not queried
  (`assertNumQueries`).
- `test_immutability.py` — update via instance, `QuerySet.update`, raw SQL: all refused on Postgres;
  retention delete allowed only with the session flag.
- `test_only_record_writes_the_table` — source scan for `ActivityLog(`/`.objects.create` outside
  `core/audit/record.py`.
- `test_every_audit_action_literal_is_registered` — fails on zero literals.

**Configurable, not hard-coded.** `AUDIT_DIFF_VALUE_MAX` (default 1,000) · channels, actions and tone
labels via registries · capture allow-list via registry · `DATABASES["audit"]` alias present or
absent · retention of the log via § 6 (off by default).

---

## 5. State-transition history — **Tier 2 · Core**

**What.** A generic `core_state_transition` table written by `StatefulMixin` on every save that
changes a declared state field, so durations, funnels and SLAs are computed from recorded facts.

**Why.** "A gap in a duration table does not look like a gap, it looks like a fast stage." A studied
product computed response times from `updated_at` — which moves on every edit, so a typo fix turned a
two-hour response into a two-month one. Transitions written only by one service were missed by the
next write path someone added without knowing the table existed.

**Rules.**

- **Written by the model, not a service convention.** `StatefulMixin.save()` compares the loaded
  state (`from_db()` snapshot) with the new one and writes the transition in the same transaction.
  Every write path — service, admin, import, shell — records it.
- **`QuerySet.update(status=…)` is refused** by the stateful queryset; state moves through the
  transition service ([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) § 3) or `save()`.
- **System writes record actor `NULL`** with a `system:<task>` label — never "whoever is resolvable".
- **Backfills record only evidenced transitions**, with `is_reconstructed = True`. The
  `measured()` queryset excludes them, and every contractual or reported figure is computed from
  `measured()`. A reconstructed row is history; it is not a measurement.
- **Never compute a duration from `updated_at`.** Durations are differences between transition
  `occurred_at` values.
- **Derived facts are computed on read.** An SLA breach, an "overdue" flag, a pairing already implied
  by the audit log — computed from transitions plus the current target setting, never stored as
  `breached_at`. Re-tuning the target then re-evaluates history consistently, and a reminder job
  cannot go permanently silent because it gated on `reminder_sent_at IS NULL`.
- **State sets are named constants**: `OPEN_STATES = frozenset({...})`, `TERMINAL_STATES`, with
  queryset methods (`.open()`, `.terminal()`). A literal `status="won"` in six places is how one
  eligibility check was gated on a status the pipeline never entered. A source scan forbids status
  literals outside the model module (ratchet).
- **Ownership is a column pair** (`owner`, `claimed_at`): cleared on release, **not restamped on an
  unchanged re-save**, and its history *is* the transition table (`field="owner"`).

**Django + Next shape.**

| Column | Notes |
|---|---|
| `object_type` · `object_id` | Snapshot, as § 4.1 — history survives deletion |
| `field` | `status` by default; a model may track several |
| `from_state` · `to_state` | Raw values; labels rendered from the model's `TextChoices` at read |
| `actor_id` · `actor_label` · `source` | From `ActorContext` |
| `reason` | Optional; required for corrections between terminal states |
| `occurred_at` | When it happened (may be supplied by import, § 9.2) |
| `recorded_at` | When we wrote it |
| `is_reconstructed` | Backfill flag |
| `batch_id` | Bulk transitions |

Append-only (§ 4.7). Index `(object_type, object_id, occurred_at)` and `(field, to_state,
occurred_at)`. `StatefulMixin` declares `STATE_FIELDS = ("status",)`. Detail endpoints may include a
`transitions` sub-resource.

**Enforced by.** `test_state_history.py::test_admin_save_records_a_transition`,
`test_queryset_update_of_status_is_refused`, `test_measured_excludes_reconstructed`,
`test_no_duration_reads_updated_at` (source scan over reporting modules).

**Configurable, not hard-coded.** `STATE_FIELDS` per model; SLA/target values are settings
(`CONFIGURATION.md`), read at computation time.

---

## 6. The retention engine — **Tier 2 · Core**

**What.** One engine that deletes or anonymises data according to **registered policies**, run daily
by the job runner and by `manage.py retention` for cron. [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md)
§ 19.2's `auth_cleanup` becomes three policies registered by the `users` app.

**Why.** Four failures across the studied codebases: seven tables "each quietly deciding for
themselves"; a package's own cleaner reading a 50-day default that silently destroyed three weeks of
audit trail against an agreed 90-day policy; a scratch table that reached 76 % of the database
because nobody wrote its purge; and "age alone never bounded the database" — the tables that grow
fastest (request logs, error occurrences, deliveries) grow fastest **exactly when something is
wrong**.

### 6.1 The policy

```python
# users/retention.py — registered from UsersConfig.ready()
registry.retention.register(RetentionPolicy(
    key="users.login_attempts",
    model="users.LoginAttempt",
    timestamp_field="created_at",
    max_age_setting="retention.users.login_attempts.days",   # default 90, floor 7
    max_rows=2_000_000,                                        # optional cap
    data_class="security_log",
    strategy="delete",
    description="Throttling and forensics; grows with attack traffic, not users",
))
```

| Field | Meaning |
|---|---|
| `key` | Registry key, `module.name` |
| `model` · `timestamp_field` · `filter` | What is eligible (`filter` e.g. "revoked or expired sessions only") |
| `max_age_setting` | Settings-registry key holding days; code default + **floor** (`min_age_days`) |
| `max_rows` | Optional cap, applied **after** age |
| `data_class` | `security_log` · `operational_log` · `personal_data` · `evidence` · `content` |
| `strategy` | `delete` · `anonymise` (with `scrub` spec or an anonymiser callable) |
| `storage_fields` | File fields whose objects are deleted before the row |
| `requires_opt_in` | The flag travels with the policy, so the next caller cannot forget it |
| `batch_size` · `max_batches` | Defaults from settings |

### 6.2 The algorithm

1. **Resolve the cutoff once**, from the setting clamped to the floor, via one helper
   `cutoff_for(policy, now)` — shared by `--dry-run`, `--status` and the real run (asserted by test).
2. **Age cut** (cheap, indexed): `timestamp < cutoff`.
3. **Then the cap**, if `max_rows`: `COUNT(*)` short-circuits when under cap; otherwise order by
   `(timestamp DESC, pk DESC)` and delete everything beyond `OFFSET max_rows`. **The pk tiebreak** is
   what stops a row flipping in and out of the keep-window between batches.
4. **Batched**: select up to `batch_size` pks, delete `WHERE pk IN (…)`, **commit per batch** (each in
   its own `atomic`). Short locks; an interrupted sweep still made progress.
5. **`max_batches` per run**, reporting `truncated=True` — "still shrinking" is not "at target", and
   the status screen says which.
6. **Record one summary row per policy per run**, only if something was removed (§ 4.8). Purging the
   audit log records itself **after** the purge, so the record survives the truncation it describes.

⚠️ **Django `QuerySet.delete()` fast-path trap.** Django deletes in one SQL statement only when the
model has no cascades and **no `pre_delete`/`post_delete` receivers**; otherwise it loads every row
into memory to fire signals. Registering a log model for audit capture (§ 4.3) silently turns a
batched purge into a memory spike. Retention-managed log models are never captured, and a test asserts
no delete receivers exist on them.

### 6.3 Rules

- **Floors, so a `0` cannot wipe a table.** `None` means *keep forever* (disabled); `0` and negatives
  are refused at save time by the settings registry validator and again by the engine; a value under
  the floor is refused, never clamped silently.
- **Contradictory flags resolve toward deleting less.**
- **Evidence tables are opt-in.** The audit log's policy has `requires_opt_in=True`; the scheduled run
  skips it unless the setting `retention.core.activity_log.enabled` is on, and the CLI needs
  `--include-opt-in`. This preserves `AUTH_BLUEPRINT.md` § 19.2's rule that core never silently
  truncates an audit trail.
- **Evidence and security tables are never row-capped.** A cap on an audit table is an
  attacker-controllable delete: generate enough noise and your own tracks roll off the end. The
  registry refuses `max_rows` on `data_class in {"evidence", "security_log"}`.
- **Never cap live state**: sessions (a cap would sign live users out on a busy day — the per-user
  live-session limit in `AUTH_BLUEPRINT.md` § 19.2 is a different mechanism and stays), error
  *groups* (the triage surface), open findings, user-owned content. Only machine-written logs get caps.
- **Anonymise vs delete is per data class.** Closed tickets, orders and invoices keep rows, statuses
  and timestamps for metrics while identity, bodies and payloads are scrubbed; transcripts, raw
  payloads and scratch data are deleted. Anonymisation sets `anonymised_at` and is idempotent.
- **Storage objects are deleted before database rows.** If an object cannot be deleted, **the row is
  skipped untouched** and retried next run — never half-erased, never a dropped pointer to an object
  that may still exist. After `retention.max_storage_failures` consecutive failures the row raises a
  finding ([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) § 8).
- **Legal hold wins.** `core_retention_hold(target_type, target_id | subject_user_id, reason, placed_by,
  released_at)`; held rows are excluded from every policy. Placing and releasing a hold are audited.
- **Erasure on request uses the same registry.** Policies with a `subject_field` can be run for one
  person (`manage.py retention --erase-subject <id> --dry-run`), applying each policy's strategy —
  one mechanism for "age out" and "forget me".
- **Plugin tables that do not exist yet are skipped**, not errors — a plugin registered but not
  migrated reports `missing` in `--status`.

### 6.4 A package default never decides retention

Every third-party component that deletes on its own schedule is disabled or routed through a policy:
Celery's built-in `celery.backend_cleanup` beat entry, `django-celery-results` expiry, Django's
`clearsessions` if session storage is used, any activity-log package's cleaner. **A test lists the
beat schedule and fails on any periodic task that deletes data and is not the retention job.**

**Django + Next shape.** `core/retention/{registry,engine,commands}.py`;
`manage.py retention [--status] [--dry-run] [--policy KEY] [--include-opt-in] [--erase-subject ID]`;
a daily job in the jobs registry (`JOBS_AND_INTEGRATIONS.md`) — until a scheduler exists, the cron
line is the deploy contract (`TECH_DEBT` DB-16). `--status` prints per policy: rows, oldest row,
cutoff, eligible, cap, last run, truncated, missing. A read-only System → Data retention screen shows
the same table and edits the windows through the settings registry.

**Enforced by.** `test_retention.py` against a real database: age cut, cap with pk tiebreak, batching
commits per batch (kill mid-run, progress kept), `truncated` reported, dry-run and real run share the
cutoff, `0` refused, floor refused, opt-in skipped by default, cap refused on evidence,
storage-failure row left untouched, held row kept. `test_no_foreign_cleaner_in_the_beat_schedule`.
`test_every_append_only_or_log_model_has_a_policy_or_an_exemption` (ratchet with reasons).

**Configurable, not hard-coded.** Every window is a settings-registry key with a code default and a
floor: `retention.<policy>.days`; `retention.core.activity_log.enabled` (default off);
`retention.batch_size` (5,000); `retention.max_batches` (200); `recycle_bin.retention_days` (§ 7).

---

## 7. Soft delete and the recycle bin — **Tier 2 · Core**

**What.** `SoftDeletableModel` for user-facing content (per `DATA_MODEL.md` D4), uniqueness that
survives it, and a recycle bin built from a registry.

**Why.** Before a recycle bin, every delete in one studied core was permanent. The popular fix —
widening a unique index with `deleted_at` — silently destroys uniqueness on databases where `NULL`s
are distinct (`UNIQUE(email, deleted_at)` accepts two live rows). And a recycle bin that resolves a
request's `type` string to a class name is an arbitrary-model-load primitive.

### 7.1 The model

- `deleted_at`, `deleted_by` (§ 2 rules), `deletion_batch` (`UUIDField`, null).
- **Default manager excludes deleted rows; `all_objects` opts in** (`DATA_MODEL.md` D4) — forgetting is
  the safe direction.
- `delete()` soft-deletes and records `deleted`; `hard_delete()` is explicit and separately permitted;
  `restore()` clears the three columns and records `restored`.
- **Soft delete does not cascade implicitly.** A service that soft-deletes a parent and its children
  stamps all of them with one `deletion_batch`; restore restores the batch. Children not stamped stay
  visible and must be hidden by their own queries — a decision per relation, written in the model's
  docstring.
- **A soft-deleted user must not authenticate**: user soft delete also sets `is_active = False`, and
  session/token lookup filters deleted rows.

### 7.2 Uniqueness that survives soft delete

- **Soft-deletable models never declare `unique=True`** (other than the pk). Uniqueness is
  `UniqueConstraint(fields=[...], condition=Q(deleted_at__isnull=True), name=...)` — functional where
  needed (`Lower("email")`). PostgreSQL and SQLite both support partial unique indexes; the rule
  holds in development too.
- **The direction inverts:** re-creating a value held by a binned row is allowed; **restore** must
  check for a live row now holding it and answer `409 restore_conflict`, naming the conflicting
  record if the caller may see it.
- **Never widen a unique index with `deleted_at`.**

### 7.3 History surfaces still resolve deleted rows

Deleted rows are filtered from login, pickers, lists, details and search — but **not** where a record
is named *as history*: audit actor names, a security panel, error occurrences, "created by" on an old
document. Those use `all_objects` / `_base_manager` or, better, the snapshot label (§ 4.1). Otherwise
"who did this" becomes "unknown" for exactly the deleted accounts.

⚠️ **Never set `Meta.base_manager_name` to a filtering manager.** Django uses the base manager for
forward related-object access *and inside `Model.save()`'s update path*; a base manager that hides
deleted rows makes saving a soft-deleted instance attempt an `INSERT`, and makes `invoice.customer`
raise for a binned customer.

### 7.4 The recycle bin

```python
registry.recyclable.register(Recyclable(
    key="crm.contact", model="crm.Contact", label="Contacts",
    title_field="name", subtitle_field="email",
    unique_fields=("email",), restore_hook=None, purge_hook=None,
))
```

- **Types resolve by registry key only.** The request's `type` is looked up in the registry **before
  anything resolves**; an unknown key is `404`. A class name, `app.Model` string or content-type id
  from a request is never turned into a model.
- **Show the unique values a binned row carries and whether each is currently free**, so a restore
  conflict is visible before the click (and, for any model left on full uniqueness, the invisible
  blocker behind "email already taken" is visible too).
- **Scoped like everything else**: the bin lists `all_objects.deleted().visible_to(user)` — a recycle
  bin that forgets scoping is a cross-tenant leak of precisely the data people deleted.
- **One permission, `core.recycle_bin.manage`**, covers listing, restore, force-delete — seeing what
  was deleted is as sensitive as restoring it. Force-delete additionally requires the model's own
  delete permission and respects `PROTECT` foreign keys, reporting a blocked row with its reason
  rather than failing the batch.
- **Purge after `recycle_bin.retention_days`** via a retention policy (§ 6) with
  `timestamp_field="deleted_at"`, storage objects first.
- **Every action is audited** (`restored`, `force_deleted`, `purged` summary row).

⚠️ **`dumpdata` uses the default manager** and silently omits soft-deleted rows unless `--all` is
passed. Backups are `pg_dump` (`OPERATIONS.md`), never `dumpdata`; the export registry
([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) § 6) states whether binned rows are included.

**Django + Next shape.** `core/softdelete.py`, `core/recyclebin/{registry,services,views}.py`;
`GET /api/core/recycle-bin/?type=crm.contact`, `POST …/<type>/<id>/restore/`,
`POST …/<type>/<id>/force-delete/`. Next: one recycle-bin screen with a type picker from the
registry; restore invalidates the resource's list cache.

**Enforced by.** System check `core.E0xx`: a `SoftDeletableModel` with a `unique=True` field fails
boot. `test_recycle_bin.py`: unknown type → 404, class-name type → 404, restore conflict → 409,
scoped listing, held values shown, force-delete blocked by `PROTECT` reported;
`test_history_still_names_a_deleted_actor`.

**Configurable, not hard-coded.** `recycle_bin.retention_days` (default 90, floor 7); types via
registry.

---

## 8. Provenance — **Tier 2 · Core**

**What.** `ProvenanceMixin` records *how* a row came to exist, in two halves with different trust.

**Why.** Machine-authored records need tracing without inventing facts. A boolean `is_manual`
defaulting to `False`, backfilled across existing data, would have asserted "a human typed this"
about ~20,000 rows nobody had verified.

**Rules.**

- **`created_via`** — FK to the API consumer (`API_PLATFORM.md`), `null=True`,
  `on_delete=SET_NULL`, set **from the authenticated principal** in the service, never from the
  payload. Serializers declare it read-only.
- **`origin`** — `web` · `api` · `import` · `job` · `system`, copied from `ActorContext.source` at
  insert.
- **`source_ref`** — `CharField(191)` from the request body: the caller's pointer to its own record.
  **A pointer, never evidence.** Constrained by **form** (`RegexValidator(r"^[A-Za-z0-9._:/#-]{1,191}$")`)
  where it cannot be constrained by membership. **A plain, non-unique index** — a unique one silently
  becomes an idempotency key with the wrong semantics (idempotency is `JOBS_AND_INTEGRATIONS.md`'s
  ledger).
- **`NULL` means unknown.** Never backfilled, defaulted or rendered as "Web"/"Manual"; the UI shows
  "—" with a tooltip "recorded before provenance tracking". Adding the mixin to an existing model
  leaves existing rows `NULL`.

**Enforced by.** `test_provenance.py::test_created_via_ignores_the_payload`,
`test_source_ref_rejects_control_characters`, `test_existing_rows_stay_null_after_migration`.

**Configurable, not hard-coded.** The `source_ref` pattern is a setting (`provenance.source_ref_regex`)
with the default above.

---

## 9. Data-modelling conventions — **Tier 1 · Core**

Additions to [`DATA_MODEL.md`](DATA_MODEL.md) § 4. Each is a correctness bug a studied team hit.

### 9.1 Human-declared vs machine-reported are two fields, never one

A sync-owned `health` overwritten every poll and a human-set `is_broken` + `broken_notes` are
**separate columns**. The machine field has no human edit path (read-only in serializers); the human
field is never written by a sync. Any "effective" value is a computed property with its precedence in
the docstring. Naming: `reported_*` / `declared_*` where ambiguity is possible.

### 9.2 Event date vs recorded-at

`created_at` is when **we recorded it**. When the domain has a moment it *happened* — a stock
movement, a payment received, a meeting held — that is a separate `occurred_at` (instant) or
`occurred_on` (date), supplied by the user or source. Reports and state durations use the event time;
backdating beyond `data.max_backdate_days` requires a permission and is audited.

### 9.3 Durable identity and public tokens

- **History follows a durable key**, not a mutable attribute — a device trail survives
  re-registration by keying on the most stable identifier available, with the fallback order written
  down.
- **Anything printed** (a label, a QR code, a document reference) carries a random `public_token`
  (`secrets.token_urlsafe`, unique), **stored and exported verbatim**, never derived from the pk or the
  environment — so a printed label survives a staging→production migration and an id re-sequence.
  Regenerating a token is an audited action. This complements `AUTH_BLUEPRINT.md` A15 (opaque public
  ids), it does not replace it.

### 9.4 Inclusive date semantics, stated

- **Suffixes carry meaning:** `*_at` = instant (UTC); `*_on` = calendar date in the business
  timezone, never converted to UTC; `*_until` = **inclusive** last valid day; `ends_at` = **exclusive**
  instant. Datetime ranges are half-open `[start, end)`.
- **A default end date is `add_months(start, n) - 1 day`, with month-end clamping first**
  (31 January + 1 month = end of February), via one helper `core.dates.add_months()`.
- **Compare with `<` / `>` against `now() - timedelta`**, not signed differences — a signed diff printed
  "pending for -1771h" and a transposed freshness check never tripped.
- **Derive labels from the generating cursor**; never re-parse a `YYYY-MM` key (the 31st overflows).

### 9.5 Length caps only on what a person types

- A human-typed field gets a cap, enforced in the **serializer** and shown as a counter in the UI.
- ⚠️ **`TextField(max_length=…)` is enforced by neither PostgreSQL nor `full_clean()`** — only
  `CharField` gets a `MaxLengthValidator`. The serializer is the enforcement point; shared limits live
  in `core/limits.py` (`NOTES_MAX_LENGTH`, …).
- **Machine-written text is never capped**: our own error messages, tracebacks, generated summaries,
  scripts. "The system must always be able to say what went wrong, at full length." Third-party
  payload excerpts (a webhook response body) may be bounded, with an explicit `truncated` marker.
- Tested at the cap and at cap + 1.

**Enforced by.** `test_text_length_caps.py` per app (cap passes, cap+1 → 400);
`test_dates.py::test_add_months_clamps_month_end`; a conventions test that `*_on` fields are
`DateField` and `*_at` fields are `DateTimeField`.

**Configurable, not hard-coded.** `data.max_backdate_days`; limits in `core/limits.py` as constants
(they are contracts with the UI, not tunables).

---

## 10. Invariants in the model **and** the database — **Tier 1 · Core**

**What.** Every business invariant has three homes: a validator in `Model.clean()`, a database
constraint, and a mapping from the constraint's violation to a friendly error.

**Why.** Per-caller checks drifted between services, bulk paths and imports; and an application-level
check loses the race that a database constraint wins. `DATA_MODEL.md` § 4 already says "constraints in
the database"; this section is the mechanism.

**Rules.**

- **One shared validator per invariant**, called by `Model.clean()`; services call `full_clean()`;
  bulk and import paths call the **same** validator for per-row messages.
- **A database backstop for every invariant expressible in SQL**: `CheckConstraint(condition=…)`
  (Django 5.1+ spelling), `UniqueConstraint` (partial where needed — "unique when non-blank":
  `condition=~Q(reference="")`), `ExclusionConstraint` with `btree_gist` for overlapping ranges
  (PostgreSQL only, ⚠️ C10). Constraints set `violation_error_code` and `violation_error_message`
  (Django 5.0+), so `full_clean()` and the API speak the same code.
- **An application pre-check exists only for the friendly message**; the index remains the authority.
- **`IntegrityError` maps to `400`/`409`** in the exception handler through a registry keyed on
  **constraint name** → `(field, code, message)`. This is why every constraint is named (§ 1). An
  unmapped `IntegrityError` is a `409 conflict` with a generic message and a logged bug, never a
  `500`.
- **Migration order for a new constraint on existing data**: clean violating rows (a data migration) →
  `CREATE EXTENSION` if needed → add the constraint. On large PostgreSQL tables, add `NOT VALID` then
  `VALIDATE CONSTRAINT` separately via `RunSQL` so the table is not locked for the scan.

**Enforced by.** For every constraint, a test that **bypasses the application** —
`Model.objects.filter(pk=…).update(<violating value>)` — and asserts `IntegrityError`. A conventions
test asserts each named constraint has a mapping entry.

**Configurable, not hard-coded.** Nothing. Invariants are code.

---

## 11. A data migration may rewrite system content, never operator-authored content — **Process**

**What.** An extension to [`DATABASE_MIGRATIONS.md`](DATABASE_MIGRATIONS.md).

**Why.** A regex migration that fixed duplicated signature blocks worked on every development row and
would have silently mangled production templates; its `RunPython.noop` reverse admitted it could not
be undone. It was stopped before it shipped.

**Rules.**

- Migrations may create, update or delete **what the product ships and the operator cannot edit**:
  seeded reference rows, defaults, enum values.
- They **never transform user-authored rows** — templates, saved filters, notification bodies,
  documents — "even when the transform looks safe".
- Models that mix both carry `is_system` and `is_customised`. Editing a system row through the UI sets
  `is_customised = True`; data migrations filter `is_system=True, is_customised=False`. Corrections to
  customised rows ship as a new default plus an in-app "an updated version is available" action.

**Enforced by.** Review checklist item; a test helper `assert_migration_touches_only_system_rows()`
for data migrations over mixed models.

**Configurable, not hard-coded.** Not applicable.

---

## 12. Object scoping — extensions to RBAC Layer 2 — **Tier 1 · Core**

**What.** [`RBAC_DESIGN.md`](RBAC_DESIGN.md) Layer 2 and [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 7.6
define `visible_to(user)`, failing closed with `NotImplementedError` when missing. This section adds
what the studied codebases learned after shipping that much.

**Why.** Across the studies, tenant/object scoping was **the number-one recurring bug class**: an
"admin bypass" helper returned `None` to mean "no restriction", a caller built an unscoped query from
it and non-admins saw everything; scope applied to lists but not counts or filter dropdowns; reads
scoped while writes were not, so a user who could not *see* a row could `PATCH` it by id, change its
email and drive a password reset; scoping existed on the API but not on most UI list pages.

### 12.1 Register every listable model

- `registry.scopes.register(Model, tenant_field=None, owner_field=None, public_predicate=None)` from
  the owning app's `ready()`.
- **Every model a viewset lists is registered**, and — if tenancy exists — **every model carrying the
  tenant field is registered**. Both are asserted by walking `apps.get_models()` and the URL
  resolver's viewsets.

### 12.2 `None` vs empty, and no sentinel meaning "all"

- **`visible_to()` always returns a queryset** — possibly `.none()` — never `None`, never a flag.
- Scope resolvers that compute id sets return a **typed `Scope`**, not an optional set:
  `Scope.unrestricted(reason)` or `Scope.only(frozenset_of_ids)`, applied by `scope.apply(qs, field)`.
  The typed value exists because of the truthiness trap: with raw values, `if allowed:` treats the
  empty set (no access) exactly like `None` (unrestricted). **Truthiness tests on scope values are
  banned** by review and a source scan for `if not allowed` / `if allowed` in scoping modules.
- **An empty scope means no access, never everything.** A role grants no tenants/regions until given
  some.
- **The admin path is explicit**: `Scope.unrestricted(reason="holds core.tenants.view_all")`, and the
  bypass is audited like the superuser bypass.

### 12.3 Scope before anything the client controls

The scope is applied **before** search, filters, sort and pagination, so no client parameter reaches an
excluded row and the `count` is honest (post-filtering a page tells the user "40" and hands them 12).
The same scoped queryset feeds **lists, filter-dropdown options, counters, badges, exports, bulk
"select all", search and dashboards** — one resolver, read by every surface.

### 12.4 Narrow writes, not just reads

- `writable_by(user)` is a second queryset method (defaulting to `visible_to(user)` intersected with
  ownership or `manage`-level rules).
- The base viewset's `get_queryset()` dispatches on `self.action`: `list`/`retrieve` →
  `visible_to`; `update`/`partial_update`/`destroy` and every write `@action` → `writable_by`.
- `assert_writable(obj, user)` guards service entry points called outside a viewset.
- **Invisible → `404`; visible but not writable → `403`** (existence is already known).

### 12.5 Anonymous and machine callers

Anonymous and machine principals get the model's `public_predicate` or `.none()` — never "no user, so
no filter". A naive `if user is None: return qs` serves the internet everything. A model opts into
public visibility only by naming its predicate.

### 12.6 A remembered scope is re-validated on every read

A "current tenant / region / workspace" preference is stored as an **opaque string, not a foreign
key** (so a preference never blocks a delete) and **re-validated against the user's scope on every
read**; an invalid value silently falls back to the default. A client-supplied tenant header is fine
for *display*, never for *authority*.

### 12.7 The optional tenant safety net

Only when `DATA_MODEL.md` D3 introduces a tenant model (⚠️ C1).

- `TenantScopedManager` as the **default** manager filters on the tenant bound in a contextvar;
  `Model.objects.unscoped(reason="…")` is the logged, greppable bypass.
- **Bound and reset in the same middleware, in a `finally`**; Celery tasks bind it explicitly from
  their arguments; management commands require `with tenant_context(t)` or `unscoped(reason=…)`.
- **No tenant bound in a web request → `.none()`**, not all rows.
- **It is a safety net under `visible_to()`, not a replacement** — caller-applied scoping measured at
  eight call sites in one study; the ninth, forgotten, is a silent cross-tenant read.
- **It does not cover forward FK access** (`obj.related` uses `_base_manager`, which must not filter —
  § 7.3); that is acceptable because the related row is reached from an already-scoped row. Reverse
  managers (`tenant.invoices.all()`) use the default manager and *are* covered. `dumpdata`, the admin
  and migrations use managers differently — decided per case and written in the module doc.

### 12.8 Test fixtures

- **A "different-tenant actor" fixture is standard**: a user who manages a *different* tenant/record
  set. A bypass role, or a user managing nothing, passes both before and after a scoping fix and
  proves nothing.
- **A zero-membership user runs every list endpoint** and must get empty results; every detail
  endpoint with another tenant's id must 404; every write endpoint with an invisible id must 404.

**Django + Next shape.** `core/scoping.py` (`Scope`, `registry.scopes`), `core/querysets.py`
(`VisibleToQuerySet` gains `writable_by`), `core/api/viewsets.py` (action-dispatching
`get_queryset`). Next consumes only the results; it never computes scope.

**Enforced by.** `tests/architecture/test_scoping.py::test_every_listed_model_is_registered`,
`test_every_tenant_bearing_model_is_registered` (fails on an empty universe once tenancy exists),
`test_write_actions_use_writable_by` (introspects viewsets), `test_zero_membership_user_sees_nothing`,
`test_cross_tenant_pk_is_404_on_read_and_write`, `test_counts_and_filter_options_use_the_scope`.

**Configurable, not hard-coded.** The tenant field name (`CORE_TENANT_FIELD`) if tenancy exists;
nothing else — scope rules are code.

---

## 13. Delegation grants — **Tier 3 · Module**

**What.** An optional `delegation` app: explicit, per-module data-access grants from one user to
another, independent of roles and reporting lines.

**Why.** "While I'm on leave, X can see my records"; a senior overseeing two colleagues. Reporting lines
change for HR reasons and would silently redraw data access if access followed them.

**Rules.**

- **`DataAccessGrant(grantee, subject, scope, level, granted_by, reason, starts_at, expires_at,
  revoked_at)`** — `scope` is `"*"` or a module key **validated against the module registry**;
  `level` is `view` or `manage`.
- **`manage` implies `view`**, explicitly and tested — the ordering is `view < manage`. (One studied
  implementation compared levels by string equality, so a `manage` grant did not show up in a `view`
  query; the implicit hierarchy is the less surprising design.)
- **`accessible_user_ids(user, scope, level)` always includes self**, seeded before any grant — so
  it is never empty, and never mistaken for "no restriction".
- **`"*"` grants forward-extend to modules that do not exist yet** — which is exactly why creating one
  requires a stronger permission than a module grant and is audited with that warning.
- **Composes with tenant scope by AND** — a grant never crosses a tenant; a grant to a subject in
  another tenant is refused at creation. Self-grants are refused.
- **Applied to lists *and* filter dropdowns *and* counters *and* exports *and* search** — the same
  rule as § 12.3. It injects no query by itself; each module's `visible_to()` composes it
  (`created_by__in=accessible_user_ids(...)`), unless the user holds the module's view-all permission.
- Grant, revoke and expiry are audited; expiry is evaluated at read, never by a job that might not run.

**Django + Next shape.** `delegation/{models,services,querysets}.py`; `DelegatedQuerySetMixin`;
`/api/delegation/grants/`; a Next screen "Who can see my data" for the subject and an admin screen.

**Enforced by.** `test_delegation.py`: self always included, manage implies view, expiry honoured at
read, cross-tenant refused, counters match lists.

**Configurable, not hard-coded.** Module keys from the registry; `delegation.max_grant_days`.

---

## 14. ⚠️ Conflicts with existing docs

Not edited here — each needs the owning doc changed (and, where marked, a `TECH_DEBT.md` row).

| # | Existing doc says | The problem | Recommended fix |
|---|---|---|---|
| **C1** | `DATA_MODEL.md` D3 — no organisation model in core, design for it via `visible_to()` | Evidence from a studied core: it moved the tenant table **into** core because the core schema could not be created without it and the auth guard branches on tenant status (pending / active / suspended; suspension revokes sessions). The retrofit was measured at a 258-signature sweep against an estimate of ~40. Already tracked as `TECH_DEBT` **DB-23** | **Pending owner decision** (see below). Either keep D3 = no and record the measured retrofit cost in its ADR, or adopt a swappable core `Organisation` (like `AUTH_USER_MODEL`: `CORE_TENANT_MODEL`), nullable `User.organisation`, a tenant-status gate in authentication, and products extending it via `OneToOneField(primary_key=True)`. § 12.7 is written to work either way |
| **C2** | `AUTH_BLUEPRINT.md` § 3.12 and `DATA_MODEL.md` § 3 — `ActivityLog` target is a generic FK: `target_type_id` → `django_content_type` `SET_NULL`, `target_id PositiveBigIntegerField` | `SET_NULL` is an `UPDATE` on an append-only table (refused by the § 4.7 trigger, or silently erasing types if not); removing a plugin's content types rewrites history; a `PositiveBigIntegerField` cannot hold a UUID target (D2, or any plugin using UUIDs) | `target_type CharField(100)` (`app_label.model_name`), `target_id CharField(64)`, `target_repr CharField(255)`, no FK — § 4.1 |
| **C3** | `AUTH_BLUEPRINT.md` § 3.12 / § 4 `on_delete` table — `activity_log.actor` (and `impersonator`) `SET_NULL`, "the audit trail must survive the actor" | It survives, but as `NULL`: "who did this" becomes unknown for exactly the deleted accounts, and it is an `UPDATE` on an append-only table | `ForeignKey(..., db_constraint=False, on_delete=DO_NOTHING, null=True)` plus `actor_label` / `impersonator_label` snapshots — § 4.1. Alternatively forbid hard-deleting users (soft delete only) and keep the FK; decide explicitly |
| **C4** | `DATA_MODEL.md` § 2 / `AUTH_BLUEPRINT.md` § 3 shorthand — `created_at = DateTimeField(auto_now_add=True, db_index=True)` | `auto_now_add` overwrites supplied values, including in `bulk_create()`, so imports cannot preserve original creation times | `default=timezone.now, editable=False, db_index=True` — § 1 |
| **C5** | `DJANGO_STANDARDS.md` § 4 — "consider a shared abstract base in `core/` once a second model needs them — not before" | Contradicts `DATA_MODEL.md` § 2 (base models first) and the evidence (a base copy-pasted into five apps; 189 files redeclaring columns) | One base from the first model; the conventions test in § 1 enforces it |
| **C6** | `DATA_MODEL.md` § 2 `AuthoredModel` / D5 — `updated_by` = "who touched it last"; no rule for how the columns are set | Unconditional stamping writes `NULL` (or a wrong user) over real attribution from jobs and seeders | `updated_by` = last known **human** editor, set from `ActorContext` only when `kind == "user"`; machine writes are visible in the audit log — § 2. State the meaning in `DATA_MODEL.md` |
| **C7** | `DATA_MODEL.md` D4 — soft delete with a default manager; silent on uniqueness | The obvious `unique=True` blocks re-creation; widening with `deleted_at` breaks uniqueness where `NULL`s are distinct | Partial `UniqueConstraint(... condition=Q(deleted_at__isnull=True))`, no `unique=True` on soft-deletable models (system check) — § 7.2 |
| **C8** | `AUTH_BLUEPRINT.md` § 3.12 — "every write is wrapped in try/except" | In Django, catching a database error inside an `atomic` block without a savepoint breaks the outer transaction at its next query | Wrap in `try:` **+** `with transaction.atomic():` (a savepoint) — § 4.2. Also decide the rollback behaviour of security rows (recommended: independent connection) |
| **C9** | `AUTH_BLUEPRINT.md` § 19.2 / `BUILD_ORDER` 1.7 — a dedicated `auth_cleanup` command | Becomes the first caller of a generic engine; keeping a bespoke command re-creates "seven tables each deciding for themselves" | Register the three auth tables as retention policies (§ 6); keep `auth_cleanup` as an alias for `retention --policy users.*` so Phase 1 is not blocked. The `MAX_SESSIONS_PER_USER` live cap is unaffected |
| **C10** | [ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md) — SQLite for development | The § 4.7 immutability trigger, `ExclusionConstraint`, the independent audit connection and `NOT VALID` constraints are PostgreSQL behaviour; SQLite development silently skips or weakens them (`TECH_DEBT` DB-12) | Vendor-guarded `RunSQL`; the tests that prove these guards are marked `postgres_only` and must run in CI on PostgreSQL — skipping on SQLite is allowed, skipping in CI is a failure |
| **C11** | `DATA_MODEL.md` D2 recommends `BigAutoField`; `AUTH_BLUEPRINT.md` A15 integer PKs + opaque public ids; two studied codebases used UUID primary keys and one proposed UUIDv7 | Not a contradiction yet — D2 is open — but every design here must work for both | The base exposes `new_id()`; audit and transition targets use `CharField(64)`; decide D2 before the first migration as `DATA_MODEL.md` already demands |

---

## Pending decisions (for the repository owner)

1. **Tenancy in core (D3 / DB-23).** Keep "no organisation model" and record the retrofit cost, or adopt
   a swappable core tenant model now. This decides whether § 12.7 ships in Phase 1.
2. **PK type (D2)** and, if UUIDv7, which library backs `core.ids.new_id()` until Python 3.14.
3. **Security audit rows survive rollback** via a second `DATABASES["audit"]` alias (recommended) — or
   accept losing them when a request fails.
4. **Actor columns on the audit log**: `db_constraint=False` + labels (recommended), or a hard rule that
   users are never hard-deleted.
5. **Audit-log retention**: stays off by default (recommended); if enabled, what window, and is an
   archive export taken first.
6. **Where high-volume operational logs live** — the main database, or an optional `DATABASES["logs"]`
   alias with its own retention. The audit log stays in the main database either way, because
   transactional audit (§ 4.2) cannot span two databases.
7. **Soft-delete cascade** — per-relation batches (recommended) or a generic cascading soft delete.
8. **Enabling Ruff `DTZ`** — a one-line edit to the protected `backend/pyproject.toml`.
9. **Delegation grants** — confirm Tier 3 (module), as `PLATFORM_BLUEPRINT.md` lists it.

---

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section.
