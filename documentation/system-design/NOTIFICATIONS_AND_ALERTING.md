# Notifications and Alerting

**How DjangoBaseX decides who is told what, on which channel — the notification purposes registry and
admin-editable routing, channel transports, the event × channel matrix, per-user preferences, test
routing, the in-app notification store and bell, digests, outbound email — and how operational
alerts reach people without training them to mute the channel: one dispatcher, a decision ledger,
an instant allow-list, a twice-daily digest, incidents and quiet hours.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

---

## Scope — read first

**Owns:** notification purposes and routing · channel adapters (transports) · the `notify()` gate
chain · the event × channel matrix · per-user preferences · send-test and test routing · delivery
semantics for human-facing messages · the in-app notification store and the bell · digests · email
specifics · editable-template safety · the chat transport · the ops alert dispatcher, its ledger,
the instant/digest policy, incidents, quiet hours, scheduled monitors and the ops panel.

**Does not own:**

| Topic | Owner |
|---|---|
| The outbox, retry policy, locks, the run record, `core_job_state`, webhooks, the SSRF-safe HTTP client, the credential store, the non-production outbound guard | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| Metrics, error grouping, health checks, the system-health page, external alert-pipeline rules | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
| User-defined alert rules over business data (the optional alert-rules engine) | [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md) |
| Templated documents (PDF, contracts) | [`REUSABLE_MODULES.md`](REUSABLE_MODULES.md), [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) |
| The settings registry, `APP_ENV`, `platform.default_timezone` | [`CONFIGURATION.md`](CONFIGURATION.md) |
| The polling/data layer, toasts, safe links on the frontend | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) |
| Registry mechanics and soft-disable of a module | [`EXTENSIBILITY.md`](EXTENSIBILITY.md) |
| Retention of the tables defined here | [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) |

**Two audiences, one plumbing.** *Notifications* tell a person something about the product
("your export is ready", "invoice 42 is overdue"). *Ops alerts* tell operators something about the
system ("the queue is stalled"). They share transports and routing rows; they differ in policy — ops
alerts pass through the dispatcher of § 14, which is where the anti-noise rules live.

---

## 0. The rules in one screen

1. **Callers name a purpose, never a destination.** No email address, channel id or URL in calling code — routing is admin-editable data. ([§ 1](#1-notification-purposes-and-routing----tier-2--core))
2. **Transports are adapters in a registry** — email, in-app, chat, webhook, SMS — and a transport never raises into its caller. ([§ 2](#2-channel-adapters----tier-2--core))
3. **`notify()` runs after commit and never fails the save.** ([§ 3](#3-notify-and-the-gate-chain----tier-2--core))
4. **The gate chain is documented, and every gate says why it stopped a message** — at debug in the log, and in the delivery row once a recipient is known. ([§ 3](#3-notify-and-the-gate-chain----tier-2--core))
5. **Nothing bypasses `notify()`.** A direct transport call skips the master toggle, preferences and the guard. ([§ 3](#3-notify-and-the-gate-chain----tier-2--core))
6. **The event × channel matrix is seeded from code and never overwrites an admin's choice.** ([§ 4](#4-the-event--channel-matrix----tier-2--core))
7. **Preferences resolve user row → system default row → code default; security notices cannot be opted out of.** ([§ 5](#5-per-user-preferences----tier-2--core))
8. **Every route has "Send test"; new flows roll out with test routing on; token-bearing messages are never test-routed in production.** ([§ 6](#6-send-test-and-test-routing----tier-2--core))
9. **Human-facing delivery is at-most-once:** an ambiguous send is `unknown`, not resent. Reminder dedupe fails closed. ([§ 7](#7-delivery-semantics-and-the-delivery-log----tier-2--core))
10. **Read state is per user; resolved state is shared.** Resolving an item closes everyone's prompt for it. ([§ 8](#8-the-in-app-notification-store----tier-2--core))
11. **One open in-app row per recipient × purpose × object** — re-runs update it, they do not duplicate it. ([§ 8](#8-the-in-app-notification-store----tier-2--core))
12. **A digest is one message per run, with a header count and every row.** No top-N cap, no @-mention floods; stamp only after the provider accepts. ([§ 10](#10-digests----tier-2--core))
13. **Emailed links come from `FRONTEND_BASE_URL`, never the `Host` header; `send_email()` returns a bool and never raises; production refuses the console backend.** ([§ 11](#11-email----tier-1--core))
14. **Ops alerts go through one dispatcher that records every decision — `sent`, `held`, `skipped` — in the database**, so a cache clear cannot re-announce everything. ([§ 14](#14-the-ops-alert-dispatcher-and-its-ledger----tier-2--core))
15. **Instant is a short allow-list; everything else waits for the twice-daily digest, which says "all clear" when it is.** ([§ 15](#15-instant-or-digest----tier-2--core), [§ 16](#16-the-ops-digest----tier-2--core))
16. **An incident is announced once and recovers once.** Nothing in between. ([§ 17](#17-incidents----tier-2--core))
17. **Quiet hours hold alerts and release one summary.** ([§ 18](#18-quiet-hours----tier-2--core))
18. **Scheduled monitors exit 0 and report through the dispatcher**; `--strict` is for humans. ([§ 19](#19-scheduled-monitors----tier-2--core))
19. **The ops panel is rendered from the same settings and ledger the code runs on**, so it cannot drift. ([§ 20](#20-the-ops-panel----tier-2--core))

---

# Part A — Notifications

## 1. Notification purposes and routing   — **Tier 2 · Core**

**What.** Every kind of message the product sends is a **purpose**, declared in code by the module
that owns it. Where a purpose goes — which chat channel, which distribution list — is a **routing
row** an administrator edits. Calling code says *what happened*; it never says *where to send it*.

**Why.** The first design everyone builds is a webhook URL or a channel id per call site. Then an
administrator needs to move "new orders" to a different channel, and it is a code change and a
deploy. Worse, a real incident: one admin alert posted to a hard-coded channel and **ignored the
module's master toggle**, because it did not go through the path where the toggle lived.

**Rules.**
- **A purpose is a code, a label, an owner module, an audience and default channels.** Codes are
  stable and dotted (`billing.invoice_overdue`); renaming one is a data migration.
- **Two audiences.** `user` purposes are addressed to people the purpose resolves from the subject
  (an assignee, an owner, a role). `broadcast` purposes go to a routed destination (a team channel, a
  shared inbox). A purpose may be both.
- **Callers may name *subjects*, never *addresses*.** `notify("orders.assigned", obj=order,
  recipients=[order.assignee_id])` is fine — the assignee is part of the event. `to="ops@…"` or
  `channel="C0123"` is not; that is routing.
- **Recipients are resolved by the purpose**, from its `recipients(obj, context)` callable, at
  dispatch time in the worker — so a reassignment between the save and the send reaches the right
  person.
- **Routing rows are cached with an explicit bust** from the admin screen, never a long TTL someone
  has to wait out.
- **Mandatory purposes** (`mandatory=True`) — password reset, invitation, new sign-in, MFA disabled,
  email change — cannot be switched off by the matrix or by preferences (§ 4, § 5).
- **Token-bearing purposes** (`carries_token=True`) — anything whose body contains a single-use link —
  are additionally excluded from test routing in production (§ 6).

**Django + Next shape.**

```python
registry.notification_purposes.register(Purpose(
    code="billing.invoice_overdue", label="Invoice overdue", owner_module="billing",
    description="Sent daily while an invoice is past due.",
    audience={"user", "broadcast"}, default_channels=("email", "in_app"),
    recipients="billing.notifications.invoice_recipients",     # dotted path, resolved lazily
    preview="billing.notifications.invoice_overdue_preview",   # returns a sample context
    context_schema=InvoiceOverdueContext,                       # TypedDict; validated in tests
    dedupe_window_minutes=1440, mandatory=False, carries_token=False, rollout=True))
```

`core_notification_route`: `purpose_code`, `channel` (a registered channel key), `target` JSON
(validated against the channel's target schema — a chat channel id, a list of addresses, a webhook
endpoint id), `is_active`, `created_by`/`updated_by` (`SET_NULL`), timestamps. Unique
`(purpose_code, channel, target_hash)`. Routes are edited under `/api/notifications/routes/`
(`core.notifications.manage`) and every change is audited — re-pointing a route redirects data.

**Enforced by.** `dbx.notify.E001` — a registered purpose whose `recipients`/`preview` path does not
import, or whose `default_channels` names an unregistered channel.
`tests/architecture/test_notify_calls_carry_no_destination.py` — AST scan of every `notify(` call:
no keyword named `to`, `email`, `channel`, `url`, `address`, `target`.
`tests/core/notifications/test_purposes.py::test_every_purpose_preview_renders_for_every_default_channel`
— fails on an empty registry.

**Configurable, not hard-coded.** Routes are rows. Purpose metadata is code, because the code that
emits it is.

---

## 2. Channel adapters   — **Tier 2 · Core**

**What.** A channel is a **transport** registered in `registry.notification_channels`: it knows how
to deliver a rendered message to a target, and nothing about purposes, preferences or policy.

| Channel | Ships in | Target | Notes |
|---|---|---|---|
| `email` | core | a user's address, or a routed list | § 11 |
| `in_app` | core | a user | the store of § 8; never leaves the database |
| `chat` | optional module | a routed channel, or a user's direct message | § 13 |
| `webhook` | core (reuses outbound webhooks) | a webhook endpoint id | posts the purpose event through [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 16 — ids only, signed |
| `sms` | optional module | a user's verified phone number | E.164 only; see below |

**Why.** Alerts should be able to reach chat, the bell, or both, without coupling the thing that
raises them to the thing that delivers them. A transport per module that sends its own mail is how a
product ends up with five email code paths, each missing a different safety rule.

**Rules.**
- **`send(message, target) -> DeliveryResult`, never raises.** The result is `accepted(ref)`,
  `rejected(code)` (permanent — bad address, blocked recipient), `retry(after)` (transient) or
  `unknown(evidence)` (the provider may have accepted it). Exceptions inside a transport are caught
  and converted.
- **`available()` is cheap and honest**: "configured, and its credential is not marked bad"
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 26). An unavailable channel is a gate
  outcome (§ 3), not an error.
- **Every outbound transport goes through the platform's HTTP client or mail layer**, so SSRF
  protection and the non-production guard apply without the transport re-implementing them.
- **Each channel declares its limits** — max body length, max blocks, supports HTML, supports
  threading — and the renderer respects them (chunking, § 10).
- **SMS specifics.** Numbers are stored and sent in E.164; provider selection is configuration, never
  a heuristic on the number's prefix (a real bug: a bare leading "91" was treated as a country code).
  Templates are placeholders-only (§ 12). A per-account, per-hour cap is enforced at claim time, and
  rows past the cap are recorded as `skipped:budget`, not silently dropped.

**Django + Next shape.** `core/notifications/channels/base.py`:

```python
class Channel(Protocol):
    key: str; label: str
    target_schema: type[TypedDict]
    limits: ChannelLimits
    def available(self) -> bool: ...
    def render(self, purpose: Purpose, context: dict, target: dict) -> RenderedMessage: ...
    def send(self, message: RenderedMessage, target: dict) -> DeliveryResult: ...
```

**Enforced by.** `tests/core/notifications/test_channel_contract.py` — parametrised over every
registered channel: `send` never raises (inject a transport error), `available` is side-effect free,
`render` respects `limits`. `tests/architecture/test_no_direct_transport_use.py` — imports of
`core.notifications.channels.*` or the mail backend outside `core/notifications/` and `core/ops/`.

**Configurable, not hard-coded.** Channel credentials live in the credential store; per-channel
budgets `notifications.channels.<key>.max_per_hour`.

---

## 3. `notify()` and the gate chain   — **Tier 2 · Core**

**What.** The single entry point, and the documented sequence of gates every message passes through
before a transport sees it.

**Why.** "Why didn't they get the email?" is the most common notification question, and without a
documented chain the answer is an afternoon of reading code. With one, it is a lookup. And a
notification failure — a broken template, a provider outage — must never turn a user's successful
save into a `500`.

**Rules.**
- **`notify()` does no fallible work inline.** It checks the purpose code exists (a programming
  error — raises in tests and `DEBUG`, logs at ERROR otherwise), then registers
  `transaction.on_commit(...)` to write one outbox row (`notifications.dispatch`, ids only). Resolution,
  rendering and delivery happen in the worker. The call is wrapped: nothing it does can raise into
  the caller.
- **After commit, deliberately.** A notification about a row that rolled back is a lie. The cost —
  a process dying in the microseconds between commit and the outbox write loses the message — is
  accepted for notifications, which are not the system of record.
- **The one exception: `durable=True`.** A message that must be exactly as durable as the business
  change (a contractual notice) writes its outbox row *inside* the transaction. It still renders
  nothing inline, so it still cannot fail the save on a template error.
- **Nothing bypasses `notify()`.** Direct transport use is lint-banned (§ 2). Anything that genuinely
  needs a different path re-implements every gate below and says so in a comment reviewers check.

**The gate chain, in order.** Each gate logs at `DEBUG` with `purpose`, `channel`, `gate`,
`outcome`. From gate 6 on, a recipient exists, so the stop is also written to the delivery row
(`status=skipped`, `skip_reason=<gate>`) — "why didn't X get it?" is then a query.

| # | Gate | Stops when |
|---|---|---|
| 1 | Platform switch | `notifications.enabled` is off |
| 2 | Module | the owning module is soft-disabled ([`EXTENSIBILITY.md`](EXTENSIBILITY.md)) or its master toggle is off |
| 3 | Matrix | the purpose × channel cell is off (§ 4) — skipped for mandatory purposes |
| 4 | Channel availability | the transport is unconfigured or its credential is marked bad |
| 5 | Routing | a broadcast purpose has no active route for this channel |
| 6 | Recipient resolution | the purpose resolves nobody (logged as a finding if the purpose declares `must_reach_someone`) |
| 7 | Preferences | the user opted out (§ 5) — skipped for mandatory purposes |
| 8 | Test routing / environment | the message is redirected to the tester (§ 6) or the non-production guard applies |
| 9 | Dedupe | an identical `(purpose, recipient, channel, dedupe_key)` was sent inside the purpose's window (§ 7) |
| 10 | Budget | the channel's per-recipient or per-account cap is spent |
| 11 | Claim-time revalidation | the subject no longer warrants the message (invoice now paid, user deactivated) |
| 12 | Provider | the transport's `DeliveryResult` |

**Django + Next shape.** `core/notifications/api.py::notify(purpose, *, obj=None, recipients=None,
context=None, dedupe_key=None, durable=False) -> None`. The dispatch handler fans one outbox row into
one delivery per (recipient × channel), each itself an outbox row on topic
`notifications.<channel>` with `at_most_once` semantics
([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 12). A **"Why not delivered?"** panel on
the delivery log reads `skip_reason`.

**Enforced by.** `tests/core/notifications/test_notify.py`:
`test_notify_inside_a_rolled_back_transaction_sends_nothing`,
`test_a_broken_template_does_not_fail_the_save`, `test_each_gate_records_its_skip_reason`
(one case per gate, 6–11), `test_mandatory_purpose_ignores_matrix_and_preferences`,
`test_durable_notify_is_in_the_same_transaction`.

**Configurable, not hard-coded.** `notifications.enabled`, per-module master toggles (§ 4).

---

## 4. The event × channel matrix   — **Tier 2 · Core**

**What.** A settings screen, generated from the purposes registry, showing every purpose × every
channel it supports, with a master toggle per module, a toggle per cell, and a **payload preview**
for each cell.

**Why.** A real incident: two feature modules each built their own 700–870-line notification
settings page. A third module would have built it a third time. And administrators enabling a
notification they have never seen produced surprised customers.

**Rules.**
- **Seeded from code on every sync** (post-migrate and `manage.py sync_notifications`): a new purpose
  appears as rows with its code defaults; **existing rows are never overwritten** — an admin's "off"
  survives every deploy. A purpose removed from code has its rows deleted by the sync, not orphaned.
- **Master toggle per module, then per cell.** The master is evaluated first (gate 2), so turning a
  module's notifications off is one click, and turning it back on restores each cell's own state.
- **Preview renders the real template** with the purpose's `preview()` sample context for that
  channel — subject, plain text and HTML for email; blocks for chat. HTML previews are shown in a
  sandboxed iframe (`sandbox=""`), never injected into the page.
- **Mandatory cells are shown locked**, with the reason ("security notice — cannot be disabled").
- **Toggle changes are audited** with old and new value.

**Django + Next shape.** `core_notification_setting(purpose_code, channel, enabled, updated_by,
updated_at)` unique `(purpose_code, channel)`; `core_notification_module_setting(module, enabled)`.
`GET /api/notifications/matrix/` returns the grid grouped by module;
`PATCH /api/notifications/matrix/` takes a list of cell changes;
`POST /api/notifications/purposes/<code>/preview/ {"channel": "email"}` returns the rendered message.
A plugin gets its rows, its section on the screen and its previews by registering purposes — no UI
code.

**Enforced by.** `tests/core/notifications/test_matrix_sync.py`: `test_sync_adds_new_purposes`,
`test_sync_never_overwrites_an_admin_choice`, `test_removed_purpose_rows_are_deleted`,
`test_master_off_then_on_restores_cells`.

**Configurable, not hard-coded.** Everything on this screen is data; defaults come from the purpose.

---

## 5. Per-user preferences   — **Tier 2 · Core**

**What.** Each user can turn opt-out-able purposes on or off per channel, on top of a system default
an administrator sets.

**Rules.**
- **Resolution order:** the user's row → the system default row (`user IS NULL`) → the purpose's
  code default. A system default row lets an administrator change the default for everyone who has
  not chosen, without touching the people who have.
- **Mandatory purposes are not in the preferences UI as toggles** — they appear, locked, so a user
  can see they exist.
- **Preferences are checked at dispatch time**, not when `notify()` was called — the user who
  unsubscribed a minute ago is respected.
- **Email for opt-out-able purposes carries a one-click unsubscribe** (`List-Unsubscribe` and
  `List-Unsubscribe-Post` headers, a signed, purpose-scoped, single-user token) that flips exactly
  that preference. Mandatory mail carries no unsubscribe link — it would be a lie.
- **The in-app channel is the floor** for `user` purposes: a user who turns off email for a purpose
  still sees it in the bell unless they turn that off too.

**Django + Next shape.** `core_notification_preference(user nullable FK CASCADE, purpose_code,
channel, enabled, updated_at)` with two constraints:
`UniqueConstraint(fields=["user", "purpose_code", "channel"], condition=Q(user__isnull=False))` and
`UniqueConstraint(fields=["purpose_code", "channel"], condition=Q(user__isnull=True))` — a plain
unique over a nullable column would allow unlimited system rows. `GET/PATCH /api/me/notification-preferences/`.
Next: a preferences page grouped by module, generated from the same registry as the matrix.

**Enforced by.** `tests/core/notifications/test_preferences.py`: resolution order,
`test_only_one_system_default_row_per_cell`, `test_unsubscribe_token_flips_only_its_own_preference`,
`test_mandatory_purposes_cannot_be_opted_out`.

**Configurable, not hard-coded.** System default rows are admin-editable data.

---

## 6. Send test and test routing   — **Tier 2 · Core**

**What.** Two rollout safety tools: a **Send test** button on every route and channel configuration,
and a per-purpose **test routing** mode that sends every real message for that purpose to one tester
while a new flow is proven.

**Why.** "Send test" has caught every routing misconfiguration first — the wrong channel, a bot not
invited to it, a list address with a typo — before a real message went nowhere. Test routing exists
because a new notification flow to real external users is the moment a wrong recipient rule is most
expensive.

**Rules.**
- **Send test uses the real path** — the real transport, credential, SSRF client and guard — with a
  synthetic `[TEST] <purpose label>` message, and returns the `DeliveryResult` to the screen. A test
  that bypasses the transport tests nothing.
- **Purposes declared `rollout=True` ship with test routing ON.** Every message for the purpose goes
  to `notifications.test_recipient.<channel>`, and the body names the recipients it *would* have
  reached. It is flipped off on the settings screen — **not by a deploy** — and the flip is audited.
- **Token-bearing purposes are never test-routed in production.** Redirecting a password-reset email
  to a tester hands the tester a live single-use link to someone else's account. In production, test
  routing for a `carries_token=True` purpose is refused by the settings validator and by the
  dispatcher. (Non-production environments redirect everything anyway —
  [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 27 — and hold no real accounts.)

**Django + Next shape.** `POST /api/notifications/routes/<id>/test/` and
`POST /api/notifications/channels/<key>/test/` (`core.notifications.manage`, throttled). Setting
keys `notifications.<purpose>.test_routing` (bool) and `notifications.test_recipient.<channel>`.

**Enforced by.** `tests/core/notifications/test_test_routing.py`:
`test_rollout_purposes_default_to_test_routing`, `test_test_routed_body_names_intended_recipients`,
`test_token_bearing_purpose_cannot_be_test_routed_in_production`,
`test_send_test_goes_through_the_real_transport`.

**Configurable, not hard-coded.** The tester per channel and the per-purpose flag are settings.

---

## 7. Delivery semantics and the delivery log   — **Tier 2 · Core**

**What.** How a notification is actually handed to a provider, recorded, deduplicated and bounded.

**Rules.**
- **Human-facing channels are `at_most_once`.** A lease that expires mid-send, or a timeout after the
  provider may have accepted the message, moves the delivery to `unknown` — never an immediate
  resend. A duplicate email storm is worse than a missed reminder.
- **Reminder dedupe fails closed.** Period-scoped dedupe keys (`reminder:invoice:42:2026-09-29`) with
  a unique constraint in the delivery table: if the dedupe check cannot be made, the reminder is not
  sent. (The inverse of inbound-webhook dedupe, which fails open — dropping a partner's event is
  worse than processing it twice. The direction is chosen per use and written down.)
- **Never write marker rows into business tables to remember "already reminded".** A real incident:
  zero-value "marker" transactions used as reminder dedupe polluted a customer-visible ledger.
  Dedupe state lives in the delivery table.
- **Revalidate at claim time** (gate 11): the invoice is still unpaid, the contact still exists, the
  address is not on the suppression list.
- **Budgets.** Per channel, per recipient and per account per hour; over-budget deliveries are
  `skipped:budget`, visible and countable.
- **Record every attempt, including skips.** The delivery log answers "what did we send, to whom,
  when, and what did the provider say?" without reading logs.
- **Never persist provider bodies.** A provider error message may echo the recipient list or a
  signed URL; store a code and a scrubbed, truncated message.

**Django + Next shape.** `core_notification_delivery`: `purpose_code`, `channel`, `recipient` FK
(`SET_NULL`, null for broadcast), `target_hash`, `dedupe_key`, `status` (`pending · sent ·
skipped · failed · unknown`), `skip_reason`, `provider_ref`, `error_code`, `error_message`,
`attempts`, `created_at`, `sent_at`, and `outbox` FK. Unique `(purpose_code, channel, target_hash,
dedupe_key)` where `dedupe_key <> ''`. High volume: design for a separate `logs` database alias
(see [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) Pending decisions) and retention with a
row cap ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)). Next: a delivery log with filters by purpose,
channel, status and recipient, and the "why not delivered?" reason column.

**Enforced by.** `tests/core/notifications/test_delivery.py`:
`test_stale_lease_is_unknown_not_resent`, `test_reminder_dedupe_fails_closed_when_check_errors`,
`test_over_budget_is_recorded_as_skipped`, `test_provider_error_body_not_stored`.

**Configurable, not hard-coded.** `notifications.channels.<key>.max_per_hour`,
`notifications.channels.<key>.max_per_recipient_per_hour`, `notifications.delivery_retention_days`.

---

## 8. The in-app notification store   — **Tier 2 · Core**

**What.** The `in_app` channel's storage: one row per notification per recipient, with **per-user
read state** and **shared resolved state**.

**Why.** Two floods it prevents. Syncs that raise one notification per changed item bury the bell;
the answer is one evolving row per subject. And stale "please act on this" prompts linger in the
inboxes of everyone who was told, long after one of them handled it.

**Rules.**
- **`read_at` is per user.** Reading your copy does not read anyone else's.
- **`resolved_at` is shared.** `notifications.resolve(object_ref, by=user, note="")` closes every open
  row for that subject, across all recipients — the item has been handled; nobody needs prompting.
  Domain code calls it where the item is handled (the approval service, the ticket close), not from
  the bell.
- **One open row per recipient × purpose × `object_ref`.** A re-run of the same notification for the
  same subject finds the open row and does not duplicate it.
- **Digest upsert.** `notifications.digest(purpose, recipient, object_ref, title, count,
  resurface=True)` updates one evolving row ("12 pending changes") instead of inserting twelve.
  `resurface=True` marks it unread again **without changing its id**, so a client that raises an OS
  notification per new id fires once, not per update. Pass `resurface=False` when the count shrinks —
  fewer things to do is not news.
- **`url` is a relative deep link** to the real record (`/billing/invoices/42`), validated at write:
  starts with a single `/`, no scheme, no `//`. The bell never links off-site.
- **`object_ref` is a stable string** (`"billing.invoice:42"`), not a generic foreign key, so rows
  survive the subject's deletion and can be resolved by code that holds only the reference.
- **A soft-disabled module's rows are hidden, not deleted**, and reappear when it is re-enabled.
- **Emitters never write rows directly** — they call `notify()`/`digest()`/`resolve()`.

**Django + Next shape.**

| Column | Type | Notes |
|---|---|---|
| `recipient` | FK user, `CASCADE` | a user's notifications go with the user |
| `purpose_code` / `source_module` | `CharField` | `source_module` drives soft-disable hiding |
| `level` | `TextChoices`: `info · success · warning · error · action` | `action` = needs the user to do something |
| `title` / `body` | `CharField(200)` / `TextField` | plain text; rendered escaped |
| `url` | `CharField(500)` | relative path, validated |
| `object_ref` | `CharField(200)`, indexed | |
| `count` | `PositiveIntegerField` default 1 | digest rows |
| `read_at` | `DateTimeField` null | per user |
| `resolved_at` / `resolved_by` / `resolved_note` | shared | `resolved_by` `SET_NULL` |
| `created_at` / `updated_at` | | `updated_at` moves on resurface |

Indexes `(recipient, read_at)`, `(recipient, -updated_at)`; partial unique
`(recipient, purpose_code, object_ref)` where `resolved_at IS NULL AND object_ref <> ''`.
Endpoints (own rows only, via `visible_to()`): `GET /api/notifications/` (filter `unread`, `level`,
`source`), `POST /api/notifications/<id>/read/`, `POST /api/notifications/read-all/ {"up_to_id": n}`
(marks only what the user has seen — a new row arriving mid-click stays unread).

**Enforced by.** `tests/core/notifications/test_inapp_store.py`:
`test_read_is_per_user`, `test_resolve_closes_every_recipients_row`,
`test_repeat_notify_does_not_duplicate_open_row`, `test_resurface_keeps_the_id`,
`test_shrinking_count_does_not_resurface`, `test_offsite_url_is_rejected`,
`test_soft_disabled_module_rows_are_hidden_not_deleted`, `test_read_all_respects_up_to_id`.

**Configurable, not hard-coded.** Retention of read + resolved rows
(`notifications.inapp.retention_days`, 90) via the retention engine.

---

## 9. The bell   — **Tier 2 · Core**

**What.** The topbar indicator and its data contract.

**Rules.**
- **A dedicated summary endpoint** — `GET /api/notifications/summary/` →
  `{"unread": n, "action_required": m, "latest_id": id, "latest_at": ts}` — cheap (two indexed
  counts), so polling it is not a load problem.
- **The badge counts rows, not a live re-evaluation** of whatever raised them, so it always matches
  the list the user opens.
- **Poll while visible.** The frontend polls the summary (default every 30 s) only while the tab is
  visible, and fetches the list only when `latest_id` changes. Server-sent events are a later
  optimisation behind the same contract (see Pending decisions).
- **OS notifications are opt-in** and fire once per new `latest_id`, never per poll.
- **A finished background job announces itself** through the same store: the job's completion writes
  an in-app notification to its actor, and the page that started it also raises a toast on the
  transition ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)).

**Django + Next shape.** `src/lib/api` client functions for summary/list/read; a `useNotificationSummary()`
hook in the data layer specified by [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md); a `<NotificationBell>`
component in `src/core/`. No `fetch()` in the component.

**Enforced by.** `tests/core/notifications/test_summary.py` (counts match the list; query count is
constant); a frontend test that polling pauses when `document.hidden`.

**Configurable, not hard-coded.** `notifications.bell.poll_seconds` exposed through the bootstrap
payload.

---

## 10. Digests   — **Tier 2 · Core**

**What.** A base class for any scheduled job that tells someone about a *set* of things — reminders,
"requests waiting for you", "changes since yesterday" — and the rules that stop it failing silently
in either direction.

**Why.** Digests fail both ways. Silence: a digest capped at "worst 20" never shows the oldest items
at the tail of an oldest-first list — they stay invisible forever. A run marker kept in the cache was
cleared by a deploy and the digest posted twice. A baseline committed *before* the send meant a
provider outage silently swallowed a day. Flood: one message per row; @-mentioning every owner
pinged 63 people.

**Rules.**
- **One message per run per destination**, with a **header count** ("17 requests waiting — oldest 9
  days") and **every row**. No top-N cap.
- **Chunk within the message, not across messages.** If a channel's block or length limit is hit,
  split into blocks inside one message; if even that cannot hold it, include as many rows as fit plus
  "and N more" linking to a filtered list page — **rendered rows + N must equal the header count**.
- **Plain names, not @-mentions.** Mention at most the single owner the digest is addressed to.
- **Escape table content** for the channel's markup (a `|` in a name breaks a table; a `<` breaks
  HTML).
- **Stamp only after the provider accepts.** `reminder_sent_at`, and the baseline, are written after
  `DeliveryResult.accepted`, never before the send.
- **Baselines live in the database** (`core_job_state` —
  [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 11), committed after success. Never the
  cache.
- **Completeness needs state, not events.** A digest of "what changed" diffs committed snapshots
  (row hashes stored in the job state) rather than listening to model signals — `QuerySet.update()`,
  `bulk_create` and raw SQL fire no signals, so an event-driven change digest is incomplete by
  construction.
- **"Nothing to report" is a declared behaviour** per digest: `silent` (reminders) or `all_clear` (the
  ops digest, § 16). Never accidental.
- **One feed row per run.** A digest run writes one activity row with counts, not one per item;
  a run that found nothing and sent nothing writes nothing.

**Django + Next shape.**

```python
class DigestJob:
    name: str; purpose: str; empty: Literal["silent", "all_clear"] = "silent"
    def collect(self, state: JobState) -> list[Row]: ...          # ALL rows, oldest first
    def destinations(self, rows) -> dict[Destination, list[Row]]: ...
    def render(self, dest, rows, total: int) -> RenderedMessage: ...
    def on_sent(self, dest, rows, state: JobState) -> None: ...   # stamps + baseline; runs only after accept
```

It registers as a `JobSpec` and sends through `notify()`'s channel layer (so matrix, routing and the
guard apply), but it writes its own stamps only from `on_sent`.

**Enforced by.** `tests/core/notifications/test_digest_base.py`:
`test_one_message_per_destination_per_run`, `test_no_row_is_dropped` (1 000 rows; rendered + "more"
equals total), `test_no_mentions_except_the_owner`, `test_pipe_and_angle_brackets_are_escaped`,
`test_provider_failure_leaves_baseline_unchanged`, `test_baseline_survives_cache_clear`.

**Configurable, not hard-coded.** Schedule per digest via its `JobSpec`; `digests.<name>.enabled`.

---

## 11. Email   — **Tier 1 · Core**

**What.** The email transport and its rules. Phase 1 needs it for password reset and invitations
([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 18, `BUILD_ORDER` 1.5b); this section extends that
chapter rather than replacing it.

**Rules.**
- **Three template files per message:** `<name>.subject.txt`, `<name>.txt`, `<name>.html`, in
  `<app>/templates/<app>/email/`. The plain-text part is not optional.
- **Autoescape on for HTML.** Subjects render with autoescape off and **newlines stripped** — a
  newline in a subject is header injection.
- **Links come from `FRONTEND_BASE_URL`** through one helper, `core.urls.frontend_url(path, **query)`
  — **never from the request's `Host` header** (host-header injection turns a genuine reset email
  into a link to an attacker's server; [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 18).
- **Production refuses the console, locmem, dummy and file backends.** A silently discarded reset
  email is diagnosed as "the reset endpoint is broken".
- **`send_email(...) -> bool` never raises.** It catches, logs, and returns `False`; callers that
  must answer uniformly (forgot-password always answers `204`) do so regardless.
- **A failure logs the recipient and subject only** — never the body, which may hold a token.
- **Recipient cap.** At most `EMAIL_MAX_RECIPIENTS` (default 20) per message; fan-out to many people
  is one message per recipient, never a To: line that discloses everyone to everyone.
- **Sent after commit**, through the outbox (§ 3); never inside the transaction.
- **`Auto-Submitted: auto-generated`** on system mail, so out-of-office replies do not loop.
- **Suppression list.** Hard bounces and complaints (from the provider's inbound webhook,
  [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 17) add the address to
  `core_email_suppression(address_hash, reason, created_at)`, checked at claim time.
- **No tracking pixels or remote images** by default; images are inline or absent.
- **SMTP hosts that an operator configures** are resolved, checked and pinned like any other outbound
  host.

**Django + Next shape.** `core/mail/`: `send_email(template, to, context, *, reply_to=None) -> bool`,
`render_email(template, context) -> (subject, text, html)` (also used by the matrix preview), and the
guarded backend of [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 27. Phase 1 calls
`send_email` from `transaction.on_commit`; when § 3 lands, the auth emails become mandatory,
token-bearing purposes (`users.password_reset`, `users.invitation`) and move behind `notify()`.

**Enforced by.** `dbx.notify.E010` — `APP_ENV=production` and the (inner) email backend is console,
locmem, dummy or file-based. `tests/core/mail/test_send_email.py`:
`test_send_failure_returns_false_and_does_not_raise`, `test_failure_log_has_no_body`,
`test_links_ignore_the_host_header`, `test_subject_newlines_are_stripped`,
`test_recipient_cap_is_enforced`. `tests/architecture/test_every_email_has_three_parts.py` — every
`*.subject.txt` has a `.txt` and `.html` sibling; fails on an empty template set.

**Configurable, not hard-coded.** `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `FRONTEND_BASE_URL`,
`EMAIL_MAX_RECIPIENTS` (env); `email.reply_to` (settings registry).

---

## 12. Editable templates   — **Tier 2 · Core**

**What.** The rules for the day a product lets administrators (or tenants) edit message templates.

**Why.** A real incident class: tenant-editable templates rendered by an unsandboxed template engine
were server-side template injection — remote code execution. **Autoescaping does not stop template
injection**; it escapes output, not what the template itself can do.

**Rules.**
- **File templates (in the repository) use Django templates.** Only reviewed code writes them.
- **Database-editable templates render in a sandbox** — a sandboxed engine with autoescape for HTML
  and a separate non-escaping sandboxed environment for subjects and text, strict undefined
  variables, and no access to attributes beyond the declared context. Django's own template engine is
  not a sandbox and must not render user-authored template source.
- **User-supplied values are context, never template source.** A customer's name goes into the
  context dict; it is never concatenated into the template string.
- **Validate at save** in the same sandbox, and render the preview there — a broken template must fail
  on the edit screen, not silently drop every email.
- **Token-bearing templates cannot be overridden** (reset, verification, invitation, MFA). A guard on
  the template model refuses overrides for those purposes, and fails closed for new purposes whose
  code matches the security keyword list.
- **SMS and chat templates are placeholders only** — `{{ name }}` from a whitelist; control
  structures are rejected at save.
- **No `|safe` on anything user-derived.** A documented example showing `{{ url | safe }}` is how a
  bypass becomes a convention.

**Django + Next shape.** Specified with the templated-documents module in
[`REUSABLE_MODULES.md`](REUSABLE_MODULES.md); this section is the rule set notifications must meet.
The sandboxed engine is a new dependency, added only when editable templates are built.

**Enforced by.** A test per editable-template surface that a template containing an attribute-walk
payload raises a sandbox error at save; `test_token_bearing_templates_cannot_be_overridden`.

**Configurable, not hard-coded.** Which purposes allow overrides is declared on the purpose.

---

## 13. The chat transport   — **Tier 3 · Module**

**What.** An optional module providing the `chat` channel for a team-chat workspace: a singleton
configuration (bot token in the credential store, default channel), `chat.available()`,
`chat.send(destination, blocks, fallback_text) -> DeliveryResult`, a test-connection action and a
list-channels helper for the routing screen.

**Why.** Operators live in chat, and alerts belong there — but chat is a transport, not a
notification system. Keeping it a kernel transport, **independent of the bell store**, lets an alert
go to chat, to the bell, or both, without either knowing about the other.

**Rules.**
- **Callers never import it.** The ops dispatcher and the notification channel layer reach it through
  `registry.notification_channels` or a service contract ([`EXTENSIBILITY.md`](EXTENSIBILITY.md)).
  When the module is absent, `chat` is simply not an available channel.
- **Installing a workspace app is deliberate**: the bot token has no environment fallback; it is
  entered in settings and verified by a probe on save.
- **Respect the provider's limits** by chunking blocks (§ 10) and by honouring `429` + `Retry-After`
  through the provider error hierarchy.
- **Links in messages are absolute** from `FRONTEND_BASE_URL`.
- **Outside production, messages go to the test destination** with the intended channel named
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 27).
- **Outcomes are recorded** in the delivery log like any other channel.

**Django + Next shape.** A plugin (`djx_chat`) registering the channel, a credential provider and
its probe. No core code changes.

**Enforced by.** The channel contract test of § 2 (it runs against every registered channel,
including this one when installed); `test_block_chunking_respects_limits`.

**Configurable, not hard-coded.** Default channel and per-purpose routes are data.

---

# Part B — Ops alerting that people don't mute

A real incident motivates every section below: **227 alert messages in 30 days, 119 of them in one
day, of which about 25 needed a human.** 127 were duplicate "scheduled command failed" messages; about
129 were one outage re-announced every hour. A director left the channel. An alert channel people
mute is worse than none — it is a record that everyone was told.

## 14. The ops alert dispatcher and its ledger   — **Tier 2 · Core**

**What.** `ops.alerts.raise_(...)` — the **only** way a monitor, health check or scheduled job
talks to operators — and `core_ops_alert`, a database ledger of every decision it makes.

**Rules.**
- **One dispatcher.** Monitors never call a transport or `notify()` directly for operator alerts.
  The dispatcher routes through the `core.ops_alert` purpose, so the destination is an
  admin-editable route (§ 1) and the channel layer's guards apply.
- **Every call writes a ledger row** with its decision — `sent`, `held` (waiting for a digest or for
  quiet hours to end) or `skipped` (cooldown, disabled, no destination) — and the reason.
- **Cooldowns read the ledger, not the cache.** "Was this `subject_key` sent in the last N minutes?"
  is a query on `core_ops_alert`. A real incident: cooldowns kept in the cache were cleared by a
  deploy and every open problem was re-announced at once.
- **A `subject_key` identifies the problem, not the check run** (`queue:billing:stalled`,
  `db:unreachable`), so repeated sightings dedupe.
- **An alert with no destination is itself a misconfiguration alert**, surfaced on the ops panel
  and the system-health page — not a silent drop.
- **A storm cap.** More than `operations.alerts.max_instant_per_hour` instant sends in an hour
  converts the rest to `held` and sends one "alert storm: N held" message.

**Django + Next shape.**

```python
ops.alerts.raise_(source="queue", reason="stalled", subject_key="queue:billing:stalled",
                  title="Billing queue stalled", body="Oldest job queued 42 min ago.",
                  kind=AlertKind.INFRA_OUTAGE)          # kind drives the instant/digest policy (§ 15)
```

`core_ops_alert`: `source`, `reason`, `kind`, `subject_key` (indexed), `title`, `body`, `decision`
(`sent · held · skipped`), `decision_reason`, `channel`, `provider_ref`, `created_at`,
`released_at` (for held rows), `digest_run` (FK to the digest that carried it, null). Index
`(subject_key, decision, created_at)`.

**Enforced by.** `tests/core/ops/test_dispatcher.py`: `test_every_call_writes_a_ledger_row`,
`test_cooldown_survives_cache_clear`, `test_no_destination_is_reported_not_dropped`,
`test_storm_cap_holds_the_excess`. `tests/architecture/test_monitors_use_the_dispatcher.py` —
modules under `*/monitors/` and every job with `owner_module="ops"` import neither channels nor
`notify`.

**Configurable, not hard-coded.** `operations.alerts.enabled`,
`operations.alerts.max_instant_per_hour` (6), cooldowns per kind (§ 15).

---

## 15. Instant or digest   — **Tier 2 · Core**

**What.** The policy that decides whether an alert interrupts someone now or waits for the digest.

**Rules.** Instant is a **short allow-list**, each with a cooldown; **everything else is held for
the digest.**

| Kind | Instant when | Default cooldown |
|---|---|---|
| `regression` | an error group marked resolved has recurred | 6 h per group |
| `infra_outage` | database, cache or broker unreachable | 30 min |
| `misconfiguration` | a route mapped to a permission that does not exist, an alert route with no destination, the encryption self-test failing, a credential marked bad | 6 h |
| `deploy_breakage` | a post-deploy check still failing after the grace period | once per deploy, after 5 min grace |
| `first_sighting` | an error group seen for the first time | once per group |
| anything else | — | held for the digest |

- **The allow-list is code; thresholds are settings.** A new kind is a reviewed change with an
  argument for why it deserves to interrupt someone.
- **A failure that is still true is not news.** Repeats inside the cooldown are `skipped:cooldown`;
  a problem that persists across many checks belongs to an incident (§ 17), not to repeated alerts.

**Django + Next shape.** `core/ops/policy.py::decide(kind, subject_key, now) -> Decision`, a pure
function over the ledger and settings — the ops panel (§ 20) calls the same function to explain
itself.

**Enforced by.** `tests/core/ops/test_policy.py` — one test per row; `test_unknown_kind_is_held`.

**Configurable, not hard-coded.** `operations.alerts.cooldown_minutes.<kind>`,
`operations.alerts.deploy_grace_minutes` (5).

---

## 16. The ops digest   — **Tier 2 · Core**

**What.** A scheduled digest, twice daily by default, that carries everything the policy held.

**Rules.**
- **One message** containing: errors since the **last sent** digest grouped by error group with
  counts; open incidents with their age; alerts held since the last digest; and the next digest time.
- **"Since the last sent digest", from the ledger** — not "the last 12 hours". A digest that failed
  to send must not make its contents disappear from the next one.
- **An explicit all-clear line when there is nothing:** "All clear since 09:00." Silence then always
  means the digest itself is broken — which the heartbeat of § 21 catches — never "probably fine".
- **Digest times are a setting, in a configured timezone** — never a constant, never a literal zone.
- It is a `DigestJob` (§ 10) with `empty="all_clear"`, so every digest rule applies.

**Django + Next shape.** Registered as the `ops.alert_digest` job; held ledger rows get `digest_run`
and `released_at` set when the digest is accepted by the provider.

**Enforced by.** `tests/core/ops/test_ops_digest.py`: `test_empty_digest_says_all_clear`,
`test_failed_digest_contents_roll_into_the_next`, `test_digest_times_follow_the_configured_timezone`.

**Configurable, not hard-coded.** `operations.alerts.digest_times` (`["09:00", "17:00"]`),
`operations.alerts.timezone` (defaults to `platform.default_timezone` —
[`CONFIGURATION.md`](CONFIGURATION.md)).

---

## 17. Incidents   — **Tier 2 · Core**

**What.** A condition-tracking primitive for monitors: open an incident when a problem appears,
announce it once, stay quiet while it persists, announce recovery once.

**Why.** The "one outage re-announced hourly" half of the incident above. A monitor that alerts on
every check that finds the problem is a monitor that says the same sentence 24 times a day.

**Rules.**
- **`incidents.sync(source, problems)`** — the monitor passes the complete set of current problems
  (`{key: label}`) every run. New keys open incidents; absent keys recover; present keys update
  `last_seen_at`.
- **`confirm_after_minutes`** (per source): a problem must persist that long before it is announced.
  A problem that appears and clears inside the window is never announced at all — flap suppression.
- **Announce once, recover once.** Opening sends one `sent` alert through the dispatcher; recovery
  sends one; nothing in between.
- **Recovery is announced only if opening was**, so an unannounced flap does not produce a lonely
  "recovered" message.
- **Passing the complete set is the contract.** A monitor that passes only new problems would
  recover everything else; a monitor that crashes passes nothing and must not recover everything —
  so `sync` is only called on a successful check run, and a failed run is reported as the monitor
  failing (§ 19).

**Django + Next shape.** `core_health_incident`: `source`, `key`, `label`, `status` (`pending · open
· recovered`), `first_seen_at`, `confirmed_at`, `announced_at`, `last_seen_at`, `recovered_at`,
`details` JSON. Partial unique `(source, key)` where `status <> 'recovered'`. The queue health of
[`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 8 is the first consumer.

**Enforced by.** `tests/core/ops/test_incidents.py`: `test_persisting_problem_announces_once`,
`test_flap_inside_confirm_window_is_silent`, `test_recovery_announced_once`,
`test_unannounced_incident_recovers_silently`, `test_one_open_incident_per_key`.

**Configurable, not hard-coded.** `operations.incidents.<source>.confirm_after_minutes` (default 0
for outages, 10 for queue depth).

---

## 18. Quiet hours   — **Tier 2 · Core**

**What.** A window in which nothing posts to operators; held alerts are released as **one** summary
afterwards.

**Rules.**
- **During the window, every instant decision becomes `held:quiet_hours`.** The ledger still
  records it.
- **On the first dispatcher run after the window** (a job every 15 minutes), release one message:
  "While it was quiet (22:00–07:00): 3 alerts held" listing them, and noting incidents that opened
  *and* recovered during the window as such.
- **Empty settings mean off.** Quiet hours are opt-in.
- **In the configured timezone**, evaluated per run — a window crossing midnight and a DST change are
  test cases, not edge cases.
- **The core does not page.** Whether anything should bypass quiet hours is a decision for an
  external on-call tool, not this dispatcher (see Pending decisions).

**Django + Next shape.** `core/ops/quiet_hours.py::in_quiet_hours(now) -> bool` and the
`ops.release_held` job.

**Enforced by.** `tests/core/ops/test_quiet_hours.py`: `test_window_crossing_midnight`,
`test_dst_transition`, `test_release_is_one_message`, `test_empty_settings_disable_quiet_hours`.

**Configurable, not hard-coded.** `operations.alerts.quiet_start`, `operations.alerts.quiet_end`
(`"HH:MM"`, empty = off), `operations.alerts.timezone`.

---

## 19. Scheduled monitors   — **Tier 2 · Core**

**What.** How a monitor job or command behaves when it finds a problem.

**Why.** 127 of the 227 messages above were "scheduled command failed" — monitors that correctly
found a problem, exited non-zero, and were then *also* reported by the scheduler as failing commands.
Every real problem arrived twice, once in a useless form.

**Rules.**
- **A monitor that finds a problem is a monitor that worked.** It reports through the dispatcher or
  `incidents.sync` and **exits 0** (a job returns normally).
- **`--strict` exits non-zero** on any finding — for humans at a terminal and for CI, never for the
  scheduler.
- **A monitor that could not check** (its own exception, a dependency it needs to run the check) is
  the thing that fails — and that failure is a `misconfiguration` or `infra_outage` alert through the
  dispatcher, with its own cooldown, not a traceback email per run.

**Django + Next shape.** `core/ops/monitor.py::MonitorCommand` — a `BaseCommand` subclass that adds
`--strict` and `--json` and routes findings; the doctors of
[`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) § 8 are built on it.

**Enforced by.** `tests/core/ops/test_monitor_command.py`: `test_findings_exit_zero_by_default`,
`test_strict_exits_nonzero`, `test_findings_are_reported_through_the_dispatcher`.

**Configurable, not hard-coded.** Nothing — this is the contract.

---

## 20. The ops panel   — **Tier 2 · Core**

**What.** An in-app page that explains the alerting system to the people it alerts: the rules, the
current state, when the next digest is, and what was sent.

**Rules.**
- **Served from the same data the code runs on** — the policy function of § 15, the settings of
  § 16–18, the ledger and the incident table. There is no second description of the rules to drift
  from the first.
- **It shows:** the instant allow-list with cooldowns; open incidents; the held count; whether quiet
  hours are active now and when they next start; the next digest time; the destination each alert
  goes to (and a warning if none); the last ten messages with their decisions; a "Send test" button
  for the ops route.
- **Settings are editable from the panel** for users holding `core.ops.manage`; edits are audited.

**Django + Next shape.** `GET /api/ops/alerts/overview/` (`core.ops.view`); a settings page under
`src/core/` that renders it.

**Enforced by.** `tests/core/ops/test_overview.py` — the overview's rules come from `policy.decide`'s
table (assert identity, not equality of copies); `test_missing_destination_is_flagged`.

**Configurable, not hard-coded.** Everything shown is either code (the policy) or a setting.

---

## 21. Alerting that watches itself   — **Tier 2 · Core**

**What.** The dispatcher cannot report its own death, so something outside must notice.

**Rules.**
- **Heartbeat.** A job pings an external dead-man's-switch URL every few minutes through
  `core.http` (a fixed-host purpose). If the worker, the scheduler or the dispatcher dies, the ping
  stops and the external service alerts.
- **The all-clear digest line (§ 16)** is the human-visible heartbeat: its absence at 09:05 means the
  system is broken.
- **Metrics-side rules** — absent-series detection, receivers with no destination, notification
  pipeline failures — are specified in [`OBSERVABILITY.md`](OBSERVABILITY.md).

**Django + Next shape.** The `ops.heartbeat` job; `OPS_HEARTBEAT_URL` in env.

**Enforced by.** `dbx.notify.E020` — `APP_ENV=production` and `OPS_HEARTBEAT_URL` unset (a warning,
not an error: a product may use a different mechanism, but it should decide that on purpose).

**Configurable, not hard-coded.** `OPS_HEARTBEAT_URL`, `operations.heartbeat.interval_minutes` (5).

---

## 22. Summary of registries this file adds

| Registry | Contributes | Read by |
|---|---|---|
| `notification_purposes` | `Purpose` | `notify()`, the matrix, preferences, previews |
| `notification_channels` | `Channel` transports | the dispatch handler, routing and matrix screens |
| `digests` (via `jobs`) | `DigestJob` subclasses | the job runner |
| `monitors` (via `jobs`) | `MonitorCommand` jobs | the job runner, the ops panel |

---

## 23. ⚠️ Conflicts with existing docs

| File § | What it says | Fix |
|---|---|---|
| [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 12, § 18 | `EMAIL_BACKEND` defaults to console; nothing refuses console in production | Add `dbx.notify.E010` (§ 11). The default stays console for development |
| [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 18 | One `.txt` and one `.html` per message | Add a `.subject.txt` part rendered without autoescape and with newlines stripped — a subject built in Python from user data is the header-injection path |
| [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 18 and `BUILD_ORDER` 1.5b | `send_password_reset()` / `send_invitation()` as direct helpers | Correct for Phase 1. Record that when § 3 lands they become **mandatory, token-bearing purposes** behind `notify()` — never test-routable in production, never opt-out-able |
| [`DATA_MODEL.md`](DATA_MODEL.md) § 3 (Phase 2+) | `Notification` as one model | It is the in-app store of § 8, one of several tables (routes, matrix, preferences, deliveries, ops ledger, incidents). Its read/resolve split is the part that must not be simplified away |

---

## Pending decisions (for the repository owner)

1. **Live updates for the bell.** Polling the summary endpoint is specified; server-sent events need
   an ASGI deployment and a streaming endpoint behind the cookie auth. Recommendation: polling until
   a product measures it as a problem.
2. **Does anything bypass quiet hours?** Recommendation: no — the core does not page anyone. A
   product that needs paging integrates an on-call service as a channel with its own policy.
3. **Where the ops alerting lives.** Specified as core (`core/ops/`), because every product needs
   operators told about stalled queues and failed credentials. The alternative is an optional module;
   the cost is that the job monitor and credential store would then have no way to raise an alert.
4. **Sandboxed template engine.** Needed only when editable templates are built (§ 12); choosing it is
   a dependency decision that should be an ADR at that time.
5. **Email delivery log on a separate database alias.** Same question as the outbox — design for it,
   configure it when volume is measured.

---

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section.
