# Jobs and Integrations

**How DjangoBaseX runs work in the background and talks to other systems — the job registry and
workers, queues and schedules, the run monitor, locks, reconcilers, the transactional outbox and
idempotency ledgers, webhooks in and out, the SSRF-safe HTTP client, provider error mapping, the
integration registry, the encryption service, the encrypted credential store and the non-production
outbound guard.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

---

## Scope — read first

**Owns:** the job/worker model (Celery + beat, and the in-process `run_worker` that precedes it) ·
the job registry and the run monitor · queue topology and its invariants · schedules · locks ·
retry policy · reconcilers · the transactional outbox · idempotent run ledgers · "push once" control
rows · outbound webhooks · inbound webhooks · the SSRF-safe HTTP client and per-target circuit
breakers · the provider error hierarchy and its HTTP mapping · external-lookup caching · contract
field validation · feeds · the integration registry · the encryption service · the encrypted
integration credential store · the non-production outbound guard.

**Does not own:**

| Topic | Owner |
|---|---|
| Who gets told, on which channel, and how ops alerts avoid being muted | [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md) |
| The registry catalogue itself, the event bus, service contracts, soft-disable | [`EXTENSIBILITY.md`](EXTENSIBILITY.md) |
| API tokens, machine principals, the `Idempotency-Key` header on endpoints, the error envelope, 429s | [`API_PLATFORM.md`](API_PLATFORM.md) |
| Request ids, the one log/error scrubber, metrics, health endpoints, doctors as a family | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
| Compose/Procfile topology, Redis persistence, PgBouncer, restore safety, dump sanitising | [`OPERATIONS.md`](OPERATIONS.md) |
| `APP_ENV`, the settings registry, feature flags, boot refusal | [`CONFIGURATION.md`](CONFIGURATION.md) |
| The retention engine that prunes the tables defined here | [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) |
| The findings queue (`core_finding`) that reconcilers and the outbox write into | [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) |
| The polling hook and toast store that announce a finished job | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) |
| The alert-rules and automation engines (optional modules built on these primitives) | [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) |

**Naming used below.** Tables are `core_*` because every primitive here is platform code. Permission
codes follow [`RBAC_DESIGN.md`](RBAC_DESIGN.md) (`core.jobs.view`). Environment variables are
`UPPER_SNAKE`; runtime settings are dotted keys in the settings registry
([`CONFIGURATION.md`](CONFIGURATION.md)). System-check ids are namespaced per subsystem
(`dbx.jobs.E001`) so this file cannot collide with the flat `dbx.E0xx` series in
[`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.2.

---

## 0. The rules in one screen

1. **Every job is declared in the job registry** — name, queue, schedule, owner module, description. Nothing is scheduled by hand. ([§ 1](#1-the-job-registry----tier-1--core), [§ 6](#6-schedules-are-code-synced-into-the-scheduler----tier-1--core))
2. **One failing job never stops the loop, and every job gets its own database connection.** ([§ 2](#2-two-runners-one-registry----tier-1--core))
3. **Destructive jobs ship disabled.** Enabling one is an operator's decision, recorded. ([§ 1](#1-the-job-registry----tier-1--core))
4. **Task payloads are ids, JSON-serialised, dispatched after commit.** Never a model instance, never pickle, never from inside an open transaction. ([§ 4](#4-dispatching-work----tier-1--core))
5. **Every queue has a worker and every beat entry names a registered task** — both are tests, and both fail on an empty universe. ([§ 5](#5-queue-topology----tier-1--core))
6. **Every run is recorded by a recorder that can never break the job it records.** ([§ 7](#7-the-run-record----tier-1--core))
7. **"Quiet" and "dead" must look different.** Health is `disabled > never_run > failing > overdue > ok`, plus `worker_seen_recently`. ([§ 8](#8-health-liveness-and-the-doctors----tier-1--core))
8. **A lock that outlives the work it guards is an outage.** Short TTLs, token-checked release, never a 24-hour lock. ([§ 9](#9-locks----tier-1--core))
9. **Long delays live in the database, not the broker.** A countdown longer than the visibility timeout is a duplicate. ([§ 10](#10-retry-and-backoff----tier-1--core))
10. **Every asynchronous or `PENDING` state has a reconciler**, and a reconciler that gives up records a finding. ([§ 11](#11-reconcilers----tier-2--core))
11. **A side effect that must happen is an outbox row written in the same transaction as the change.** An ambiguous send is `unknown`, never blindly retried. ([§ 12](#12-the-transactional-outbox----tier-1--core))
12. **"Do this exactly once" is a partial unique constraint**, not a check-then-insert. ([§ 13](#13-the-idempotent-run-ledger----tier-1--core))
13. **Outbound webhooks carry ids, are signed over `timestamp.body`, re-check SSRF at send time, never follow redirects, and trip a breaker.** ([§ 16](#16-outbound-webhooks----tier-2--core))
14. **Inbound webhooks verify the signature over the raw body before anything else**, and money-moving ones dedupe in the database. ([§ 17](#17-inbound-webhooks----tier-2--core))
15. **Every outbound HTTP call goes through `core.http`** — timeouts always, private ranges refused, the resolved IP pinned. Raw `requests`/`httpx`/SDK imports outside adapters fail lint. ([§ 18](#18-the-ssrf-safe-http-client----tier-1--core))
16. **An upstream 401/403 is a 502 to our caller**, never a 401 — or our frontend signs the user out for a partner's fault. ([§ 20](#20-provider-errors-and-their-http-mapping----tier-1--core))
17. **Never cache a failed lookup.** ([§ 21](#21-caching-external-lookups----tier-1--core))
18. **Encryption keys are a list, separate from `SECRET_KEY`, distinct per environment; decrypt failure raises; nothing decrypts on attribute access.** ([§ 25](#25-the-encryption-service----tier-1--core))
19. **Reading a stored secret needs a permission, a recent re-authentication, and writes an audit row every time.** Development never falls back to production credentials. ([§ 26](#26-the-encrypted-credential-store----tier-2--core))
20. **Outside production, nothing messages a person or writes to another system** — and there is no switch that turns that guard off. ([§ 27](#27-the-non-production-outbound-guard----tier-1--core))

---

# Part A — Background work

## 1. The job registry   — **Tier 1 · Core**

**What.** The `jobs` registry already planned in
[`CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md) § 2, specified. A module declares
every background job it owns — periodic or on-demand — as one `JobSpec` in `AppConfig.ready()`.
Workers, the scheduler, the run monitor, the doctors and the queue-topology tests all read **this
one list**; none of them keeps a second.

**Why.** A real incident: four careful purge and retry functions each carried a docstring saying
"nothing calls this on a schedule". The code existed, was tested, and never ran. When the schedule
lives in one place and the code in another, the two drift silently and the monitor — if one exists —
watches the wrong list.

**Rules.**
- **The registry is the only schedule.** The monitor derives "what should have run" from it, never
  from the scheduler's own table and never from a second list.
- **`owner_module` is required.** A failing job with no owner is nobody's pager.
- **`description` says what the job does and what breaks if it stops.** It is rendered on the Job
  Monitor page; "cleans up" is not a description.
- **`destructive=True` jobs ship `enabled_by_default=False`.** Anything that deletes or anonymises
  policy-governed data (retention of evidence, audit archival) is off until an operator turns it on;
  the switch is a setting change and therefore audited.
- **Idempotency is declared, not assumed.** `idempotent=True` is a claim the job's tests must prove
  (run twice, same end state). Only idempotent jobs may use `acks_late` (§ 3).
- **Feature-flagged jobs return before opening a database connection.** A disabled feature's job
  must cost nothing and touch nothing; "returns early after loading 10 000 rows" is not disabled.
- **Names are stable, dotted and owner-prefixed** (`billing.close_usage`). The name is the task name,
  the schedule key, the lock key prefix and the monitor row — renaming one is a migration.

**Django + Next shape.**

```python
# core/jobs/spec.py
@dataclass(frozen=True)
class JobSpec:
    name: str                       # "billing.close_usage" — also the Celery task name
    func: str                       # dotted path to the callable (resolved lazily)
    owner_module: str               # "billing"
    description: str                # what it does, and what breaks if it stops
    queue: str = "default"
    schedule: Schedule | None = None     # Interval(seconds=900) | Cron("15 */6 * * *") | None
    enabled_by_default: bool = True
    destructive: bool = False       # ⇒ enabled_by_default must be False (checked)
    idempotent: bool = False
    time_limit: int = 300           # hard, seconds
    soft_time_limit: int = 270      # always < time_limit (checked)
    expires: int | None = None      # periodic: < period, so a backlog drops stale runs
    single_flight: bool = True      # periodic default: never two at once (§ 9)
    unit: str = "rows"              # what the returned count means, for the monitor
```

```python
# billing/apps.py
registry.jobs.register(JobSpec(
    name="billing.close_usage", func="billing.jobs.close_usage", owner_module="billing",
    description="Closes yesterday's usage windows. If it stops, invoices are generated empty.",
    queue="billing", schedule=Cron("20 0 * * *"), idempotent=True, time_limit=900,
    soft_time_limit=840))
```

A job callable has one signature: `def run(ctx: JobContext) -> int` — it returns a count in `unit`,
and `ctx` carries the run id, a `stop_requested()` probe, a logger bound to the run, and the
idempotency key if one was supplied.

**Enforced by.**
- `dbx.jobs.E001` — two specs share a name.
- `dbx.jobs.E002` — `destructive=True` with `enabled_by_default=True`.
- `dbx.jobs.E003` — `soft_time_limit >= time_limit`, or a periodic job with `expires >= period`.
- `dbx.jobs.E004` — `func` does not import, or its signature is not `(ctx) -> int`.
- `tests/architecture/test_jobs_registry.py::test_every_job_has_an_owner_and_description` —
  walks the frozen registry; **fails if the registry is empty** (a registry that failed to load
  must not read as "no jobs, all fine").

**Configurable, not hard-coded.** Per-job overrides live in the settings registry, never in code
edits: `jobs.<name>.enabled` (bool), `jobs.<name>.schedule` (optional override, validated against the
same parser), `jobs.<name>.stale_after_minutes`. The spec carries the defaults.

---

## 2. Two runners, one registry   — **Tier 1 · Core**

**What.** Two ways to execute registered jobs, sharing every piece of code except the loop:

| Runner | When | How |
|---|---|---|
| `manage.py run_worker` | **Phase 1**, before any broker exists — and forever after as the cron-drivable fallback | An in-process loop that runs due periodic jobs |
| Celery worker + beat | Phase 2 onward, once real background *work* (fan-out, queues, user-triggered tasks) appears | § 3 |

**Why.** [`TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-16** records that `auth_cleanup` has no
scheduler and so depends on a crontab entry the deployer must remember. A broker is a heavy thing to
introduce for three daily sweeps — no fan-out, no queues, no results needed. But "a cron line per
job" is how the four uncalled functions above happened. The in-process runner gives Phase 1 the
registry, the run record and the health model **now**, and Celery later changes only the loop.

**Rules for `run_worker`.**
- **One failing job never stops the loop.** Each run is wrapped; an exception is recorded (§ 7),
  logged once, and the loop continues to the next due job.
- **Each run gets its own connection.** `close_old_connections()` before and after every job, so a
  job that broke its connection (or left a transaction open) cannot poison the next.
- **Graceful `SIGTERM`.** The handler sets a flag; the current job finishes (a delivery that was sent
  is recorded as sent), then the loop exits. Sleep is in one-second slices so shutdown is prompt.
  Long jobs poll `ctx.stop_requested()` between batches.
- **`--once`** runs every due job once and exits — the same code path, so a cron line calling
  `run_worker --once` every minute is a legitimate deployment, not a second implementation.
- **`--job NAME`** runs one job now, **even if disabled** — naming it is the instruction. It is still
  recorded, with `trigger="manual"`.
- **`--list`** prints every registered job with schedule, enabled state, last run and health.
- **"Due"** is computed from the last *recorded start* in `core_job_run`, never from process memory,
  so a restart does not re-run everything and two runners on one host do not double-run (the
  single-flight lock of § 9 is the real guard).

**Django + Next shape.** `core/jobs/runner.py` holds `execute(spec, ctx)` — the function both runners
call. `core/management/commands/run_worker.py` is the loop; the Celery task wrapper (§ 3) calls the
same `execute`. Nothing job-specific lives in either loop.

**Enforced by.** `tests/core/jobs/test_runner.py`:
`test_a_raising_job_is_recorded_and_the_loop_continues`,
`test_stop_finishes_the_current_job_rather_than_killing_it`,
`test_a_disabled_job_runs_when_named`, `test_destructive_jobs_are_off_by_default`,
`test_once_and_the_loop_share_execute` (patch `execute`, assert both call it).

**Configurable, not hard-coded.** `WORKER_TICK_SECONDS` (default 15), `WORKER_MAX_RUNTIME_SECONDS`
(optional; the loop exits cleanly after it so a process manager restarts it with fresh memory).

---

## 3. Celery configuration   — **Tier 1 · Core**

**What.** The settings every product inherits once Celery lands (Phase 2 in
[`CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md) § 8), each with its reason.
The Celery task for a registered job is generated from the `JobSpec` — modules do not hand-write
`@shared_task` wrappers for periodic jobs.

**Rules — the settings.**

| Setting | Value | Why |
|---|---|---|
| `CELERY_TASK_SERIALIZER` / `ACCEPT_CONTENT` / `RESULT_SERIALIZER` | `"json"` / `["json"]` / `"json"` | Pickle is remote code execution for anyone who can write to the broker. JSON also forces ids-only payloads (§ 4) |
| `CELERY_TASK_DEFAULT_QUEUE` | `"default"` — **explicit** | Celery's implicit default queue is named `celery`. A real incident: no worker listened on it, and every unrouted task sat in the broker forever |
| `CELERY_TASK_CREATE_MISSING_QUEUES` | `False`, with `CELERY_TASK_QUEUES` **generated from the registry** | A typo in a queue name must raise at publish, not create a queue nobody consumes. The flag only has teeth when the queue set is declared, so the declaration is generated rather than hand-kept |
| `CELERY_TASK_ACKS_LATE` | `False` globally; **`True` per task where the spec says `idempotent=True`** | Late ack means a crash re-delivers — correct only if running twice is safe. Durability for non-idempotent work comes from the outbox (§ 12), not the broker |
| `CELERY_TASK_REJECT_ON_WORKER_LOST` | `True` for the `acks_late` tasks | Otherwise a SIGKILLed worker acks the message it was holding |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | `1` | With late acks, prefetched messages sit reserved behind a long task; one slow job then delays many |
| `CELERY_TASK_TRACK_STARTED` | `True` | "Started" is a state the monitor shows; without it "queued" and "running" are indistinguishable |
| `CELERY_TASK_TIME_LIMIT` / `SOFT_TIME_LIMIT` | global `1800` / `1740`, overridden per spec | **Every task that sets `time_limit` also sets a smaller `soft_time_limit`.** A real incident: a per-task hard limit of 60 s with no soft limit inherited the global soft limit and effectively ran for ~29 minutes |
| `CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"]` | `> max(time_limit)` across all specs, with margin | On a Redis broker a message not acked within the visibility timeout is **redelivered to another worker while the first is still running** |
| `CELERY_TASK_ALWAYS_EAGER` | never outside tests | Eager mode hides serialisation, routing and transaction bugs — the exact class this file exists to catch |
| `CELERY_TASK_IGNORE_RESULT` | `True` | See the result-backend rule below |
| `CELERY_BEAT_SCHEDULER` | `django_celery_beat.schedulers:DatabaseScheduler` | Schedules are rows the registry syncs (§ 6), visible and toggleable, and they survive a beat restart |
| `CELERY_WORKER_SEND_TASK_EVENTS` | `False` unless a monitoring tool is deployed | Events cost broker traffic; our run record (§ 7) does not need them |

**The result backend matches what the UI reads.** The Job Monitor reads `core_job_run` (§ 7) —
**our** table, one source of truth for history. The Celery result backend is not a history store:
results are keyed by task id, expire, and cannot be listed. So results are ignored by default. A
task that genuinely returns a value to a caller opts in with `ignore_result=False`, and then
`dbx.jobs.E010` requires a result backend that is configured, shared, and not in-memory. A real
incident: a scheduler page read its history from a database result backend while the deployment
file overrode the backend to Redis — the page was empty in every deployed environment, and nobody
noticed, because empty looks exactly like quiet.

**Worker process hygiene.**
- **Connections:** `close_old_connections()` on `task_prerun` and `task_postrun`. Django closes stale
  connections per *request*; a worker has no requests, so without this a connection killed by the
  database or PgBouncer surfaces as an error in the *next* unrelated task.
- **Fork safety:** HTTP pools, SDK clients and anything holding a socket are built **lazily per
  process** (never at import, which runs before fork) and closed on `worker_process_shutdown`.
- **Tasks are synchronous.** The ORM here is synchronous
  ([`DJANGO_STANDARDS.md`](DJANGO_STANDARDS.md)); no `asyncio.run()` inside a task — a new event loop
  per call abandons the previous loop's connections.
- **Warm shutdown.** Workers get a stop grace period longer than the longest soft time limit they
  run, or the platform kills them mid-job ([`OPERATIONS.md`](OPERATIONS.md)).

**Django + Next shape.** `config/celery.py` (composition root) creates the app and calls
`core.jobs.celery.install(app)`, which registers one task per `JobSpec`, installs routing from the
specs' `queue`, connects the signals of § 7 and applies per-task `acks_late` / limits.

**Enforced by.**
- `dbx.jobs.E010` — a task has `ignore_result=False` and the result backend is unset/in-memory.
- `dbx.jobs.E011` — the broker visibility timeout is not greater than the largest `time_limit`.
- `dbx.jobs.E012` — serializer or accept-content includes anything but JSON.
- `dbx.jobs.E013` — `CELERY_TASK_ALWAYS_EAGER=True` while `APP_ENV` is not `test`.
- `dbx.jobs.E014` — `acks_late=True` on a spec that is not `idempotent`.
- `tests/core/jobs/test_celery_config.py::test_every_time_limit_has_a_smaller_soft_limit` —
  across **every registered task**, including hand-written ones; fails on an empty task list.

**Configurable, not hard-coded.** `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` (optional),
`CELERY_VISIBILITY_TIMEOUT` from env; the limits from each spec.

---

## 4. Dispatching work   — **Tier 1 · Core**

**What.** The rules for putting a task on a queue — the place most background-job bugs are born.

**Why.** Three generic incidents. A queued listener serialised a hydrated user object with its roles
and permissions and exhausted the worker's memory on every logout. A side-effect task was dispatched
before the transaction committed, ran against a row that did not exist yet, and failed — or, worse,
the transaction rolled back and the side effect happened anyway. A web request spawned a process to
do "background" work; endpoint-security software on a developer machine killed the dev server for
"web server starts a program", and in production the orphaned process outlived its request.

**Rules.**
- **Payloads are primitive ids and small scalars.** `send_invoice.delay(invoice_id=42)`, never
  `send_invoice.delay(invoice)`. The task re-reads the row — which is also how it sees the *current*
  state rather than a stale snapshot.
- **Dispatch after commit.** Inside a transaction, `core.jobs.enqueue()` registers
  `transaction.on_commit(...)`; outside one it publishes immediately. Raw `.delay()` / `.apply_async()`
  is lint-banned outside `core/jobs/` — the helper is the one place the rule lives.
- **Dispatch only when state actually transitioned.** "Mark paid, then enqueue the receipt" enqueues
  only on the call that moved the row to `paid`, not on every idempotent re-save. Compute
  `newly_paid` inside the transaction; enqueue on commit if it is true.
- **A side effect that must not be lost is not a bare `.delay()`.** A publish can fail after commit
  (broker down). If losing it matters, write an outbox row in the transaction (§ 12); the drainer is
  the backstop, the `on_commit` kick is only a latency optimisation.
- **Never queue work from a model signal on a global model event** (`post_save` for every model).
  Signals fire from fixtures, migrations, the shell and bulk loaders, and bypass entirely for
  `QuerySet.update()` and `bulk_create` — they are neither complete nor bounded.
- **Never spawn a process or a thread from a web request.** No `subprocess`, `os.system`,
  `multiprocessing`, `threading.Thread(...).start()` in views, serializers or services. Work that
  outlives a request is a job.

**Django + Next shape.**

```python
# core/jobs/dispatch.py
def enqueue(name: str, /, **kwargs: int | str | bool | None) -> None:
    spec = registry.jobs.get(name)                 # unknown name → KeyError (a programming error)
    _assert_primitive(kwargs)                      # raises TypeError on a model/dict/list
    send = partial(celery_app.send_task, name, kwargs=kwargs, queue=spec.queue)
    if connection.in_atomic_block:
        transaction.on_commit(send, robust=True)   # robust: a publish failure never breaks the save
    else:
        send()
```

A user-triggered long job returns its `core_job_run` id (`202 Accepted`,
`{"job_run_id": ...}`); the frontend polls `GET /api/jobs/runs/<id>/` and raises a toast on the
transition to done ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)).

**Enforced by.**
- `tests/architecture/test_task_payloads.py` — AST scan: every `enqueue(...)` call passes only
  names/literals, and every registered task's signature is annotated with `int | str | UUID | bool`
  parameters only.
- `tests/architecture/test_no_raw_dispatch.py` — `.delay(` / `.apply_async(` / `send_task(` outside
  `core/jobs/`.
- `tests/architecture/test_no_process_spawn_in_requests.py` — `subprocess`, `os.system`, `Popen`,
  `multiprocessing`, `Thread(` in any `views.py`, `serializers.py`, `services.py` or `api/` module;
  allowlist with a reason per entry (management commands are exempt by path).
- `tests/core/jobs/test_dispatch.py::test_enqueue_inside_atomic_publishes_only_after_commit` and
  `::test_rollback_publishes_nothing`.

**Configurable, not hard-coded.** Nothing — these are invariants.

---

## 5. Queue topology   — **Tier 1 · Core**

**What.** Queues are per domain, declared by the specs that use them, and the worker topology is
proven to consume every one.

**Why.** Isolation: revenue work must never be starved by a slow sweep, sign-up must not queue behind
a flood on `default`, and user-facing tasks must not wait behind periodic audits. And the silent
failure: **a task routed to a queue with no consumer is enqueued and never executed, and nothing
raises.** A real incident: a module's tasks were moved to a new queue, the worker for it was never
added, and the work sat in the broker for months — the failed-jobs table was empty the whole time,
which read as healthy. Those jobs never failed; they were never picked up.

**Rules.**
- **A queue exists because a spec names it.** The routing table is generated from the specs; there
  is no hand-maintained `task_routes` dict to drift.
- **Every declared queue has a consumer** in every deployment topology the repository ships
  (`compose.yaml`, `Procfile`, any orchestrator manifest).
- **Every beat entry names a registered task**, and every scheduled spec produces a beat entry.
- **Exact task names route before globs**, and hand-written tasks that register under a custom name
  must be routed by that name — a route keyed on the module path silently misses them.
- **Separate queues for separate latency classes**, not per module by reflex: `default`,
  `interactive` (a human is waiting), `bulk` (sweeps, imports), `outbox` (§ 12), `monitoring` (the
  recorder's own housekeeping, excluded from the monitor so it does not record itself). A product
  adds domain queues when a measured starvation justifies one.

**Django + Next shape.** `core.jobs.topology.declared_queues()` returns the set from the registry.
Compose services are one per queue group:
`celery -A config worker -Q billing,bulk --concurrency=2 -n billing@%h`.

**Enforced by.**
- `tests/architecture/test_every_queue_has_a_worker.py` — parses every shipped topology file, collects
  each worker's `-Q`, and asserts `declared_queues() ⊆ consumed`. **It fails, not skips, when no
  topology file is found** — a real incident: the equivalent guard skipped whenever it ran inside a
  backend-only container, so it only protected full checkouts.
- `tests/architecture/test_task_routing.py` — for every registered task, the queue the router
  actually resolves (`app.amqp.router.route(...)`) equals the spec's `queue`; divergences allowlisted
  with a reason.
- `tests/architecture/test_beat_entries_are_registered.py` — every synced `PeriodicTask.task` is in
  `app.tasks`; every scheduled spec has an entry. Fails on an empty schedule.

**Configurable, not hard-coded.** Concurrency per worker and queue grouping are deployment choices
([`OPERATIONS.md`](OPERATIONS.md)); the set of queues is code.

---

## 6. Schedules are code, synced into the scheduler   — **Tier 1 · Core**

**What.** `django-celery-beat`'s `PeriodicTask` rows are **generated from the registry** on
`post_migrate` (and by `manage.py sync_schedules`), never created by hand or in a data migration.

**Why.** Schedules created by hand in an admin screen exist in one environment and not the next;
schedules created in data migrations are frozen at the moment the migration was written and are not
updated when the spec changes. Both drift from the code that is supposed to own them.

**Rules.**
- **Sync is reconcile, not rebuild.** Create missing registry-owned rows, update changed ones,
  **delete registry-owned rows whose spec is gone**, and never touch rows the registry does not own
  (ownership is recorded in a `core_job_schedule(job_name, periodic_task)` map, not inferred from a
  name prefix).
- **Enabled state comes from `jobs.<name>.enabled`** (falling back to `enabled_by_default`), so an
  operator's toggle survives the next sync.
- **Bulk updates call `PeriodicTasks.update_changed()`** — the database scheduler only notices
  changes through that marker, and `QuerySet.update()` does not fire the signal that sets it.
- **Stagger.** Periodic jobs do not all land on `:00`. Cron specs pick explicit offsets; interval
  specs get a deterministic per-name jitter (hash of the name mod the interval) so the whole fleet
  does not wake at once.
- **`expires` shorter than the period.** If a worker falls behind, stale periodic runs are dropped
  rather than queued behind each other and executed in a burst.
- **Timezones are explicit.** Cron specs run in `CELERY_TIMEZONE` (UTC by default); a spec whose
  business meaning is local ("09:00 for the operators") declares `tz_setting="platform.default_timezone"`
  and is resolved from the settings registry — never a literal zone in code
  ([`CONFIGURATION.md`](CONFIGURATION.md)).
- **Exactly one beat process.** Two beats double every periodic job; the single-flight lock (§ 9) is
  the backstop, not the plan.

**Django + Next shape.** `core/jobs/schedules.py::sync_schedules(dry_run=False) -> SyncReport`,
connected to `post_migrate` from `CoreConfig.ready()` with `sender=self` so it runs once per migrate.
`manage.py sync_schedules --dry-run` prints the diff.

**Enforced by.** `tests/core/jobs/test_schedule_sync.py`: sync twice is a no-op; a removed spec's row
is deleted; a foreign row survives; an operator's disable survives a re-sync;
`test_update_changed_is_called_after_bulk_edits`.

**Configurable, not hard-coded.** `jobs.<name>.schedule` and `jobs.<name>.enabled` in the settings
registry; `CELERY_TIMEZONE` from env.

---

## 7. The run record   — **Tier 1 · Core**

**What.** Every execution of every job — periodic, on-demand, manual — writes one `core_job_run`
row, from `queued` to a terminal state, by a recorder that is structurally unable to break the job.

**Why.** The broker deletes successes and the failed-task view only shows what failed; a job that was
never picked up appears in neither. A real incident: thousands of queued jobs — over a hundred of
them real emails to real people — sat unprocessed for months while the only failure view was empty.

**Rules.**
- **Recorded from Celery signals** (`after_task_publish` → `queued`, `task_prerun` → `started`,
  `task_success`/`task_failure`/`task_retry`/`task_revoked` → terminal or `retrying`,
  `task_unknown`/`task_rejected` → `dead`), and directly by `run_worker` through the same recorder.
- **Self-guarded: the recorder never raises.** Every handler is wrapped; a recording failure is
  logged at WARNING and dropped. Monitoring that can crash the thing it monitors is worse than none.
- **A separate connection.** The recorder writes through a second database alias (`"monitor"`, the
  same database, `ATOMIC_REQUESTS=False`) so a queued row is not rolled back with the caller's
  transaction, and a failed job's rollback does not erase the record of its failure.
- **Duration is measured in the worker with `time.perf_counter()`**, keyed by task id in process
  memory at `task_prerun` and popped at `task_postrun`. Not from the row's timestamps: a real
  incident showed database timestamps bracketing the recorder's own writes and inflating a 13 ms job
  to 156 ms. Queue wait is `started_at − queued_at` and is reported separately.
- **The error is `type + message`, never a traceback.** Truncated to 2 000 characters and passed
  through the one scrubber ([`OBSERVABILITY.md`](OBSERVABILITY.md)); tracebacks go to error
  tracking, where access is controlled. A traceback in an operator-visible table leaks locals.
- **The monitoring queue is not recorded**, or the recorder's own housekeeping floods the monitor.
- **Retention is asymmetric:** completed runs 14 days, failed runs 90 — failures are evidence —
  through the retention engine ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)), with a row cap, because
  this table grows fastest exactly when something is wrong.

**Django + Next shape.**

| Column | Type | Notes |
|---|---|---|
| `id` | `BigAutoField` | returned to callers of on-demand jobs |
| `task_id` | `CharField(64)`, unique | Celery's id; `run_worker` generates one |
| `job_name` | `CharField(150)`, indexed | the registry name; also recorded for unknown tasks |
| `queue` | `CharField(64)` | |
| `trigger` | `TextChoices`: `schedule` · `on_demand` · `manual` · `retry` | |
| `status` | `TextChoices`: `queued` · `started` · `succeeded` · `failed` · `retrying` · `revoked` · `dead` | `dead` = unknown/unregistered task name |
| `attempt` | `PositiveSmallIntegerField` | |
| `queued_at` / `started_at` / `finished_at` | `DateTimeField` (null) | |
| `duration_ms` | `PositiveIntegerField` (null) | perf_counter, in-worker |
| `count` / `unit` | `IntegerField` / `CharField(32)` | the job's return value |
| `error_type` / `error_message` | `CharField(200)` / `TextField` (≤2 000, scrubbed) | |
| `actor` | FK user, `SET_NULL`, null | who triggered a manual/on-demand run |
| `idempotency_key` | `CharField(200)`, `""` default | § 13 |

Indexes: `(job_name, -started_at)`, `(status, queued_at)` (for "oldest queued"). API:
`GET /api/jobs/` (registry + health, `core.jobs.view`), `GET /api/jobs/runs/?job=&status=`,
`GET /api/jobs/runs/<id>/`, `POST /api/jobs/<name>/run/` (`core.jobs.run`, audited). Next: a Job
Monitor page under settings — one row per registered job with health badge, last run, next due,
last error; drill-down to runs.

**Enforced by.** `tests/core/jobs/test_recorder.py`:
`test_a_recorder_failure_never_fails_the_job` (make the monitor alias raise; the job still succeeds),
`test_a_rolled_back_job_still_records_its_failure`,
`test_duration_comes_from_perf_counter_not_timestamps`,
`test_error_message_is_scrubbed_and_has_no_traceback`, `test_monitoring_queue_is_not_recorded`.

**Configurable, not hard-coded.** `jobs.retention.completed_days` (14), `jobs.retention.failed_days`
(90), `jobs.retention.max_rows`.

---

## 8. Health, liveness and the doctors   — **Tier 1 · Core**

**What.** A health state per job, a liveness signal per queue, and two doctors that answer "is the
background system actually working?" from the command line.

**Why.** The failure mode the monitor exists for is **a worker that is not running**, and that looks
identical to a healthy, quiet system. Every signal below is designed to make those two
distinguishable.

**Rules — the per-job health state, in precedence order:**

| State | Condition |
|---|---|
| `disabled` | the job is off (`jobs.<name>.enabled` false) |
| `never_run` | enabled, and no run has ever been recorded — **distinct from failing**; a new deploy is not an incident, but a job that has *never* run a week later is |
| `failing` | the most recent terminal run failed |
| `overdue` | the last *start* is older than 3 × the interval (or the previous cron fire + `stale_after_minutes`) |
| `ok` | everything else |

- **`worker_seen_recently`** is reported alongside: any run started (on any queue the worker consumes)
  within the window. It is the one signal that separates "quiet" from "dead".
- **Liveness of a queue = recent activity OR an empty queue.** Short-lived or autoscaled workers mean
  a process check would read "dead" between runs; an idle queue with no backlog is healthy by
  definition. A queue is **stalled** when its oldest queued run is older than
  `operations.queue.stall_threshold_minutes`.
- **Dead tasks are detected, not guessed.** A message whose task name is not registered can only
  fail; `task_unknown` records it as `dead`, and the queue doctor also peeks queued messages and
  checks their names against the registry.
- **Health feeds incidents, not a stream of alerts.** A stalled queue opens one incident and recovers
  once ([`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md) § 17).

**Django + Next shape.**

```
manage.py queue_doctor [--json] [--stale-older-than 7d] [--export stale.csv]
manage.py schedule_doctor [--json]
```

`queue_doctor` reports, exiting non-zero on any finding: stalled queues (oldest queued age), queues
with no recent consumer, unregistered task names in queued messages, `visibility_timeout <=
max(time_limit)`, `prefetch_multiplier > 1` with late acks, eager mode outside tests, and the result
backend mismatch of § 3. `schedule_doctor` reports every registered periodic job with its schedule,
last start, next due, state, and every `PeriodicTask` the registry does not own. Both are also
exposed as system-health checks ([`OBSERVABILITY.md`](OBSERVABILITY.md)) and share one
implementation with the Job Monitor page — the CLI and the UI are two renderings of the same
function.

**Enforced by.** `tests/core/jobs/test_health.py` — one test per state and per precedence pair
(`disabled` beats `failing`, `never_run` beats `overdue`), `test_empty_queue_is_alive`,
`test_quiet_but_dead_worker_is_not_ok`; `test_queue_doctor_exits_nonzero_on_unregistered_task`.

**Configurable, not hard-coded.** `operations.queue.stall_threshold_minutes` (15),
`operations.queue.worker_seen_window_minutes` (15), `operations.queue.depth_alert_threshold`.

---

## 9. Locks   — **Tier 1 · Core**

**What.** Three lock primitives, one for each shape of "only one at a time", and a rule for each
about what happens when the lock store is down.

**Why.** A real incident: a scheduler's "without overlapping" guard held a 24-hour lock by default;
a worker killed mid-run never released it, and the job did not run again for a day. Another: a lock
released with a plain `DELETE` removed the *successor's* lock when a slow first run finished late,
and two runs overlapped anyway.

**Rules.**

| Primitive | Use for | Mechanism |
|---|---|---|
| `single_flight(key, ttl_ms)` | periodic jobs, "refresh now" buttons, evaluators | Redis `SET key token NX PX ttl`; release by Lua compare-and-delete on the token |
| `advisory_xact_lock(key)` | serialising a critical section that is already inside a DB transaction (collectors, per-account money moves) | `pg_try_advisory_xact_lock(hashtext(key))` — released at commit/rollback |
| Row claim | "one worker processes this row" | `select_for_update(skip_locked=True)` + stamp a claim column + **commit before enqueueing** |

- **TTL ≤ the work's `time_limit` + a small margin. Never 24 hours.** A lock that outlives its holder
  is an outage with a timer on it. Long work renews (`extend(token, ttl)`) between batches.
- **Release checks the token.** A plain `DEL` (or `cache.delete`) after `cache.add` deletes whoever
  holds the lock *now*, which after a timeout is someone else.
- **Session-level advisory locks are forbidden.** Behind a transaction-pooling PgBouncer the
  "session" is shared by strangers; only the `_xact_` variants are safe.
- **Claim, commit, then dispatch.** Without committing the claim first, a task still waiting in the
  queue lets the next sweep re-dispatch the same row — a real incident produced a double refund.
- **Direction when the store is unavailable is declared per call:** `on_unavailable="skip"` (the
  default — an evaluator that cannot lock skips this cycle) or `"proceed"` only for work that is
  itself idempotent. Silence is not a choice.
- **Locks need the shared cache.** On a per-process cache a lock guards one process — `dbx.E005`
  ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 17.4) already refuses that in production.

**Django + Next shape.** `core/locks.py`. The Redis client is built lazily from `LOCKS_REDIS_URL`
(defaulting to the cache's URL) — it does not reach into the cache backend's private client. On
SQLite (development, [ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md)) `advisory_xact_lock`
is a no-op with a one-time warning, and `select_for_update` is already a no-op; both are acceptable
for a single developer process and are one reason CI must run on PostgreSQL.

```python
with single_flight(f"job:{spec.name}", ttl_ms=(spec.time_limit + 30) * 1000) as got:
    if not got:
        return record_skip(spec, reason="already_running")
    execute(spec, ctx)
```

**Enforced by.** `tests/core/test_locks.py`: `test_release_does_not_delete_a_successors_lock`,
`test_ttl_expires_after_a_killed_holder`, `test_unavailable_store_skips_by_default`;
`dbx.jobs.E020` — a `single_flight` TTL above `jobs.max_lock_ttl_seconds`;
`tests/architecture/test_no_session_advisory_locks.py` — `pg_advisory_lock(` / `pg_try_advisory_lock(`
anywhere.

**Configurable, not hard-coded.** `LOCKS_REDIS_URL`; `jobs.max_lock_ttl_seconds` (3 600 — a cap, not a
default).

---

## 10. Retry and backoff   — **Tier 1 · Core**

**What.** One retry policy module, used by tasks, the outbox, webhooks and the HTTP client — instead
of three styles (framework auto-retry, hand-written `self.retry`, database-driven attempts) with
three different backoff shapes and no jitter.

**Why.** `autoretry_for=(Exception,)` retries a validation error five times. Backoff without jitter
makes every client that failed together retry together. And on a Redis broker a task scheduled with
a countdown longer than the visibility timeout is redelivered while it waits — a two-hour retry
countdown becomes two deliveries.

**Rules.**
- **Classify, then retry.** Retry only transient failures: `ProviderUnavailable`,
  `ProviderRateLimited`, `OperationalError`, connection resets (§ 20). A permanent failure
  (`ProviderClientError`, `ValidationError`, `PermissionDenied`) fails immediately and says why.
- **Exponential with full jitter, capped:** `delay = random(0, min(cap, base × factor^(n−1)))`.
- **Honour `Retry-After`** when the upstream sends it, capped at the policy's `cap`.
- **Delays beyond the broker's visibility timeout are stored, not scheduled.** The row gets
  `next_attempt_at`; a drainer picks it up. Broker countdowns are for short delays only.
- **Every retry loop is bounded** (`max_attempts`) and ends in a terminal state a human can see —
  `failed`/`dead_letter`, never "retrying forever".

**Django + Next shape.** `core/jobs/retry.py`:

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_seconds: float = 30
    factor: float = 4
    cap_seconds: float = 3600
    def next_delay(self, attempt: int, retry_after: float | None = None) -> float | None: ...
    def is_transient(self, exc: BaseException) -> bool: ...
```

**Enforced by.** `tests/core/jobs/test_retry.py` (delays grow, are jittered, respect the cap and
`Retry-After`, stop at `max_attempts`); `tests/architecture/test_no_blanket_autoretry.py` —
`autoretry_for=(Exception,)` or `(BaseException,)` anywhere; `dbx.jobs.E021` — a policy used with
broker scheduling whose `cap_seconds` exceeds the visibility timeout.

**Configurable, not hard-coded.** Policies are named constants per use (`WEBHOOK_RETRY`,
`OUTBOX_DEFAULT_RETRY`) with settings-registry overrides for the operator-relevant ones
(`webhooks.max_attempts`).

---

## 11. Reconcilers   — **Tier 2 · Core**

**What.** A base class for the job that compares our state with an external system's and repairs,
advances or flags the difference.

**Why.** A real incident class: resources created with an asynchronous provider status stayed
`PENDING` forever because nothing ever went back to ask. The fix each time was a reconciler; the
lesson was that **the reconciler is part of the state, not an afterthought**.

**Rules.**
- **Every asynchronous or `PENDING_*` state has a reconciler**, declared next to the state. Adding a
  transient state without one fails a test.
- **Reconcilers cover child tables**, not only the parent — a parent marked `active` with a child
  stuck `provisioning` is the same bug one join away.
- **Commit incrementally.** Per-row savepoint and commit; on `SoftTimeLimitExceeded`, commit what is
  done and return. A reconciler that commits at the end loses all its progress to the time limit it
  will eventually hit.
- **Bounded batches, and say so.** "Batch limit reached; N remain" is logged and returned — a cap is
  never mistaken for "clean".
- **Skip doomed calls.** A target that is backed off (§ 19) or known-unreachable is skipped this
  cycle, not called and timed out.
- **The fail-closed decision rule:** the provider says *gone* → act; the provider says *it exists
  and differs* → mutate nothing and record a **finding** for a human; the provider cannot answer →
  skip. Never fall back to a broader credential to "just check".
- **Findings, not auto-destruction and not alerts.** Drift is upserted as one open finding per
  `(kind, object)` into the findings queue ([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md)), bumped on
  each sighting, auto-cleared when the state converges.
- **A resumable reconciler keeps its cursor in `core_job_state`**, a database row — not the cache,
  which a deploy clears.

**Django + Next shape.**

```python
class Reconciler:
    name: str                  # also the JobSpec name
    batch_size: int = 50
    commit_every: int = 1
    def queryset(self) -> QuerySet: ...        # rows needing attention, ordered for a stable cursor
    def reconcile(self, obj) -> Outcome: ...   # FIXED | UNCHANGED | DRIFT(finding) | SKIP(reason)
    def give_up(self, obj, reason) -> None:    # default: record a finding
        findings.upsert(kind=f"{self.name}.gave_up", obj=obj, details={"reason": reason})
```

`core_job_state(name unique, cursor JSON, last_success_at, updated_at)` is shared by reconcilers and
digests ([`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md) § 10).
`registry.reconcilers.register(ReconcilerSpec(model="app.Model", states=["pending_provision"],
reconciler=...))` generates the `JobSpec`.

**Enforced by.** `tests/architecture/test_every_pending_state_has_a_reconciler.py` — every
`TextChoices` member whose value matches the declared transient pattern (`pending_*`, `*_ing`, or an
explicit `TRANSIENT_STATES` tuple on the model) is covered by a registered reconciler; fails on an
empty universe. `tests/core/jobs/test_reconciler_base.py` —
`test_soft_time_limit_banks_progress`, `test_cap_is_reported_not_silent`,
`test_exists_and_differs_mutates_nothing`.

**Configurable, not hard-coded.** `reconcilers.<name>.batch_size`, `reconcilers.<name>.stale_after_minutes`.

---

## 12. The transactional outbox   — **Tier 1 · Core**

**What.** One generic outbox table and one drainer, with pluggable per-topic handlers and an explicit
delivery-semantics flag — replacing the hand-rolled copies every mature codebase grows (one per
emailer, notifier, provisioning step and compliance feed), each with its own states and backoff.

**Why.** A side effect decided in a transaction and executed outside it has two failure windows: it
runs and the transaction rolls back, or the transaction commits and the process dies before it runs.
The outbox closes both by making "we owe the world this message" a row committed with the change.
Hand-rolled copies disagree on the one question that matters — **what happens when a lease expires
mid-send** — and so some resend (duplicates to customers) and some silently drop.

**Rules.**
- **Enqueue in the same transaction as the business change.** `outbox.enqueue()` asserts
  `connection.in_atomic_block` and raises otherwise; an outbox row written after commit is just a
  slower `.delay()`.
- **A unique `dedupe_key` per logical message** (`f"{topic}:{aggregate}:{version}"`), inserted with
  `ON CONFLICT DO NOTHING` semantics — enqueueing twice is a no-op, not a duplicate send.
- **Payloads are ids**, like task payloads (§ 4). The handler re-reads current state.
- **Claim with `SELECT … FOR UPDATE SKIP LOCKED LIMIT n`** over due rows, set `leased_until`,
  `locked_by`, `attempts += 1`, **commit**, then send outside any transaction. Per-row result commit.
- **Re-validate at claim time.** The handler checks business state is still true (invoice still
  unpaid, contact not deleted, recipient not on the suppression list) and returns `SKIPPED(reason)`
  otherwise. Suppression is checked when sending, not when enqueuing — the list changes in between.
- **Each topic declares its semantics:**
  - `at_least_once` — a stale lease returns the row to `retry`. For receivers that dedupe (webhooks
    with a delivery id, idempotent upstream APIs).
  - `at_most_once` — a stale lease moves the row to `unknown`. For anything a human receives
    (email, SMS, chat) where a duplicate is worse than a gap.
- **`unknown` is terminal and human-owned.** A timeout after the provider may have accepted the
  message is `unknown`, **never an immediate blind retry**. Each `unknown` row opens a finding with
  the evidence; a human resolves it (mark sent, or resend deliberately).
- **Intentionally unconfigured is `skipped`, not dead-lettered.** A handler raising
  `ProviderNotConfigured` for a pipeline the product has not switched on records `skipped` — a
  dormant integration must not fill the dead-letter view.
- **Never persist raw provider errors.** They can carry recipients, URLs or tokens. Store an error
  `code` and a scrubbed, truncated message.
- **Stale-lease recovery is its own sweep** (every few minutes), separate from the drainer, so a
  wedged drainer does not also stop recovery.
- **Metrics per topic and status**, pre-initialised at zero ([`OBSERVABILITY.md`](OBSERVABILITY.md)),
  plus a gauge of the oldest due row's age per topic — the number that says "the outbox is stuck"
  before anyone complains.

**Django + Next shape.**

| Column | Type | Notes |
|---|---|---|
| `id` | `BigAutoField` | |
| `topic` | `CharField(100)`, indexed | registered, e.g. `webhooks.deliver`, `notifications.dispatch` |
| `dedupe_key` | `CharField(255)`, **unique** | |
| `payload` | `JSONField` | ids and scalars only |
| `status` | `TextChoices`: `pending` · `leased` · `retry` · `sent` · `skipped` · `failed` · `unknown` | `failed` = dead letter |
| `attempts` / `max_attempts` | `PositiveSmallIntegerField` | |
| `next_attempt_at` | `DateTimeField`, indexed | due = `status in (pending, retry) and next_attempt_at <= now` |
| `leased_until` / `locked_by` | `DateTimeField` (null) / `CharField(100)` | worker hostname + pid |
| `last_error_code` / `last_error_message` | `CharField(100)` / `TextField` (≤1 000, scrubbed) | |
| `result_ref` | `CharField(255)` | provider message id, when accepted |
| `created_at` / `sent_at` | `DateTimeField` | |

Indexes: `(status, next_attempt_at)`, `(status, leased_until)`.

```python
registry.outbox_topics.register(OutboxTopic(
    topic="notifications.email", handler="core.notifications.transports.email.deliver",
    semantics="at_most_once", retry=RetryPolicy(max_attempts=5, base_seconds=60, factor=5),
    lease_seconds=60, queue="outbox"))
```

A handler returns `Outcome.SENT(ref) | RETRY(after=None) | FAILED(code) | SKIPPED(reason) |
UNKNOWN(evidence)` and never raises; an unexpected exception is converted to `RETRY` for
`at_least_once` topics and `UNKNOWN` for `at_most_once` ones. After enqueue, an `on_commit` kick
publishes `outbox.drain(topic)` for latency; a beat drainer every 30 s is the guarantee.

**Enforced by.** `tests/core/outbox/test_outbox.py`:
`test_enqueue_outside_a_transaction_raises`, `test_enqueue_twice_is_one_row`,
`test_rollback_leaves_no_row`, `test_two_drainers_never_claim_the_same_row` (PostgreSQL only — marked
and run in CI), `test_stale_lease_is_unknown_for_at_most_once_and_retry_for_at_least_once`,
`test_suppressed_recipient_is_skipped_at_claim_time`, `test_provider_error_body_is_not_persisted`,
`test_not_configured_is_skipped_not_failed`. `dbx.jobs.E030` — a registered topic with no
semantics, or a handler path that does not import.

**Configurable, not hard-coded.** Per topic: `outbox.<topic>.batch_size`, `.lease_seconds`,
`.max_attempts`; global `outbox.drain_interval_seconds` (30).

---

## 13. The idempotent run ledger   — **Tier 1 · Core**

**What.** A ledger for "this action, for this key, happens once", enforced by the database:
`core_idempotent_run` with a **partial unique constraint on `(action_key, idempotency_key)` where the
key is not empty**. Used by jobs triggered with a key, automation actions, imports, and any service
that must not double-apply.

**Why.** Check-then-insert races: two concurrent runs both see "not done" and both do it. A unique
index cannot race. And a ledger row per attempt is how "did this already happen, and how did it end?"
is answered in one indexed lookup.

**Rules.**
- **Insert first, then act.** `IntegrityError` on insert means someone else owns this key — return
  their row, never run again.
- **Same key, different input is a conflict**, not a replay: the row stores an input digest
  (SHA-256 of canonical JSON), and a mismatch raises `IdempotencyConflict` (→ `409`).
- **Status-gated replay.** A replay of a `succeeded` run returns its output; of a `running` run
  returns "in progress" (`202`); of a `failed` run is allowed only if the action declares
  `retry_on_same_key=True`; of a `cancelled` run says "use a new key". **Never report a success
  that did not happen.**
- **Empty key means "not idempotent"** and is excluded from the constraint by its condition, which is
  why the constraint is partial.
- **The HTTP `Idempotency-Key` header is a caller of this ledger**, not a second mechanism — its
  request-fingerprinting and lock ordering are specified in [`API_PLATFORM.md`](API_PLATFORM.md).

**Django + Next shape.**

```python
class IdempotentRun(models.Model):
    action_key = models.CharField(max_length=150)
    idempotency_key = models.CharField(max_length=200, blank=True, default="")
    input_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices)   # running|succeeded|failed|cancelled
    attempt = models.PositiveSmallIntegerField(default=1)
    output = models.JSONField(null=True); error_code = models.CharField(max_length=100, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    started_at = models.DateTimeField(auto_now_add=True); finished_at = models.DateTimeField(null=True)
    class Meta:
        db_table = "core_idempotent_run"
        constraints = [models.UniqueConstraint(fields=["action_key", "idempotency_key"],
                       condition=~Q(idempotency_key=""), name="core_idem_run_once")]
```

`core.idempotency.run_once(action_key, key, input, fn) -> RunResult`.

**Enforced by.** `tests/core/test_idempotency.py`: `test_concurrent_run_once_executes_fn_once`
(PostgreSQL, two threads), `test_same_key_different_input_conflicts`,
`test_replay_of_failed_run_does_not_report_success`, `test_empty_key_is_not_deduplicated`.

**Configurable, not hard-coded.** Retention of ledger rows per action via the retention engine.

---

## 14. Pushing to an external system once: control row + attempt log   — **Tier 2 · Core**

**What.** The shape for "send this invoice to the accounting system", "create this customer in the
CRM", "register this device upstream": **one control row** that answers *has it been pushed?* and an
**append-only attempt log** that answers *what happened each time we tried?*

**Why.** Two tempting shapes both fail. One mutable row per object overwritten on every attempt
destroys the history you need when the upstream says "we never got it". An attempt log alone makes
"is it pushed?" a scan with ambiguous answers (three attempts: failed, timed out, succeeded? or
succeeded, then a duplicate?).

**Rules.**
- **The control row is unique per `(object_type, object_id, target)`** and holds the state
  (`pending · pushing · pushed · failed · unknown`) plus the **external reference** the upstream
  returned. `pushed` is terminal.
- **Every attempt appends a row** — request id, attempt number, status code, duration, error code,
  scrubbed message. Attempts are never updated or deleted by application code.
- **Before retrying an ambiguous attempt, ask the upstream** — by our idempotency key if it supports
  one, or by a natural lookup — instead of re-creating. A timeout on create is `unknown`, handled as
  in § 12.
- **Re-pushing a `pushed` object is a deliberate human action** that writes an attempt with
  `reason`, never a side effect of a retry loop.

**Django + Next shape.** An abstract pair in `core/integrations/push.py`:
`ExternalPush(object_type, object_id, target, state, external_ref, last_attempt_at)` and
`ExternalPushAttempt(push FK CASCADE, attempt, started_at, duration_ms, status_code, error_code,
error_message, request_id)`; a product subclasses them per target with its own `db_table`.

**Enforced by.** `tests/core/integrations/test_push.py`: `test_pushed_is_terminal`,
`test_attempts_are_append_only` (the model's `save()` refuses updates), `test_timeout_on_create_is_unknown`.

**Configurable, not hard-coded.** Retry policy per target.

---

## 15. Operational hazards   — **Process**

Rules that are not code but have each caused a real incident.

- **Purge before you wire a worker.** When adding a consumer to a queue that has been silently
  accumulating (§ 5), inspect and export the backlog **first**
  (`queue_doctor --stale-older-than 7d --export stale.csv`), decide what to discard, purge, *then*
  start the worker. A real incident: wiring the missing worker first delivered months-old
  notifications to real people within a minute. The export is the record; stale messages are not
  re-sent.
- **Feature-branch testing on a shared environment:** reverting code is not enough — beat's cached
  schedule and running workers still name the branch's tasks. Re-sync schedules (§ 6) and restart
  workers as part of the revert.
- **A job's first production enable is a change, not a toggle.** For `destructive=True` jobs, run
  `--dry-run` (every destructive job supports one, sharing its cutoff logic with the real run) and
  record the output in the change entry before enabling.
- **Never "fix" a stuck job by raising a lock TTL or a time limit** without finding why it is slow;
  both hide the next occurrence.

---

# Part B — Webhooks

## 16. Outbound webhooks   — **Tier 2 · Core**

**What.** Signed, minimal-payload, self-disabling HTTP callbacks to endpoints registered by API
consumers, delivered from the outbox, with a delivery log, redelivery and a test send. Replaces the
bare `Webhook` + `WebhookDelivery` row in [`DATA_MODEL.md`](DATA_MODEL.md) § 3 (see § 29).

**Why.** "The delivery log with a redeliver button **is** the module" — without it a missed event is
unrecoverable and undiagnosable. And every weakness a webhook system can have has been shipped
somewhere: plaintext secrets, an unsigned timestamp that lets anyone replay a captured delivery,
retries that depend on a broker countdown nobody sweeps, a URL field that happily posts record
contents to an internal metadata service, and endpoints that retry a dead URL forever.

**Rules — ownership and secrets.**
- **An endpoint belongs to an API consumer, not a user** ([`API_PLATFORM.md`](API_PLATFORM.md)).
  An integration must not break because the person who created it left.
- **The signing secret is encrypted, not hashed** — we must reproduce it to sign, so a hash is
  useless and plaintext is a leak. *Hash what you compare, encrypt what you must reproduce, never
  store plaintext.* Generated with `secrets.token_urlsafe(32)`, prefixed from
  `WEBHOOK_SECRET_PREFIX` (default derived from the product slug), **shown once** at creation.
- **Rotation with overlap.** `POST …/rotate-secret/` issues a new secret; for
  `webhooks.rotation_overlap_hours` both are used and the signature header carries both signatures,
  so a receiver can deploy the new secret without dropping deliveries.
- **Creating, re-pointing, rotating or deleting an endpoint is audited** — re-pointing a URL
  redirects data.

**Rules — the catalogue.**
- **Subscriptions are validated against the event catalogue on write.** Unknown events, and an empty
  subscription, are refused. The catalogue is the set of registry events flagged `external=True`
  ([`EXTENSIBILITY.md`](EXTENSIBILITY.md)); an internal event is not a webhook by default.
- **No wildcard subscriptions.** A wildcard consents today to events that do not exist yet and will
  carry data nobody reviewed. New events are opted into explicitly.
- **The catalogue is small and real:** every offered event has at least one emit call site. An event
  in the catalogue that nothing emits is a promise the product does not keep.

**Rules — the payload.**
- **Ids only.** `{"id", "event", "occurred_at", "api_version", "data": {"object": "invoice", "id": "…"}}`.
  The receiver fetches what it is allowed to see through the API with its own token — **one
  permission model instead of two**. A URL typed into a form must never receive record contents.

**Rules — signing and headers.**
- **Signature = HMAC-SHA256 over `"{timestamp}.{raw_body}"`**, sent as `v1=<hex>`. The timestamp is
  *inside* the signed string, so a receiver checking its age defeats replay; an unsigned timestamp
  header protects nothing.
- **Headers** — prefix from `WEBHOOK_HEADER_PREFIX` (default `X-<ProductSlug>-`, never a literal):
  `…-Signature`, `…-Timestamp`, `…-Event`, `…-Delivery` (stable per event × endpoint, so receivers
  dedupe). `User-Agent: <ProductName>-Webhooks/<version>`. The signature header is excluded from the
  stored request snapshot.
- **Custom headers** on an endpoint are allowed from an allowlist only; `Host`, `Authorization`,
  `Cookie`, `X-Forwarded-*` and the signature/timestamp names are refused.

**Rules — the network.**
- **SSRF guard at write and again before every send** (DNS can change between the two — rebinding):
  through `core.http` (§ 18) with the resolved IP pinned.
- **No redirects.** A redirect is the standard way around an allowlist; a `3xx` is a failure.
- **`http(s)` only; `https` only in production** unless `webhooks.allow_http` is explicitly on.
- **Timeout per endpoint**, default 10 s, capped at 30 s.

**Rules — delivery outcomes.**

| Response | Outcome |
|---|---|
| `2xx` | delivered; endpoint's `consecutive_failures` reset to 0 |
| `408`, `425`, `429`, `5xx`, timeout, connection error | retry with backoff (honouring `Retry-After`) |
| `410 Gone` | permanent, and the endpoint is disabled — the receiver said so |
| any other `4xx` | **permanent** — the receiver will say it again; retrying is noise |
| `3xx` | permanent (redirects are not followed) |

- **Backoff ladder** `30 s · 2 min · 10 min · 30 min · 2 h` with jitter, **stored as
  `next_attempt_at`** and driven by the outbox drainer — not a broker countdown (§ 10).
- **Circuit breaker:** after `webhooks.breaker_threshold` consecutive failed *deliveries* (not
  attempts) the endpoint's `disabled_at` is set and its owner is notified
  (`core.webhook_endpoint_disabled`). `is_active` (a human switch) and `disabled_at` (the breaker)
  are **separate columns** — "an admin turned it off" and "it tripped" need different fixes.
  Re-enabling clears the counter.
- **Inactive or disabled endpoints are skipped, not queued.** Queuing for them means a flood on
  re-enable.
- **`send_test`** sends a synthetic `ping` event through the real signing, SSRF and delivery path,
  bypassing subscriptions — "can we reach you, and do you accept our signature?" — and is logged
  with `is_test=True`.
- **`redeliver`** creates a new attempt for an existing delivery with the same `…-Delivery` id.

**Rules — emission.**
- **`webhooks.emit(event, obj)` writes one outbox row in the caller's transaction** (§ 12) and never
  raises into the business action. Fan-out to subscribed endpoints happens in the worker, via an
  indexed subscription table — never by loading all active endpoints and filtering in Python.
- **`emit()` of an event not in the catalogue raises** in tests and `DEBUG` (a programming error)
  and logs at ERROR otherwise, queuing nothing.

**Django + Next shape.**

`core_webhook_endpoint`: `consumer` FK (`CASCADE` — a deleted consumer's endpoints go with it),
`name`, `url`, `secret_ciphertext`, `previous_secret_ciphertext`, `previous_secret_expires_at`,
`timeout_seconds`, `custom_headers` JSON, `is_active`, `disabled_at`, `consecutive_failures`,
`last_delivery_at`, `created_by`/`updated_by` (`SET_NULL`), timestamps.
`core_webhook_subscription(endpoint, event)` unique pair — a real table, so matching is an indexed
join (and works on SQLite, where JSON-contains lookups do not).
`core_webhook_delivery`: `endpoint` FK, `event`, `event_id`, `delivery_id` (unique per endpoint),
`payload` JSON, `status` (`pending · delivered · failed`), `attempts`, `next_attempt_at`,
`response_status`, `response_body` (first 2 000 characters), `duration_ms`, `is_test`,
`delivered_at`, `failed_at`; index `(status, next_attempt_at)`.

Endpoints under `/api/webhooks/` gated by `core.webhooks.view` / `core.webhooks.manage`; the secret
appears in the create and rotate responses **only**. Next: endpoint list with health (last delivery,
failure streak, breaker state), a delivery log with request/response panes and a Redeliver button,
and a "Send test" button on every endpoint.

**Enforced by.** `tests/core/webhooks/`:
- `test_signature_covers_timestamp_and_body` and `test_signature_verifies_with_documented_recipe`
  (the receiver recipe in the docs is executed as a test).
- `test_secret_is_never_returned_after_create` — every serializer that renders an endpoint.
- `test_private_and_loopback_urls_are_refused_at_write` and `…_at_send_after_dns_changes`.
- `test_redirect_is_a_failure`, `test_4xx_is_permanent_and_5xx_retries`, `test_410_disables`.
- `test_breaker_trips_at_threshold_and_reset_clears`, `test_inactive_endpoint_is_not_queued`.
- `tests/architecture/test_webhook_catalogue_has_call_sites.py` — for every `external=True` event,
  an `emit("<name>"` call exists in a non-test, non-webhooks source file; **fails if the scanned
  file set or the catalogue is empty** (a real incident: the equivalent test scanned a directory a
  refactor had removed, and skipped silently forever).

**Configurable, not hard-coded.** `WEBHOOK_HEADER_PREFIX`, `WEBHOOK_SECRET_PREFIX` (env, derived
from the product slug by default); `webhooks.breaker_threshold` (10), `webhooks.max_attempts` (5),
`webhooks.default_timeout_seconds` (10), `webhooks.allow_http` (false),
`webhooks.rotation_overlap_hours` (24), `webhooks.delivery_retention_days` + row cap.

---

## 17. Inbound webhooks   — **Tier 2 · Core**

**What.** One framework for receiving third-party callbacks (payment providers, source control,
e-signature, messaging): a verifier registry, a durable inbox, and tenant-bound ingress.

**Why.** Every provider hand-rolls its check, and the hand-rolled versions fail in the same few ways:
verification that **returns true when the secret is unset**; a signature computed over the *parsed
and re-serialised* body rather than the bytes received; a deduplication claim taken *before* the
signature check, so an attacker can pre-claim delivery ids and suppress real events; a shared secret
in the query string, which lands in every access log; and an exception class mismatch that turned
"invalid signature" into a `422` from the generic handler instead of the intended `400`.

**Rules.**
- **Verify over the raw body, first.** Read `request.body` before any parser touches it; compute the
  HMAC (or the provider's scheme) and compare with `hmac.compare_digest`. Nothing else runs until
  verification passes.
- **Fail closed when the secret is missing** — in every environment. Development uses a development
  secret; it does not skip verification.
- **Timestamp tolerance** where the provider signs one (default 300 s): an old, validly signed
  delivery is a replay.
- **Verify, then dedupe.** Deduplicate by the provider's delivery id only after the signature is
  proven.
- **Money-moving or state-advancing webhooks dedupe in the database**: insert into the inbox with a
  unique `dedupe_key` (`ON CONFLICT DO NOTHING RETURNING id`). A cache-based claim that fails open
  when the cache is down is acceptable only for low-stakes events, and the choice is written on the
  verifier.
- **Acknowledge fast, process later.** Persist → commit → `200` → process asynchronously. Return `5xx`
  only when the event could not be *persisted*; a processing failure is our problem, not a reason to
  make the provider retry. If the enqueue after commit fails, the `received` row is itself the outbox
  and a sweeper re-enqueues it.
- **Per-tenant ingress routing.** When different accounts hold different secrets, the URL carries an
  opaque ingress token (`/api/hooks/<provider>/<ingress_token>/`) that selects the connection whose
  secret verifies — not "try every tenant's secret until one matches".
- **The ingress account must match the record's account.** A tenant knows its own secret and could
  forge a validly signed event for *another* tenant's order id; after verification, the handler
  asserts the referenced record belongs to the connection that received it. A real incident class.
- **Never a secret in the query string.**
- **Minimise what is stored.** Keep an allowlist of fields needed for processing and evidence; never
  the provider's whole body when it carries identity documents, URLs or personal data.
- **Consistent rejection.** Invalid signature → `400` with `code: "invalid_signature"`, from one
  `InvalidSignature` exception the base view catches — not a per-provider `except ValueError`.
- **Public by declaration.** Each ingress route is a `PUBLIC_ROUTES` entry
  ([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 9.2) with a reason, CSRF-exempt, and throttled.

**Django + Next shape.**

```python
# core/webhooks/inbound.py
class Verifier(Protocol):
    provider: str
    def verify(self, raw_body: bytes, headers: Mapping[str, str], secret: str) -> Verified: ...
    def dedupe_key(self, verified: Verified) -> str: ...
    durable_dedupe: bool          # True for money; False documents a fail-open cache claim

class InboundWebhookView(APIView):          # authentication_classes = [], throttle "inbound_webhook"
    def post(self, request, provider, ingress_token): ...   # verify → insert → commit → 200 → enqueue
```

`core_inbound_webhook_event`: `provider`, `connection` (FK to the credential/connection row, null),
`delivery_id`, `dedupe_key` (unique), `event_type`, `payload` JSON (minimised), `status`
(`received · processing · processed · failed · ignored`), `attempts`, `received_at`,
`processed_at`, `error_code`. `registry.inbound_webhooks.register(verifier, handler)`.

**Enforced by.** `tests/core/webhooks/test_inbound.py`:
`test_missing_secret_rejects`, `test_signature_is_over_raw_bytes_not_reparsed_json`,
`test_duplicate_delivery_is_processed_once`, `test_dedupe_is_not_claimed_before_verification`,
`test_old_timestamp_is_rejected`, `test_cross_tenant_reference_is_rejected`,
`test_invalid_signature_is_400_for_every_registered_verifier` (parametrised over the registry —
fails on an empty registry once any provider is installed). `dbx.hooks.E001` — an inbound route
missing from `PUBLIC_ROUTES`.

**Configurable, not hard-coded.** `webhooks.inbound.timestamp_tolerance_seconds` (300), throttle rate
`inbound_webhook`, per-provider secrets in the credential store (§ 26).

---

# Part C — Talking to other systems

## 18. The SSRF-safe HTTP client   — **Tier 1 · Core**

**What.** `core.http` — the only way application code makes an outbound HTTP request. A factory that
returns a configured `httpx.Client` for a named **purpose**, with SSRF protection, IP pinning,
timeouts, retry, redaction and the non-production guard (§ 27) built in.

**Why.** Every URL a user, tenant or admin can type — webhook targets, notification channels, image
imports, SMTP hosts, logo URLs, custom integrations — is a request our server makes into our own
network on their behalf. Validating the URL once and then letting the HTTP library resolve it again
leaves a window in which DNS answers differently (rebinding). And a client with no timeout turns one
dead partner into a worker pool that never returns.

**Rules — address safety (for any purpose whose URL is not a fixed, reviewed constant).**
- **Schemes:** `https` (and `http` only where the purpose allows it). No `file`, `ftp`, `gopher`.
- **No userinfo** (`https://user:pass@host`) and a host is required.
- **Resolve every A and AAAA record** and require **every** address to be globally routable
  (`ip.is_global`), refusing loopback, private, link-local, CGNAT, multicast, reserved, unspecified
  and benchmark ranges. **Unwrap embedded IPv4** first — IPv4-mapped IPv6, NAT64 prefixes, 6to4 and
  Teredo — or a private address hides inside a public-looking IPv6 literal.
- **A resolution failure is unsafe**, not "try anyway".
- **Pin the vetted IP.** The transport connects to the address that passed the check, preserving the
  `Host` header and setting the TLS server name (httpx's `sni_hostname` request extension) so
  certificate verification still checks the real hostname.
- **Redirects off by default.** A purpose that must follow them re-validates and re-pins every hop,
  with a hop limit.
- **Display-only URLs** (a logo link that is rendered, never fetched) go through
  `validate_display_url()` — `https` only, no DNS lookup — and are never passed to the client.
- **SMTP and other non-HTTP egress** to a user-configurable host resolve, check and connect to the
  pinned address the same way; resolving then connecting by hostname leaves the same window.

**Rules — behaviour.**
- **Timeouts always.** Connect and read timeouts are required arguments with purpose defaults; `None`
  is refused.
- **Response size cap.** Bodies are streamed and cut at `max_response_bytes`; a partner returning a
  gigabyte must not become our out-of-memory.
- **Retry only idempotent methods** (or requests carrying an idempotency key), with the § 10 policy
  and `Retry-After` honoured.
- **No cookie jar.** A session cookie from one tenant's upstream must never ride along on the next
  tenant's request through a pooled client.
- **Redaction.** Logged requests show method, host, path, status, duration and purpose; `Authorization`,
  cookies and query parameters matching the scrubber's secret patterns are masked
  ([`OBSERVABILITY.md`](OBSERVABILITY.md)).
- **Pools are per process, per purpose, per host**, created lazily (fork safety, § 3) and closed on
  worker shutdown; keyed per host so one wedged partner cannot consume every connection.
- **Bounded concurrency** for fan-out: `core.http.map(purpose, requests, max_workers=…)` sized below
  the remote's pool, never an unbounded thread per target.

**Django + Next shape.**

```python
# core/http/__init__.py
def client(purpose: str) -> httpx.Client: ...          # purpose registered with its policy
registry.http_purposes.register(HttpPurpose(
    name="webhooks.deliver", user_controlled_urls=True, allow_http=False, follow_redirects=False,
    connect_timeout=5, read_timeout=10, max_response_bytes=64_000, retry=None))
registry.http_purposes.register(HttpPurpose(
    name="payments.api", fixed_hosts=("api.payments.example",), connect_timeout=5, read_timeout=20,
    retry=RetryPolicy(max_attempts=3)))
```

`fixed_hosts` purposes skip DNS vetting but are allowlisted: a request to any other host is refused.
The frontend's server-side fetches driven by a request header follow the same rules through its own
helper ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)); the PDF renderer's no-network URL fetcher is
specified in [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md).

**Enforced by.**
- `tests/core/http/test_ssrf.py` — a table of addresses (loopback v4/v6, `169.254.169.254`, RFC 1918,
  CGNAT, `::ffff:10.0.0.1`, NAT64 and 6to4 forms of private addresses, a hostname with one public and
  one private record) all refused; `test_resolution_failure_is_refused`;
  `test_connection_goes_to_the_pinned_ip` (a resolver that answers differently the second time);
  `test_redirect_is_not_followed`; `test_userinfo_is_refused`.
- `tests/architecture/test_outbound_http_goes_through_core_http.py` — imports of `requests`, `httpx`,
  `urllib.request`, `http.client`, `smtplib` and every provider SDK listed in `OUTBOUND_SDK_MODULES`
  outside `core/http/`, `core/mail/` and `*/adapters/` fail. Allowlist with a reason per entry.
- `dbx.http.E001` — a purpose with no timeout, or with `user_controlled_urls=True` and
  `follow_redirects=True` without `revalidate_redirects=True`.

**Configurable, not hard-coded.** Per purpose: timeouts, size cap, retry — overridable as
`http.<purpose>.read_timeout` etc. in the settings registry. `OUTBOUND_SDK_MODULES` is a list in
`core/http/policy.py` that modules extend when they add an SDK.

---

## 19. Per-target circuit breaking and backoff   — **Tier 2 · Core**

**What.** A model mixin for any record that represents a remote target a sweep calls repeatedly
(a device, a partner account, a webhook endpoint, a feed source), giving it exponential backoff after
consecutive failures.

**Why.** A real incident: one unreachable target in a fleet sweep multiplied its timeout by the fleet
size on every run, until the sweep never finished within its schedule and healthy targets went stale
too.

**Rules.**
- **Backoff starts after N consecutive failures** (default 3), then doubles — 1 h, 2 h, 4 h… capped
  at 24 h. A single blip does not bench a target.
- **Scheduled sweeps skip targets whose `next_attempt_at` is in the future.** A human-triggered
  refresh **ignores** the backoff — the person is asking precisely because they fixed something.
- **Success resets** the count and clears `next_attempt_at`.
- **The breaker state is visible**: "backed off until 14:20 after 5 failures (timeout)" on the
  target's page, not only in logs.

**Django + Next shape.**

```python
class CircuitBreakerMixin(models.Model):
    failure_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=100, blank=True, default="")
    def record_failure(self, code: str) -> None: ...
    def record_success(self) -> None: ...
    class Meta:
        abstract = True
# queryset helper: Target.objects.due_for_sweep()
```

**Enforced by.** `tests/core/test_circuit_breaker.py`: threshold, doubling, cap, reset,
`test_manual_refresh_ignores_backoff`.

**Configurable, not hard-coded.** `breaker.<model_label>.threshold`, `.base_minutes`, `.cap_hours`,
with global defaults `breaker.default.*`.

---

## 20. Provider errors and their HTTP mapping   — **Tier 1 · Core**

**What.** One exception hierarchy every adapter raises, and one mapping — in the DRF exception
handler — from those exceptions to our own responses and the error envelope
([`API_DESIGN.md`](API_DESIGN.md) § Errors, [`API_PLATFORM.md`](API_PLATFORM.md)).

**Why.** Without it every module hand-rolls `if resp.status_code in (401, 403)` and they disagree.
The expensive disagreement: **passing an upstream `401` straight through tells our frontend that
*our* session is invalid, and it signs the user out** — for a partner's expired key. Nine copies of
the mapping, each with its own test, is what the absence of this section looks like.

**Rules.**

| Adapter raises | Meaning | Our response |
|---|---|---|
| `ProviderAuthError` | upstream `401`/`403` — **our** credential is bad | **`502`** `upstream_auth_failed`; the credential is marked bad (§ 26) |
| `ProviderRateLimited` | upstream `429` persisting after one bounded retry | **`503`** `upstream_rate_limited` + `Retry-After` |
| `ProviderUnavailable` | upstream `5xx`, timeout, connection error | `502` `upstream_unavailable` (`504` for a timeout) |
| `ProviderClientError` | other upstream `4xx` — the request was wrong | the **same status** (`400/404/409/422`) with a **sanitised** detail |
| `ProviderResponseError` | 2xx but malformed / contract violated | `502` `upstream_bad_response` |
| `ProviderNotConfigured` | the integration is not set up | `503` `integration_not_configured` |
| `OutboundBlocked` | the non-production guard refused it (§ 27) | `423` `blocked_locally` |

- **Adapters never let a raw library exception escape** (`httpx.ReadTimeout`, an SDK's own error);
  they translate at the boundary.
- **Detail passed through is sanitised**: an upstream message is included only from a field the
  adapter names, truncated, and scrubbed — never the upstream body wholesale.
- **Never log a token**, a signed URL or a request body in the error path.
- **Bounded auth retry.** A cached token that gets a `401` is refreshed and the call retried
  **exactly once**; a second `401` is `ProviderAuthError`. A `429` is retried once after
  `min(Retry-After, cap)`, then raised.

**Django + Next shape.** `core/providers/errors.py` (the hierarchy, each carrying `provider`,
`upstream_status`, `code`, `safe_detail`, `retry_after`); `core/api/exceptions.py` gains one branch
for `ProviderError`. The frontend's typed errors ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md))
treat `502/503` with an `upstream_*` code as "the partner is having trouble", distinct from our own
outage.

**Enforced by.** `tests/core/providers/test_error_mapping.py` — one parametrised table covering every
row above; `test_upstream_401_never_becomes_401`. `tests/architecture/test_no_hand_rolled_status_mapping.py`
— `status_code in (401, 403)` / `== 401` outside `core/providers/` and adapters.

**Configurable, not hard-coded.** `providers.rate_limit_retry_cap_seconds` (10).

---

## 21. Caching external lookups   — **Tier 1 · Core**

**What.** A rule and a helper: read caches store **hits only**.

**Why.** A real incident: a "contact not found" answer from a partner was cached for five minutes;
the salesperson created the contact 57 seconds later and the application kept insisting it did not
exist — and because the application was not making the call at all, there was no request to inspect.

**Rules.**
- **Misses, empty results and errors are never cached** — timeouts, `401/403`, `404`, `5xx`,
  unreachable.
- **`cache.get_or_set` is the wrong helper for a read that can fail**; it caches whatever the
  callable returns.
- **Measure before caching.** A cache on an external read needs a stated reason (rate limit, latency
  measured) in the adapter.
- **Bust on write.** An adapter that writes to the upstream invalidates the keys it just made stale.

**Django + Next shape.** `core.cache.cache_hits(key, ttl, fn, *, is_hit=lambda v: bool(v))`.

**Enforced by.** `tests/core/test_cache_hits.py` (a miss, an empty list and an exception each leave
the key unset); `tests/architecture/test_no_get_or_set_in_adapters.py`.

**Configurable, not hard-coded.** TTLs per adapter, as settings where an operator would tune them.

---

## 22. Contract-field validation by ownership   — **Tier 2 · Core**

**What.** How a serializer validates a field depends on **who owns the field's value set**.

**Why.** Three real incidents. An upstream added an enum value; our strict validation `422`d every
request and the failure was blamed on the wrong system for days. An internal proxy silently dropped
a key the frontend sent because the key was not in its serializer, so a feature never received its
input. And an upstream returned a successful, *empty* response; the workflow treated "no objections"
as consent and skipped a whole review stage for two weeks.

**Rules.**

| Field's values are owned by | Validate | On an unknown value |
|---|---|---|
| **The upstream** (their status, their category) | type only | **normalise** to a declared safe default and log — never reject, never length-cap |
| **Us** (our state machine, our enum) | strict membership | reject — a third value is our bug |
| **The caller, as a foreign identifier** | character class / regex and length | reject |

- **Every key a client sends must be declared**; unknown keys are rejected
  ([`API_DESIGN.md`](API_DESIGN.md) § Requests already says so) — including on internal proxy
  endpoints, where silent dropping is most tempting.
- **Absent stays absent.** A field the upstream omitted is not coerced to `""` or `0` or `False`.
- **An empty success is a hold, not consent.** When an upstream answer gates a money-moving or
  client-facing stage, an empty result moves the workflow to `on_hold` and records a finding; it
  never advances.

**Django + Next shape.** `core/api/fields.py`: `UpstreamChoiceField(known=…, normalise_to="unknown")`,
`ForeignIdField(pattern=…, max_length=…)`; `core.providers.results.require_non_empty(result,
hold=...)`.

**Enforced by.** `tests/core/api/test_contract_fields.py`; each adapter test includes "unknown
upstream enum value is normalised" and "empty success holds".

**Configurable, not hard-coded.** Normalisation targets are declared per field in code.

---

## 23. Feeds are additive-authoritative   — **Tier 2 · Core**

**What.** The rules for a feed we publish for another system to mirror, or consume from one — price
lists, catalogues, reference data.

**Why.** A consumer written as a mirror ("make ours equal theirs") would have deleted four blocks of
live published content on its first nightly run, because the feed simply did not mention them.

**Rules.**
- **A feed is authoritative for values, never for deletion.** Absence means "no information", not
  "delete". Withdrawal is explicit (`"active": false`).
- **Per-section hashes** in `meta.section_hashes` — SHA-256 of the canonical JSON of each section,
  keyed by the consumer's own section name — so a consumer re-processes only what changed.
- **`meta` is never hashed** (it carries `generated_at`, which would change every hash nightly). The
  same rule applies to ETags: compute them over content, excluding volatile fields.
- **An empty section publishes no key**, not the hash of `[]` — "we have nothing" and "we are not
  telling you" must differ.
- **Payloads are field allowlists**, never "serialise the model and filter" — a filter admits every
  new column automatically.
- **Adding a key does not bump `SCHEMA_VERSION`; renaming or removing one does.**

**Django + Next shape.** `core/feeds.py`: `FeedSerializer` with `sections()`, `section_hashes()`,
`etag()`; consumer helper `apply_feed(sections, upsert=..., withdraw=...)` with no delete path.

**Enforced by.** `tests/core/test_feeds.py` — changing one item changes exactly one section hash;
`generated_at` changes no hash; an absent item is not deleted by the consumer.

**Configurable, not hard-coded.** Section names and allowlists per feed in code.

---

## 24. The integration registry   — **Tier 2 · Core**

**What.** One record per **relationship** with another system — every inbound route group, outbound
service, scheduled fetch and webhook family — with its direction, auth mechanism, owner and live
usage read through pluggable probes.

**Why.** Three real incidents from not having one: a consumers screen under-reported traffic about
400 : 1 because a second entry point had no consumer row; a feed that priced money had no record
anywhere, so nobody knew it existed until it broke; and a rotated shared key failed silently for
weeks because nothing connected "this key" to "this integration" to "last successful call".

**Rules.**
- **Seeded from code, environment-independent.** `registry.integrations.register(...)`; a module that
  adds an outbound adapter or an inbound route registers the relationship in the same change.
- **Direction and auth are attributes**, not separate tables: `inbound · outbound · scheduled_fetch`,
  `api_token · hmac · oauth · basic · mtls · none`.
- **Usage is read through a probe per source** (request log, webhook deliveries, credential
  `last_used_at`, outbox topic stats, job runs), each one grouped query. A probe returns
  `UsageReading(tracked, untracked_reason, count_24h, count_30d, last_seen_at, recency_only)`.
- **Recency is all-time; counts are windowed.** A real incident: a windowed `MAX(last_seen)` made
  the busiest integration read "never called" because its traffic was just outside the window.
- **Untracked is a first-class state.** No probe, or a probe that raises, degrades that row to
  `untracked` with a reason — it never 500s the page and never reads as "zero calls". Untracked
  relationships are a headline figure with a one-click filter.

**Django + Next shape.** `core_integration(key unique, name, direction, auth_mechanism, owner_module,
description, credential_provider (slug, blank), usage_probe (key), is_active)`;
`registry.usage_probes.register(key, probe)`. `GET /api/integrations/` (`core.integrations.view`).
Next: an Integrations page — table with direction, auth, owner, last seen, 24 h / 30 d counts,
credential verification state (§ 26), and the untracked count at the top.

**Enforced by.** `tests/architecture/test_every_adapter_is_a_registered_integration.py` — every
registered HTTP purpose and inbound verifier maps to an integration key; fails on an empty universe.
`tests/core/integrations/test_usage_probes.py` — a raising probe yields `untracked`; recency is not
windowed.

**Configurable, not hard-coded.** Window lengths `integrations.usage_windows_days` (`[1, 30]`).

---

# Part D — Secrets

## 25. The encryption service   — **Tier 1 · Core**

**What.** `core.crypto` — the one place anything is encrypted at rest: MFA secrets, integration
credentials, webhook signing secrets, provider tokens. A keyring of Fernet keys (`MultiFernet`),
separate from `SECRET_KEY`, with per-purpose derivation, a boot self-test, masking and a rotation
command.

**Why.** The failure modes are specific and each has happened. A key derived from `SECRET_KEY`: the
signing key is rotated after a leak and every stored secret becomes undecryptable. A single key with
no list: rotation is impossible without a flag day. A decrypt helper that **returns the ciphertext
(or `None`) on failure**: a production dump restored into development "worked", every credential
silently read as garbage or as "not set", and nothing looked wrong. A model that decrypts on
attribute access: every `repr()`, log line and debugger session is a disclosure, and "who read this
secret?" becomes unanswerable.

**Rules.**
- **`FIELD_ENCRYPTION_KEYS` is a list, newest first.** New writes use the first key; reads try each.
  This is what makes rotation a procedure rather than an outage — the same shape as Django's
  `SECRET_KEY_FALLBACKS`.
- **Separate from `SECRET_KEY` and `JWT_SIGNING_KEY`**, and never derived from either. Rotating one
  must not brick the others. Boot refuses equality.
- **Distinct per environment.** A production key never exists outside production, so a production
  dump restored elsewhere *cannot* be decrypted — which is the point. Restore handling (wiping
  credential values, re-seeding) is in [`OPERATIONS.md`](OPERATIONS.md).
- **Per-purpose derivation.** The Fernet key actually used is HKDF-SHA256 over the master key with
  `info=f"{product_slug}:{purpose}:v1"`. A ciphertext from the credential store cannot be pasted into
  the MFA column and decrypted there, and one purpose's key can be retired independently. The `info`
  label never changes for a purpose once anything is encrypted under it.
- **Explicit calls only.** `encrypt(plaintext, purpose=…)` / `decrypt(token, purpose=…)` in services.
  Ciphertext lives in a `TextField` named `*_ciphertext`; models expose `set_secret()` and
  `has_secret`, never a decrypting property or a custom field that decrypts on load.
- **Decrypt failure raises `DecryptionError`** with an actionable message ("encrypted under a key not
  in `FIELD_ENCRYPTION_KEYS` — re-enter the secret or restore the key"). It never returns the input,
  never returns `None`, and never logs plaintext or ciphertext.
- **Self-test at boot.** Web and worker processes encrypt and decrypt a probe for each registered
  purpose in `CoreConfig.ready()`; failure refuses to start (a process that cannot encrypt must not
  fall back to storing plaintext).
- **Every encrypted column is registered** (`registry.encrypted_fields.register(model, field,
  purpose)`) so rotation and verification know the complete set.
- **Masking rules:** `None`/empty → `""` ("not set", distinct from short); length < 16 → fully masked
  (`••••••••`); otherwise last 4 visible; undecryptable → the distinct `UNREADABLE` marker. Showing
  the last 4 of an 8-character secret discloses half of it.

**Django + Next shape.**

```
manage.py rotate_encryption [--purpose P] [--batch 500] [--dry-run]   # MultiFernet.rotate, commit per batch, resumable
manage.py rotate_encryption --verify                                   # counts rows per key; 0 under the old key ⇒ safe to drop it
```

Rotation procedure: prepend the new key → deploy → `rotate_encryption` → `--verify` shows zero rows
under the old key → remove it → deploy. `GET /api/system/crypto/` exposes key **fingerprints**
(first 8 hex of SHA-256 of the key id, never the key) and per-key row counts for the system-health
page.

**Enforced by.**
- `dbx.crypto.E001` — `FIELD_ENCRYPTION_KEYS` empty, a placeholder, malformed, or equal to
  `SECRET_KEY`/`JWT_SIGNING_KEY` (outside `APP_ENV=development` an empty list is an error; in
  development a generated key is written by `setup.sh`, never a shared default).
- `dbx.crypto.E002` — the self-test failed.
- `tests/core/test_crypto.py`: round-trip; old-key ciphertext still decrypts after a new key is
  prepended; `test_decrypt_failure_raises_and_never_returns_input`;
  `test_cross_purpose_ciphertext_does_not_decrypt`; masking table.
- `tests/architecture/test_encrypted_columns_are_registered.py` — every model field named
  `*_ciphertext` is registered, and every registration names a real field; fails on an empty
  universe once any secret is stored.
- `tests/architecture/test_no_decrypt_on_access.py` — no `property`/`__getattr__` in `models.py`
  calls `decrypt(`.

**Configurable, not hard-coded.** `FIELD_ENCRYPTION_KEYS` (env, list). Purposes are registered
constants. The HKDF `info` prefix is the product slug.

---

## 26. The encrypted credential store   — **Tier 2 · Core**

**What.** Runtime third-party credentials — mail provider, chat bot token, payment gateway, AI
provider, storage — live in the database, encrypted, edited by an administrator through a form
**generated from a schema**, verified when saved, and read only through a service. `.env` holds only
what bootstraps the process.

**Why.** Keys must be rotatable by an administrator without shell access or a redeploy. And the
incidents: a shared key was rotated upstream and every call failed with `403` for seven weeks,
unnoticed, because **zero of 25 stored credentials had ever been verified**. A "fall back to
production credentials when the local row is missing" convenience meant a developer's laptop wrote
to real production accounts. Reading a live token left no trace.

**Rules — shape.**
- **Four tables:** providers, field schemas, credentials (provider × environment), values (one row
  per field, so only secret fields are encrypted and non-secret ones stay queryable).
- **Providers and schemas are seeded from code** — `registry.credential_providers.register(...)`
  declares fields, types, which are encrypted, validation and help text, **and which setting or
  adapter consumes each field**. A plugin gets an admin form for its provider without writing one.
  `is_system` providers cannot be deleted because code resolves them by slug.
- **Credentials are per environment** (`APP_ENV`), and resolution uses the current environment
  only. **There is no cross-environment fallback** — not as a convenience, not behind a flag.
- **Omitted and blank are the same mistake** on create: a required field left out of the payload is
  refused exactly like `""`. (A real bug: omission skipped validation while blank was rejected.)

**Rules — reading.**
- **List and detail return masked values** (§ 25 masking), with `has_value` per field.
- **Reveal is a separate endpoint** requiring `core.credentials.reveal`, a **recent
  re-authentication** (`RequiresRecentAuth("credential_reveal")`, `423` when stale —
  [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 6.9), and it **writes an audit row every time**.
- **The reveal audit defaults ON when its setting row is missing.** `security.audit.credential_reveal`
  reads as `True` if absent — a missing row must not switch the audit off.
- **Audit where a human reads, not where a machine reads.** Service-layer resolution by adapters is
  not audited per call (thousands a day would bury the one that matters); it updates `last_used_at`.
- **No per-process cache.** Resolution may use the shared cache with a short TTL, busted on save and
  on mark-bad; a per-worker cache is a per-worker staleness window after rotation.

**Rules — liveness.**
- **Probe on save.** `registry.credential_probes.register(provider_slug, probe)`; the probe runs on
  the save request (bounded timeout — the one moment a human is present to read the result) and
  writes `verification_status` = `verified | failed | unverifiable`, with `verification_detail` and
  `last_verified_at`. **No probe ⇒ `unverifiable`, never "ok".** The probe never throws: a partner's
  outage must not lose the admin's save.
- **Re-verify nightly** (a registered job), and surface never-verified and failed credentials on the
  system-health page.
- **Mark bad on upstream `401`.** `ProviderAuthError` (§ 20) sets `verification_status=failed` and
  `marked_bad_until`, and notifies the owner (`core.credential_failed`); resolution of a marked-bad
  credential raises `ProviderNotConfigured` until it is re-saved or the mark expires.

**Rules — how secrets get in.**
- **Environment reads of secret-shaped names happen only in settings.** `os.environ` /
  `os.getenv` / `env(...)` for names matching `KEY|SECRET|TOKEN|PASSWORD|DSN` outside
  `config/settings*.py` fail a static test.
- **`manage.py seed_credentials --from-file PATH` refuses a file tracked by git**, refuses
  placeholder values when `APP_ENV=production`, and never overwrites a configured value without
  `--overwrite`. Seeding from environment variables is a one-time bootstrap that fills only empty
  rows.

**Django + Next shape.**

| Table | Key columns |
|---|---|
| `core_credential_provider` | `slug` unique, `name`, `category`, `setup_steps` JSON, `is_system`, `display_order` |
| `core_credential_field` | `provider` FK, `key`, `label`, `type` (`string · secret · url · select · bool · int · json`), `is_required`, `is_encrypted`, `validation` JSON, `placeholder`, `help_text`, `default`, `order`, `consumed_by` |
| `core_credential` | `provider` FK, `environment`, `is_active`, `verification_status`, `verification_detail`, `last_verified_at`, `last_used_at`, `marked_bad_until`; unique `(provider, environment)` |
| `core_credential_value` | `credential` FK `CASCADE`, `field` FK, `value_text` (non-secret), `value_ciphertext` (secret); unique `(credential, field)` |

Service: `credentials.get(provider_slug, field_key) -> str` and `credentials.bundle(provider_slug)`.
Endpoints under `/api/settings/credentials/` (`core.credentials.view` / `.manage` / `.reveal`). Next:
one generic form component rendering the schema, a verification badge, a "Test now" button, and a
reveal action that triggers the re-auth modal on `423`.

**Enforced by.** `tests/core/credentials/`: `test_reads_are_masked`,
`test_reveal_requires_permission_and_recent_auth`, `test_reveal_writes_an_audit_row`,
`test_reveal_audit_is_on_when_setting_row_is_missing`, `test_no_probe_is_unverifiable`,
`test_probe_exception_does_not_lose_the_save`, `test_upstream_401_marks_bad`,
`test_no_cross_environment_fallback`, `test_omitted_required_field_is_refused_like_blank`,
`test_seed_refuses_a_tracked_file`. `tests/architecture/test_no_secret_env_reads_outside_settings.py`.

**Configurable, not hard-coded.** `security.audit.credential_reveal` (default `True`),
`security.reauth.credential_reveal` (default `True` — see § 29), `credentials.probe_timeout_seconds`
(10), `credentials.mark_bad_minutes` (60).

---

## 27. The non-production outbound guard   — **Tier 1 · Core**

**What.** In every environment except production, the platform refuses to message a real person or
write to another system — by construction, in the transports, with no switch to turn it off.

**Why.** Development and staging routinely run on a recent copy of production data, and the
credential rows hold working provider credentials. A real incident: queued emails from months earlier
reached the mail provider — and real recipients — from a developer's laptop. Relying on "remember to
unset the SMTP password locally" is relying on every developer, every time.

**Rules.**
- **Keyed on `APP_ENV` itself** ([`CONFIGURATION.md`](CONFIGURATION.md)). There is **no
  `DISABLE_OUTBOUND_GUARD`**; production is the only environment without the guard, and a test
  asserts no setting can remove it.
- **HTTP: allowlist, fail closed.** Outside production, `core.http` permits only hosts in
  `OUTBOUND_ALLOWLIST` (plus loopback and the product's own hosts), optionally narrowed to read-only
  methods per host. Everything else is answered **by the transport itself** with a synthetic `423`
  and `code: "blocked_locally"`, raised to callers as `OutboundBlocked` (§ 20). **Not `401`/`403`**:
  callers treat those as credential faults and would mark the credential bad or retry.
- **Email: redirect or console.** A wrapping email backend: with `NONPROD_TEST_RECIPIENT` set, every
  message goes to that one address, Cc/Bcc removed, subject prefixed `[<APP_ENV> TEST]`, original
  recipients in an `X-Original-Recipients` header; without it, only console/file backends are
  allowed. The wrapper *extends* whichever backend is configured, so a backend chosen at runtime from
  the credential store is covered too.
- **Chat and SMS transports** redirect to a configured test destination, naming the intended one,
  or drop with a log line.
- **Webhooks** are subject to the HTTP allowlist like any other request — a developer's copy never
  posts to a customer's endpoint.
- **Celery inherits it** — same settings, same transports. There is no second code path.
- **SDKs that bring their own HTTP stack** must be constructed inside an adapter that checks
  `outbound_guard.allows(host, method)` before each call; the lint of § 18 confines their import to
  adapters.

**Django + Next shape.** `core/http/guard.py` (an httpx transport wrapper); `core/mail/backends.py::GuardedEmailBackend`
(set automatically as `EMAIL_BACKEND` outside production, wrapping `EMAIL_BACKEND_INNER`).
Blocked calls log at WARNING with purpose, host and method — never the body.

**Enforced by.** `tests/core/test_outbound_guard.py` — at least one test per transport **proven to
fail with the guard patched out** (the suite asserts it catches what it claims to); a real SMTP
attempt in a non-production environment is redirected; a webhook to a public host is `423`;
`test_no_setting_disables_the_guard` (iterates every settings key containing `GUARD`/`OUTBOUND`);
`dbx.http.E010` — `APP_ENV != production` and `EMAIL_BACKEND` is not the guarded backend.

**Configurable, not hard-coded.** `OUTBOUND_ALLOWLIST` (env list), `NONPROD_TEST_RECIPIENT`,
`NONPROD_TEST_CHAT_DESTINATION`. The guard's existence is not configurable.

---

## 28. Summary of registries this file adds

Each is a catalogue in the shape [`EXTENSIBILITY.md`](EXTENSIBILITY.md) specifies (boot-time, frozen,
key + label + callable):

| Registry | Contributes | Read by |
|---|---|---|
| `jobs` | `JobSpec` | runners, schedule sync, monitor, doctors, topology tests |
| `reconcilers` | model + transient states + reconciler | generated jobs, the pending-state test |
| `outbox_topics` | topic + handler + semantics + retry | the drainer |
| `http_purposes` | outbound policy per purpose | `core.http` |
| `inbound_webhooks` | verifier + handler | the ingress view |
| `integrations` / `usage_probes` | relationships and how to measure them | the Integrations page |
| `credential_providers` / `credential_probes` | provider schemas and liveness probes | the credential store |
| `encrypted_fields` | every ciphertext column and its purpose | rotation, verification |

Events flagged `external=True` in the existing `events` registry form the webhook catalogue (§ 16).

---

## 29. ⚠️ Conflicts with existing docs

| File § | What it says | Fix |
|---|---|---|
| [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 3.6, § 12, § 16 | `MfaDevice.secret` is a `BinaryField` encrypted with a single `MFA_ENCRYPTION_KEY` via Fernet | Make MFA a **purpose** of the encryption service (§ 25): `secret_ciphertext` `TextField`, `FIELD_ENCRYPTION_KEYS` list, `decrypt(..., purpose="mfa")`. A single-purpose single key has no rotation path and is a second cipher in the codebase. Replace the `MFA_ENCRYPTION_KEY` row in § 12 |
| [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 6.9 | Every `security.reauth.<action>` defaults to `False` | Keep that default for existing flows, and add one exception: **`credential_reveal` defaults to `True`**. It is a new action, so defaulting on breaks no existing flow — the reason § 6.9 gives for "off" does not apply |
| [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 19.2 and [`TECH_DEBT.md`](../planning/TECH_DEBT.md) **DB-16** | `auth_cleanup` runs by cron; "the scheduler question stays open" | Register `auth_cleanup` as a `JobSpec` and ship `run_worker` (§ 2) in Phase 1. Cron may still drive `run_worker --once`, but the job is then recorded and monitored. DB-16 closes when § 2 lands |
| [`SECURITY.md`](SECURITY.md) § Secrets | "Everything environment-dependent comes from `.env`" | Narrow to **bootstrap** values (`SECRET_KEY`, `DATABASE_URL`, `FIELD_ENCRYPTION_KEYS`, broker/cache URLs). Runtime third-party credentials live in the encrypted credential store (§ 26) |
| [`SECURITY.md`](SECURITY.md) § What the core guarantees, item 3 | "Tokens hashed at rest — invitations, API credentials, reset tokens" | Correct for tokens we *compare*. Add: **secrets we must reproduce (webhook signing secrets, provider credentials, MFA seeds) are encrypted, never hashed and never plaintext** |
| [`DATA_MODEL.md`](DATA_MODEL.md) § 3 (Phase 2+) | `Webhook` + `WebhookDelivery` | `WebhookEndpoint` (owned by `ApiConsumer`) + `WebhookSubscription` + `WebhookDelivery`, as § 16 |
| [`CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md) § 2 | `events` — "event names it emits → the webhook subscription UI" | An event is offered to webhooks only when registered `external=True`. Otherwise every internal event becomes a public contract the moment it is registered |
| [`CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md) § 2 | `jobs` — "periodic background jobs → the worker" | Jobs are periodic **and** on-demand, and the entry carries queue, schedule, owner, limits and flags (§ 1); the registry is read by the scheduler sync, monitor and tests as well as the worker |
| [`ROADMAP.md`](../planning/ROADMAP.md) Status table | "Background jobs — Celery + Redis + Flower" | The Job Monitor (§ 7–8) is the operator surface and reads our own run record. If Flower is deployed at all it is internal-only, behind authentication — it displays task arguments and can revoke tasks |
| [ADR-0002](../adr/0002-api-first-drf-not-django-templates.md) | "No Django template is added for a product feature" | Clarify in a superseding note that **email bodies** are Django templates and are not a UI surface — [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 18 already relies on them |

---

## Pending decisions (for the repository owner)

1. **HTTP client library.** This file specifies `httpx` (sync client, pluggable transports, the
   `sni_hostname` extension that makes IP pinning clean). `requests` would need a custom adapter for
   pinning. One of them becomes a dependency with the first adapter — and only one.
2. **When Celery arrives.** Recommendation: `run_worker` in Phase 1 (it closes DB-16 with no new
   infrastructure), Celery in Phase 2 as planned, both on the one registry. The alternative — Celery
   from day one — makes the first-run experience need Redis *and* a worker process.
3. **Outbox and run-record tables on a separate database alias.** High-volume append-only logs
   (deliveries, job runs) can live on a `logs` alias to keep the main database's WAL and backups
   small. Recommendation: design for it (every write already goes through one service), do not
   configure it until volume is measured.
4. **Broker durability.** Redis as broker must run with persistence and `noeviction`
   ([`OPERATIONS.md`](OPERATIONS.md)); whether to offer a Postgres-backed broker for products that
   cannot run Redis is open.
5. **System-check id allocation.** This file uses namespaced ids (`dbx.jobs.*`, `dbx.hooks.*`,
   `dbx.http.*`, `dbx.crypto.*`). Confirm the scheme across the blueprint set before any is
   implemented.

---

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section.
