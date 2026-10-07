# Domain Primitives

**The small, domain-neutral building blocks every business product reinvents badly — money, document
numbers, state machines, business calendars, bulk actions, import/export, the open-findings queue,
document rendering, shared entity tables, ordered collections and generation-keyed caches — specified
once, with the rule that makes each one correct.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

---

## Scope — read first

**Owns:** the money primitive · document number sequences · the state-machine helper · the business
calendar · bulk actions · the import/export registry · the ingestion primitive (change-set DTO and its
rules) · the open-findings queue · the PDF/document rendering primitive · the shared-base-table +
per-app extension pattern · ordered child collections · generation-counter caching.

**Does not own:**

| Topic | Owner |
|---|---|
| Base models, audit engine, state-transition *history*, retention, soft delete, scoping | [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) |
| Currency / locale / timezone **settings**, lookups and vocabularies | `CONFIGURATION.md` |
| The list pipeline bulk actions re-run, the error envelope and code catalogue, files and storage | `API_PLATFORM.md` |
| Jobs, progress, outbox, reconcilers, locks | `JOBS_AND_INTEGRATIONS.md` |
| Billing/ledger/payments, tax, templated documents, the ingestion/sync **module**, helpdesk SLAs, approvals | `REUSABLE_MODULES.md` |
| Quiet hours and notification routing (a calendar *consumer*) | `NOTIFICATIONS_AND_ALERTING.md` |
| Toasts, DataTable selection, wizard components | `FRONTEND_PLATFORM.md` |
| Registry mechanics | `EXTENSIBILITY.md` |

These are primitives: **Tier 1/2 pieces live in `core`; the modules that use them heavily (billing,
documents, ingestion) are Tier 3 plugins built on them.**

---

## 0. The rules in one screen

1. **Money is `Decimal` + currency code, always paired.** An amount without its currency is a number,
   not money. → § 1
2. **One quantisation helper, one rounding mode, per-currency scale from currency metadata.** → § 1
3. **Round once, at the source; every surface consumes the final figure.** Never re-derive a total for
   display. → § 1
4. **Floats never touch money** — not in models, serializers, request bodies or the frontend, and a
   source scan proves it. → § 1
5. **An unknown price component is refused, never priced at zero.** → § 1
6. **Cross-currency arithmetic raises.** Without an FX service, a mismatch is rejected, never
   converted 1:1. → § 1
7. **Document numbers come from a dedicated sequence row per series + scope + period, locked inside
   the caller's transaction** — with an upsert first, because `FOR UPDATE` on an empty set locks
   nothing. → § 2
8. **Forms peek; saves reserve.** Opening and cancelling a form burns nothing; drafts never consume a
   number. → § 2
9. **Every state change goes through one `transition()` service** checked against a declared table,
   and a status never contradicts a write-once timestamp. → § 3
10. **Detail responses carry `allowed_transitions`**, so the UI never offers a move the API refuses.
    → § 3
11. **Business time is computed against a calendar with an explicit timezone**, never server time and
    never a hard-coded holiday list. → § 4
12. **Bulk "select all matching" re-runs the list's own pipeline**, and reports what it skipped instead
    of failing wholesale. → § 5
13. **Imports go through the same services and validators as the API**, upsert by natural key, remap
    foreign keys, and report only real changes. → § 6
14. **Exports never contain secrets** — an engine-level floor, not a per-spec list. → § 6
15. **Every external feed produces the same change-set DTO; nothing is silently created by name; a
    pull that collected nothing is a failure.** → § 7
16. **Anything a human must look at lands in one findings queue** — one open row per problem, with
    first/last seen. → § 8
17. **PDFs render in a job, from autoescaped templates, with a fetcher that cannot reach the
    network**, and a draft is never downloadable as final. → § 9
18. **Shared entities (task, comment, attachment, note) are one base table plus per-app 1:1 extension
    tables — never a GenericForeignKey.** → § 10
19. **Invalidate caches by bumping a generation, on commit; cache hits only, never a failure.** → § 12

---

## 1. Money — **Tier 1 · Core**

**What.** `core/money.py`: a `Money` value object, a `Rate` value object, one quantisation helper, an
allocation helper, model-field helpers and a serializer field. The billing module
(`REUSABLE_MODULES.md`) is built on it; so is every product that shows a price.

**Why.** Every failure below happened in a studied codebase:

- The same service showed prices differing by ±1 across five surfaces, because each surface rounded
  for itself.
- A report subtracted a monthly-rate column from a term-total column and reported a large negative
  number as revenue.
- An "average discount" averaged a percentage column mixed with fixed amounts and printed 4,672 %.
- An unrecognised price component `return 0.0`'d and under-quoted by 56 % — and survived a parity
  check because both sides of the check called the same method. **One implementation consulted twice
  is not evidence.**
- `amount: float` in an admin add-funds request body let a client float reach a balance debit
  unquantised; an audit then found 679 cargo-cult `Decimal(str(x))` calls, almost all no-ops, while
  the real hole was the float in the schema.
- A charge in one currency was about to be collected in another at 1:1 — roughly an 80× error.

### 1.1 The value objects

```python
# core/money.py (sketch)
@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str                     # ISO 4217 code, validated against the currency lookup

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            raise TypeError("Money + non-Money")
        if other.currency != self.currency:
            raise CurrencyMismatch(self.currency, other.currency)
        return Money(self.amount + other.amount, self.currency)   # both already quantised
```

- **`Money`** is an amount **quantised to its currency's scale**. `+`/`-` require the same currency;
  `* Decimal` returns an *unquantised* intermediate that must pass through `to_money()` again.
- **`Rate`** (a unit price, a per-hour rate, a percentage) is a separate type with a higher scale
  (`money.rate_scale`, default 6). **`Money - Rate` and `Money + Rate` are `TypeError`s** — that is the
  "never subtract a rate from a total" rule, enforced by the type rather than a code review.
- **Percentages are `Rate`s, fixed amounts are `Money`.** A column that mixes them is a modelling
  error; "average discount" over it is refused by construction.

### 1.2 One quantisation point

- **`to_money(value, currency) -> Money`** accepts `Decimal`, `int` or `str`. **It rejects `float`
  with a `TypeError`**: a float reaching money code is a bug to find, not to paper over with `str()`.
  Third-party JSON is parsed with `json.loads(..., parse_float=Decimal)` at the adapter boundary.
- **One rounding mode, platform-wide**: `money.rounding` (default `ROUND_HALF_UP`, the mode most
  invoicing expects). Documented once; changing it is an ADR, not a per-call argument. The helper
  raises `ValueError` on garbage, never `decimal.InvalidOperation`, so callers handle one exception.
- **Per-currency scale comes from currency metadata** — the currency lookup (`CONFIGURATION.md`),
  seeded from ISO 4217 minor units (JPY 0, EUR 2, KWD 3). **Never a default of 2** in code.
- **`allocate(total: Money, weights) -> list[Money]`** splits an amount by the largest-remainder
  method so the parts **always sum exactly** to the total (distributing a discount across lines, a
  payment across instalments). Rounding each part independently loses or invents a minor unit.

### 1.3 Round once, at the source

- **Each figure is rounded when it is computed** (a line total, a period charge) and **stored**.
  Document totals are sums of stored, quantised figures — or whatever the pluggable jurisdiction rule
  says (per-line vs per-document tax rounding is a tax-module decision, `REUSABLE_MODULES.md`), but
  decided in one place.
- **Every surface consumes the stored figure** — screen, PDF, email, export, API, report. No surface
  recomputes. "Yearly" is 12 × the rounded monthly figure; one-time charges are never multiplied.
- **Documents snapshot what they were computed from** — the rates, the customer's identity and tax
  treatment at issue — so a later master-data edit never relabels history.
- **Every price comes from master data**, never a constant or fallback. **An unresolvable component
  raises `PriceNotFound`**, which the API reports as a `409 pricing_incomplete` naming the component.
  Zero is a price someone must set, not a default.
- **Parity tests compare against independently computed expected values** (fixtures written by
  hand), never against a second call into the same pricing function.

### 1.4 Storage, API and frontend

- **Storage**: an amount column is `DecimalField(max_digits=19, decimal_places=4)` — headroom above the
  largest minor-unit scale, so the database never rounds on our behalf — **always written already
  quantised**. Rates use `decimal_places=6` or more. The currency lives **in the same row**
  (`currency CharField(3)`) or on a documented parent (an invoice's lines share the invoice's
  currency). `money_fields("total")` generates the pair and a `total` property returning `Money`.
- **Currency is an attribute of the account or document**, never of the request. A payment in a
  different currency from the invoice it settles is rejected.
- **CheckConstraints** where the domain allows: totals `>= 0`, `0 <= discount <= subtotal`.
- **API**: amounts are **JSON strings** — `{"amount": "12.50", "currency": "EUR"}`. DRF's
  `COERCE_DECIMAL_TO_STRING` stays `True` (asserted by test). Request money fields use a
  `StrictMoneyField` that **rejects JSON numbers**, because `json.loads` has already turned them into
  floats before any serializer sees them; it also rejects more decimal places than the currency allows.
- **Frontend**: amounts stay strings. Display goes through one formatter in `src/lib/money.ts`
  (`Intl.NumberFormat` with the response's currency and the bootstrap locale). **No float arithmetic
  on money, ever**: a live preview (a cart, a quote) asks the server; if a client computation is truly
  unavoidable, it uses a decimal library inside `money.ts` and nowhere else.
- **Cross-currency**: without an FX service, every cross-currency move is rejected. An FX module, if
  one exists, converts explicitly and records rate, source and timestamp on the result.

**Django + Next shape.** `core/money.py` (`Money`, `Rate`, `to_money`, `allocate`, `CurrencyMismatch`,
`PriceNotFound`), `core/models/fields.py` (`money_fields`), `core/api/fields.py` (`MoneySerializerField`,
`StrictMoneyField`), `frontend/src/lib/money.ts` (`formatMoney`, the branded `MoneyString` type used by
generated API types).

**Enforced by.**

- `tests/architecture/test_no_float_money.py` — scans models and serializers for `FloatField` /
  `serializers.FloatField` whose name matches `amount|price|cost|balance|rate|total|fee|tax|discount|
  charge|credit`; **fails on an empty universe** (if it finds no money-named fields at all, the regex
  has rotted).
- `test_money.py` — float rejected; scale per currency (JPY 0, KWD 3); `allocate()` sums exactly for
  1,000 random splits; `Money + Money(other currency)` raises; `Money - Rate` raises.
- `test_money_api.py` — a JSON number for an amount → `400`; an amount with too many decimals → `400`;
  responses are strings.
- A frontend lint rule forbidding `parseFloat` and arithmetic operators on `MoneyString` outside
  `money.ts` (via the branded type).

**Configurable, not hard-coded.** `money.rounding` · `money.rate_scale` · currency metadata from the
currency lookup · the platform/tenant default currency from `CONFIGURATION.md`. **No currency code or
symbol literal appears in core** — a scan in `CONFIGURATION.md` enforces it.

---

## 2. Document number sequences — **Tier 2 · Core**

**What.** `core/numbering.py`: human-facing document numbers (`INV-202609-0042`, `ORD-000913`) from a
dedicated sequence table, per series, scope and period, with configurable patterns and resets.

**Why.** "Scan the documents for the current max and add one" collided under concurrency and across
sites. A settings-row counter locked with `SELECT … FOR UPDATE` still minted duplicate `-0001`s on a
fresh environment — because **`FOR UPDATE` on an empty result set locks nothing**, so two first callers
both saw "no row", both created it, and the loser's billing run died on an `IntegrityError`. Several
series sharing one settings row serialised each other. And forms that pre-allocated a number on open
left audit-visible holes every time someone cancelled.

### 2.1 The table

`core_sequence(series CharField(64), scope_key CharField(64, default=""), period_key
CharField(16, default=""), last_value BigIntegerField, updated_at)` with
`UniqueConstraint(fields=["series", "scope_key", "period_key"], name="core_sequence_uq")`.

- **One row per series + scope + period.** Invoice minting never waits on order numbering.
- **A separate series per document kind** — invoice, credit note, statement, order, quote. A statement
  never consumes (or is confused with) an invoice number.
- `scope_key` is `""` for global, or a tenant/site/entity key; `period_key` is `""`, `2026`, `2026-09`
  or `2026-09-29` depending on the reset.

### 2.2 Peek and reserve

```python
def reserve(series: str, *, scope: str = "", on: date) -> str:
    if not connection.in_atomic_block:
        raise NumberingError("reserve() must run inside the caller's transaction")
    spec = registry.numbering.get(series)
    period = spec.period_key(on)                       # business timezone, § 2.3
    Sequence.objects.bulk_create(                      # upsert bootstrap: ON CONFLICT DO NOTHING
        [Sequence(series=series, scope_key=scope, period_key=period, last_value=0)],
        ignore_conflicts=True,
    )
    row = Sequence.objects.select_for_update().get(series=series, scope_key=scope, period_key=period)
    row.last_value += 1
    row.save(update_fields=["last_value", "updated_at"])
    return spec.render(row.last_value, on=on, scope=scope)
```

- **`reserve()` runs inside the caller's transaction** (it refuses otherwise). If the document's save
  rolls back, the number rolls back with it. **Call it as late as possible** in the transaction — the
  row lock serialises every document in that series until commit.
- **The upsert comes first**, then the lock: after `INSERT … ON CONFLICT DO NOTHING` the row is
  guaranteed to exist, so `FOR UPDATE` has something to lock.
- **`peek()` returns the next number without writing or locking.** Forms display it as a provisional
  hint ("will be INV-202609-0042 unless someone saves first"); the server assigns the real number on
  save. **Clients never submit the number.**
- **Drafts never consume a number.** The number is reserved when the document is *issued* (finalised),
  not when the draft is created.

### 2.3 Patterns and resets

- **Pattern tokens**: `{PREFIX}` · `{YYYY}` · `{YY}` · `{MM}` · `{DD}` · `{SCOPE}` · `{seq:0N}` —
  e.g. `"{PREFIX}-{YYYY}{MM}-{seq:04}"`. **Reset**: `daily` · `monthly` · `yearly` · `never`.
- **Validation at save time** (the settings registry validator):
  - exactly one `{seq}` token;
  - **the pattern must contain the period tokens its reset implies** — a monthly reset without `{MM}`
    renders `INV-0001` every month and collides with the unique backstop on the 1st;
  - a new pattern's next rendering must not equal any already-issued number (checked by rendering and
    querying the backstop).
- **Width is a minimum, never a truncation**: `{seq:04}` at 10,000 renders `10000`. When a series uses
  90 % of its declared width in a period, it raises a finding (§ 8).
- **The period comes from the document's issue date in the business timezone** (tenant or platform
  setting) — an invoice issued at 23:30 local on the 31st belongs to that month, whatever UTC says.
- **Changing a pattern or reset is audited** and takes effect for the next reservation.

### 2.4 Gapless vs gap-tolerant — stated per series

| | **Gapless** | **Gap-tolerant** |
|---|---|---|
| For | Legally sequential documents (tax invoices, credit notes in many jurisdictions) | Orders, tickets, internal references |
| How | `reserve()` in the caller's transaction, as above | `reserve()` on an **independent connection** in autocommit — the row lock is held for milliseconds |
| Cost | Serialises the series for the length of the document transaction | Gaps when the document transaction rolls back |
| Implies | **Documents in the series are never hard-deleted** — cancellation is a `void` status that keeps its number | Nothing |

The series declares `gapless=True|False` at registration; **there is no default** — the author must
choose, because the wrong one is either a compliance problem or a throughput problem.

### 2.5 The backstop

The document table carries `UniqueConstraint(fields=["scope_key", "number"],
condition=~Q(number=""), name="…")` — **"unique when non-blank"**, so drafts (blank number) coexist.
The sequence is the mechanism; the index is the authority.

**Django + Next shape.** `registry.numbering.register(NumberingSeries(key="billing.invoice",
label="Invoices", default_pattern="{PREFIX}-{YYYY}{MM}-{seq:04}", default_reset="monthly",
gapless=True, scope="tenant"))`; `numbering.peek()` / `numbering.reserve()`; settings keys override
pattern, prefix and reset per scope. `GET /api/core/numbering/<series>/peek/` for forms. Next: the
form shows the peeked value greyed as a placeholder, never as an input.

**Enforced by.** `test_numbering.py` on PostgreSQL: two threads reserving the first number of a new
period get `…0001` and `…0002` (the cold-start race); rollback returns the number (gapless) and burns
it (gap-tolerant); `reserve()` outside `atomic` raises; monthly pattern without `{MM}` refused; peek
writes nothing (`assertNumQueries` shows no write).

**Configurable, not hard-coded.** `numbering.<series>.pattern` · `.prefix` · `.reset` per scope;
`gapless` is code (a compliance property, not a knob).

---

## 3. The state-machine helper — **Tier 2 · Core**

**What.** `core/statemachine.py`: a declarative transition table next to a `TextChoices` status, one
`transition()` service, and the serializer support that exposes the legal moves. History is written by
`StatefulMixin` ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) § 5).

**Why.** A studied product's response-time metric was silently corrupted by missing states, and fixing
it surfaced three more defects: promotion allowed from only one of several open states; the internal
status leaking to anonymous viewers; and a spam classification that could not be undone.

**Rules.**

- **`TextChoices` + `CharField`, never a database enum type.** Adding a state is a code change;
  **stored values are never renamed** (labels change freely); removing a state needs a data migration
  that moves its rows first.
- **`TRANSITIONS: dict[Status, set[Status]]`** declared on the model, validated at boot: every status
  is a key, every target is a status, every non-initial status is reachable from the initial one.
- **One service, `transition(obj, to, *, actor, reason="")`**:
  1. checks the move is declared and the actor holds the transition's permission (if any);
  2. runs guards — **a status must never contradict a write-once timestamp** (a record with
     `first_responded_at` set cannot return to `new`);
  3. applies it with a **conditional update** — `filter(pk=obj.pk, status=from_state)` — so two
     concurrent transitions cannot both win (`0` rows → `409 transition_conflict`);
  4. sets write-once timestamps if they are still null, bumps `version`, records the transition and a
     `status_changed` audit row, and emits the domain event `on_commit`.
- **Write-once timestamps are declared** (`WRITE_ONCE = {"first_responded_at": RESPONDED_STATES}`) and
  backed by a `CheckConstraint` (`condition=~Q(status="new") | Q(first_responded_at__isnull=True)`).
- **Terminal states that are mutually consistent stay mutually reachable** — `won ↔ lost`,
  `resolved ↔ closed` — with `reason` required. Correcting a mis-click is not rewriting history; the
  transition table records both moves.
- **A "junk" classification reachable from anywhere must be reversible** — back to the state it came
  from (read from the transition history) or to the initial state.
- **`allowed_transitions`** is a field on every detail response: `[{to, label, requires_reason}]`,
  computed by the same checks `transition()` runs (permissions and guards included). The UI renders
  exactly these; it never offers a move the API would `409`.
- **Public and anonymous views mask internal statuses** through a declared `PUBLIC_STATUS` map
  (`junk` and `open` both read as "received") — do not tell a spammer they were classified, and do not
  leak triage timing.
- **Direct assignment is forbidden**: a source scan fails on `.status =` outside the model module and
  `transition()` (ratchet), and `StatefulQuerySet.update(status=…)` raises.

**Django + Next shape.**

```python
class Enquiry(StatefulMixin, AuditedModel):
    class Status(models.TextChoices):
        NEW = "new"; OPEN = "open"; WON = "won"; LOST = "lost"; JUNK = "junk"

    TRANSITIONS = {
        Status.NEW: {Status.OPEN, Status.JUNK},
        Status.OPEN: {Status.WON, Status.LOST, Status.JUNK},
        Status.WON: {Status.LOST}, Status.LOST: {Status.WON},       # correctable, reason required
        Status.JUNK: {Status.NEW, Status.OPEN},                      # reversible
    }
    REASON_REQUIRED = {(Status.WON, Status.LOST), (Status.LOST, Status.WON)}
    PUBLIC_STATUS = {Status.NEW: "received", Status.OPEN: "received", Status.JUNK: "received"}
```

`AllowedTransitionsField` for serializers; `POST /api/<module>/<resource>/<id>/transition/`
`{to, reason}`. A library may back the helper if all the rules above hold; most decorate methods that
mutate in memory without recording history, so check before adopting one.

**Enforced by.** `test_statemachine_graphs.py` iterates every registered stateful model: complete,
reachable, correction pairs have reasons. Per model: `test_concurrent_transition_one_409s`,
`test_cannot_contradict_write_once_timestamp`, `test_public_serializer_masks_status`,
`test_allowed_transitions_match_what_the_api_accepts` (tries every pair).

**Configurable, not hard-coded.** The table is code. Which states count for SLAs or eligibility are
named constants (`DATA_LIFECYCLE.md` § 5), not settings.

---

## 4. The business calendar — **Tier 2 · Core**

**What.** `core/calendar.py`: a calendar primitive — weekly working hours, holidays and date overrides,
and an explicit timezone — with functions for business-time arithmetic. Consumers: SLA timers (the
helpdesk module), due dates ("30 business days"), job windows (maintenance windows in the jobs
registry), quiet hours (`NOTIFICATIONS_AND_ALERTING.md`).

**Why.** A studied SLA engine hard-coded its default timezone; another team would have needed a second
calendar for billing due dates and a third for job windows. Every hand-rolled "add business hours"
gets DST, midnight-spanning shifts or the year boundary wrong at least once.

**Rules.**

- **A calendar always has an explicit IANA timezone**; computation happens in local time via
  `zoneinfo` and results are returned as UTC instants. Never server time, never a default zone in code.
- **Weekly schedule** = zero or more intervals per weekday; an interval crossing midnight is stored as
  two. **Overrides** by date (half-day, extra working day) beat the weekly schedule; **holidays** beat
  both.
- **Holidays are data** — entered, imported from an ICS file, or copied between calendars. No national
  holiday list ships in code.
- **Resolution is scoped**: record → tenant → platform default, through the settings cascade. A
  built-in `24x7` calendar exists so "no business hours" is explicit, not a null.
- **Consumers snapshot what they used.** An SLA stamps the calendar id and policy version onto the
  record at creation, so a later calendar edit does not retroactively change a running timer
  (history is re-evaluated only by an explicit, audited recompute).
- **Pause accounting belongs to the consumer** (an SLA paused while awaiting the customer); the
  calendar only answers time questions.
- **DST rules**: adding business time across a spring-forward gap skips the missing hour; across
  fall-back counts the repeated hour once. Stated, and tested.

**Django + Next shape.** Models `BusinessCalendar(key, name, timezone, is_default)`,
`WorkingInterval(calendar, weekday, start, end)`, `CalendarOverride(calendar, date, intervals JSON,
kind: holiday|modified|extra_day, name)`. Service API:
`is_open(cal, at)` · `next_open(cal, at)` · `add_business_time(cal, start, timedelta)` ·
`business_time_between(cal, a, b)` · `add_business_days(cal, date, n)` · `open_intervals(cal, from,
to)`. Holiday sets cached per `(calendar, year)` with generation invalidation (§ 12).
`GET /api/core/calendars/<key>/open-intervals/?from=&to=` for UIs that draw them.

**Enforced by.** `test_calendar.py` with frozen time: spring-forward and fall-back weeks, a Friday
22:00–02:00 shift, 31 December → 2 January over a holiday, 29 February, `add_business_days` over a
long weekend, `24x7` identity.

**Configurable, not hard-coded.** Calendars, intervals and holidays are data; the default calendar per
scope is a setting (`calendar.default`).

---

## 5. Bulk actions — **Tier 2 · Core**

**What.** One contract for "do X to these rows": an endpoint shape, a resolver, a result object and a
UI rule.

**Why.** Two definitions of "the rows on screen" drift, "and the drift is invisible until it deletes the
wrong rows". Bulk endpoints that skipped the single-item guard leaked across tenants. And bulk
operations failed silently, or all-or-nothing because one row in two hundred was protected.

**Rules.**

- **A request names its rows one of two ways**: `{"ids": [...]}`, or
  `{"query": {<the list's own query params>}, "exclude_ids": [...]}` for "select all N matching".
- **The query form re-runs the list's own pipeline** (`API_PLATFORM.md`) over the list's own scoped
  queryset — the same filter, search and scope code, not a reimplementation in the bulk view.
- **`expected_count` guards "select all"**: the client sends the count it displayed; if the resolved
  set differs, the server answers `409 bulk_selection_changed` with the new count rather than acting on
  rows the user never saw.
- **Writes use `writable_by()`** ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) § 12.4), so a bulk action can
  never reach further than the single-item endpoint.
- **Protected targets are filtered out, not rejected wholesale** — system rows, the caller's own
  account, rows in a state that forbids the action, rows not writable. Each skip carries a reason code.
- **The result says what happened**:
  `BulkActionResult{requested, affected, skipped, skipped_reasons: [{id, code, message}], batch_id,
  job_id | null}`.
- **One `batch_id` ties every audit row of the action together** (`DATA_LIFECYCLE.md` § 4), and the
  feed shows one summary row.
- **Above `bulk.max_sync_rows` the action runs as a job** with progress (`JOBS_AND_INTEGRATIONS.md`);
  the response carries `job_id` and the same result object arrives when it finishes.
- **The UI toast for a bulk result never auto-dismisses when anything was skipped**, and lists the
  reasons (`FRONTEND_PLATFORM.md`).

**Django + Next shape.** `core/bulk.py`: `@bulk_action("deactivate", permission="users.users.update")`
on a viewset method receiving the resolved queryset; `POST /api/<module>/<resource>/bulk/<action>/`;
`BulkActionResultSerializer`. Next: the DataTable selection model sends `ids` or `query +
exclude_ids + expected_count`.

**Enforced by.** `test_bulk.py`: query form and list endpoint return the same set for every filter
fixture; a cross-tenant id is skipped (not acted on, not leaked); a protected row is skipped with its
reason while the rest succeed; changed selection → 409.

**Configurable, not hard-coded.** `bulk.max_sync_rows` (default 500); actions via decorator
registration.

---

## 6. The import/export registry — **Tier 2 · Core**

**What.** `core/dataio`: apps register what can be exported and imported; the engine handles the file
formats, ordering, key resolution, diffing, auditing and the wizard.

**Why.** Environment-to-environment moves and legacy imports otherwise mean hand-written SQL, and every
module's hand-rolled CSV importer re-learns natural keys, foreign-key remapping, per-row errors and
CSV injection one bug at a time.

### 6.1 The spec

```python
registry.dataio.register(ExportSpec(
    key="crm.contacts", label="Contacts", model="crm.Contact", order=30,
    requires=("crm.companies",),                 # companions pulled in server-side too
    natural_key=("email",), natural_key_fallback=("external_ref",),
    exclude_columns=("portal_token",),
    include_deleted=False, extension="crm",
))
```

### 6.2 Export rules

- **A self-describing envelope**: `{"_meta": {"format": "djx-bundle", "format_version": 1,
  "platform_version", "app": "<slug>", "specs": {...}, "exported_at", "exported_by": "<label>",
  "counts": {...}}, "<spec key>": [rows]}`. Our own export is recognisable; a foreign or legacy file is
  treated as one.
- **Foreign-key-dependency order**, computed from the specs; cycles are an error at registration.
- **`requires` is enforced server-side** — a hand-crafted `?specs=crm.contacts` still brings companies.
- **Foreign keys export as the target's natural key** where it has one, otherwise as `<name>_id` for
  remapping.
- **A never-export floor at engine level**: password hashes, token hashes, MFA secrets, encrypted
  credential fields and anything the scrubber classifies as secret are excluded regardless of the spec.
- **Exports respect permission and scope** — the rows are `visible_to()` the requester; an export is
  audited with its counts.
- **CSV/Excel cells starting with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with `'`**
  (CSV/formula injection). CSV is UTF-8 with a BOM so spreadsheet tools read it correctly.

### 6.3 Import rules

- **Imports go through the model's services and shared validators**, never raw ORM inserts — an import
  cannot bypass an invariant, a permission or `writable_by()`. The requester needs create/update
  permission on each spec.
- **A never-import floor**: `is_superuser`, password hashes, permissions and role grants, `is_system`
  rows, pks of system rows. Changing those is an administrative action, not a data load.
- **Per-row natural-key upsert**, using the fallback key only when the primary natural key is blank.
- **Foreign-key remap**: file id or natural key → landed pk, per spec, in dependency order; an
  unresolved reference is `NULL` if nullable, otherwise a row error.
- **Canonicalised comparison** so the diff reports only real changes: decimals normalised, instants to
  UTC ISO-8601, booleans from `true/1/yes`, JSON with sorted keys, the field's own blank-vs-null rule.
  **Nulls for NOT NULL columns are dropped** so model defaults apply.
- **Timestamps are preserved in import mode** — which is why `created_at` is not `auto_now_add`
  (`DATA_LIFECYCLE.md` § 1).
- **Preview → resolve → confirm.** Upload → parse → validate → a preview of creates / updates (with the
  field-level diff) / unchanged / errors / near-duplicates → the user resolves near-duplicates (merge,
  create, skip) → confirm. **Confirm is bound to the preview** by a token over the file hash, spec
  versions and the target rows' versions; if anything changed, confirm answers `409
  import_preview_stale` and re-previews.
- **Near-duplicates use normalised exact matching**, per entity profile (casefold, collapse
  whitespace, strip legal-form suffixes for company names, keep model numbers intact) — never fuzzy or
  trigram matching, which silently merges things that are merely similar.
- **Per-row error reporting**: row number, column, code, message; a downloadable error file with the
  original rows plus an error column.
- **Atomicity is stated in the preview**: up to `import.max_atomic_rows` the whole import is one
  transaction; above it, the import runs as a job committing per chunk, and the preview says "partial
  imports are possible" before the user confirms.
- **Audit**: per-entity history via import mode (`DATA_LIFECYCLE.md` § 4.3) sharing one `batch_id`,
  plus **one feed row per import** listing counts and every overwritten field.
- **Adapters are resilient and extension-aware**: an app can attach extra rows on export or
  post-process on import; an adapter's exception is captured into the report and never aborts the
  others; a soft-disabled plugin's specs are hidden.

### 6.4 Templates and formats

- **"Download template"** is generated from the spec: a header row of labels, a hidden row of machine
  keys, an example row, and in Excel an instructions sheet and drop-down validation lists for choices
  and lookups.
- **Excel via `openpyxl`** (`read_only=True` streaming for large files); CSV with delimiter sniffing
  limited to `,` `;` and tab, and BOM detection.
- **Upload limits and content sniffing** come from the file-policy registry (`API_PLATFORM.md`).
- **Large imports are jobs** with progress; the Next wizard polls the job.

**Django + Next shape.** `core/dataio/{registry,export,import_,canonical,templates,views}.py`;
`POST /api/core/dataio/export/` (job), `POST /api/core/dataio/import/preview/`, `POST
…/import/confirm/`, `GET …/templates/<spec>/`. Next: a four-step wizard (upload → preview → resolve →
confirm) and a job-progress panel.

**Enforced by.** `test_dataio.py`: export→import round trip into an empty database reproduces rows and
FKs; re-importing the same file reports zero changes (canonicalisation works); a secret column never
appears even when a spec forgets to exclude it; `requires` pulls companions; a formula cell is escaped
and round-trips; a never-import field in the file is refused; a stale preview 409s.

**Configurable, not hard-coded.** `import.max_atomic_rows` · `import.max_rows` · normalisation profiles
per entity (registered) · specs via registry.

---

## 7. Ingestion discipline — **Tier 3 · Module**

**What.** The primitive every inbound feed (a CSV drop, a spreadsheet sync, an upstream API, a device
poll) builds on. The full sync framework with its review screens is a module (`REUSABLE_MODULES.md` §
ingestion); **the DTO and these rules are the contract** any module that ingests must follow.

**Why.** Silent auto-creation by name duplicated vendors and catalogue models; silent deletes lost
inventory; and a sync that "succeeded" having collected nothing let stale data look current for weeks.

**Rules.**

- **One canonical change-set DTO from every source adapter** — `ChangeSet(source, collected_at,
  items=[Change(op, entity, key, fields, evidence)])`. Adapters are thin; they never write.
- **A closed set of audited apply operations** per owning app (`create` · `update` · `upsert` ·
  `remove` · `adopt`), each a service. Nothing else mutates from a feed.
- **Unmatched data becomes a pending change** for a human to claim or dismiss — never an automatic
  create or delete. The first sync of an empty target is an explicit *baseline*. Bulk "accept all" and
  "re-baseline" are deliberate, audited levers.
- **No silent creates on name resolution**: normalised exact matching (§ 6.3's profiles), plus a
  confirmation queue for near-duplicates.
- **A pull that collected nothing is a failure**, reported as such (and a finding, § 8), unless the
  source declared "empty is valid".
- **Every run reports what it *applied*, not what it saw** — one feed row per run
  (`DATA_LIFECYCLE.md` § 4.8).

**Enforced by.** Contract tests in the module: an adapter cannot import the apply services; an empty
pull is `failed`; an unmatched item creates a `PendingChange`, never a row.

**Configurable, not hard-coded.** Normalisation profiles and per-source "empty is valid" flags.

---

## 8. The open-findings queue — **Tier 2 · Core**

**What.** `core_finding`: one table where anything a machine has noticed and a **human must decide**
lands — reconciler give-ups, ambiguous (`unknown`) outbox sends, webhook endpoints that tripped their
breaker, configuration drift, storage objects retention could not delete, numbering series near their
width.

**Why.** Reconcilers that auto-fix destructively cause incidents; reconcilers that alert on every pass
get muted. A studied platform settled on recording drift once, keeping it open until resolved, and
keeping resolved findings as history.

**Rules.**

- **One open row per problem**: `UniqueConstraint(fields=["kind", "object_type", "object_id"],
  condition=Q(resolved_at__isnull=True), name="core_finding_open_uq")`. A re-detection **touches** the
  open row (`last_seen_at`, `occurrences += 1`, `details` refreshed) instead of inserting.
- **Resolved findings are history**: resolving sets `resolved_at`, `resolved_by`, `resolution` (from
  the kind's allowed set — e.g. `retried` · `restored` · `auto_cleared` · `dismissed`) and a note. A
  later recurrence opens a **new** row.
- **Auto-clear on recovery**: the detector calls `findings.clear(kind, obj)` when the condition is gone
  (`resolution="auto_cleared"`, `resolved_by=NULL`).
- **Kinds are registered** with label, severity, owning module, the permission to view and act,
  allowed resolutions and a runbook link. An unregistered kind is refused at write.
- **Notify on open, not on touch** — one notification when a finding opens (and optionally when it has
  stayed open past a threshold), never one per detection pass (`NOTIFICATIONS_AND_ALERTING.md`).
- **Scoped** like everything else — a tenant's findings are visible to that tenant's operators only.
- **Metrics**: open findings by kind and severity (`OBSERVABILITY.md`); resolved rows age out through a
  retention policy.

**Django + Next shape.** Columns: `kind`, `object_type`, `object_id` (snapshots, as in the audit log),
`title`, `details` JSON, `severity`, `first_seen_at`, `last_seen_at`, `occurrences`, `resolved_at`,
`resolved_by`, `resolution`, `resolution_note`, `tenant_id` if tenancy. Service: `findings.raise_or_touch(kind,
obj, details)`, `findings.clear(kind, obj)`, `findings.resolve(finding, resolution, note, actor)`.
`GET /api/core/findings/`, `POST …/<id>/resolve/`. Next: one queue screen, filterable by kind, with
per-kind action buttons registered by the owning module.

**Enforced by.** `test_findings.py`: two detections → one open row with `occurrences=2`; resolve then
detect → a second row; unregistered kind refused; clear on recovery.

**Configurable, not hard-coded.** Kinds via registry; the "still open after N hours" re-notify threshold
per kind; resolved-finding retention via `DATA_LIFECYCLE.md` § 6.

---

## 9. PDF and document rendering — **Tier 3 · Module**

**What.** The primitive under any generated document (invoice, quote, delivery note, certificate,
report): HTML built from a template, converted to PDF with WeasyPrint, in a job, stored through the
storage abstraction. The templated-documents **module** (authored templates, merge fields, approval
chains) is `REUSABLE_MODULES.md`; these rules bind it.

**Why.** A reseller-controlled logo URL fetched server-side during rendering is SSRF; one studied
renderer used a no-network fetcher for one document type and forgot it for three others.
Operator-authored templates evaluated with a full template engine are server-side template injection.
And a draft downloadable as a clean PDF gets sent to a customer as final.

**Rules.**

- **Autoescape always.** Platform templates use Django's engine (autoescape on; `mark_safe` on user
  content is a review blocker). **Operator-authored templates use a sandboxed engine** with an
  allow-listed token context, never Django templates with the full context.
- **A no-network URL fetcher on every render**: WeasyPrint's `url_fetcher` allows only `data:` URIs and
  an allow-list of local static paths (fonts, the platform's own assets); everything else raises.
  Images a user uploaded are inlined as `data:` URIs by the HTML builder after going through the
  storage layer's own permission check.
- **Split HTML building from PDF building**: `build_html(doc) -> str` is pure and fast and is what tests
  assert on; `render_pdf(html) -> bytes` is the only WeasyPrint call. Tests never compare PDF bytes.
- **Render in a job** with a time limit — WeasyPrint is CPU-heavy and can take seconds; a request
  thread is not the place. The UI polls or receives a notification.
- **Drafts are never downloadable as final**: drafts render with a watermark (and, where the domain
  requires it, a "not a tax invoice" style legend); only a finalised document produces the clean file.
- **A final document is immutable**: it is rendered once from the document's **snapshot**, stored with
  its SHA-256, template version and renderer version. Re-rendering creates a new version; it never
  replaces the file a customer already received.
- **Stored via the storage abstraction** (`API_PLATFORM.md`), private by default, served through an
  authenticated view.
- **Fonts are bundled in the image**, never fetched; the image carries the system libraries WeasyPrint
  needs (`OPERATIONS.md`).

**Django + Next shape.** `core/rendering/{html,pdf,fetchers}.py`: `build_html(template, context)`,
`render_pdf(html, *, base_url)`, `safe_url_fetcher`; a `RenderedDocument(target_type, target_id, kind,
version, status draft|final, file, sha256, template_version, rendered_at, rendered_by)` model in the
documents module.

**Enforced by.** `test_rendering.py::test_fetcher_refuses_http_and_file_urls`,
`test_every_render_call_passes_the_safe_fetcher` (source scan: any `HTML(` construction outside
`render_pdf` fails), `test_draft_download_is_watermarked`, `test_final_is_not_re_rendered`.

**Configurable, not hard-coded.** Watermark text and legends are settings/template data; the static
allow-list is derived from `STATIC_ROOT`, not listed by hand.

---

## 10. Shared base table + per-app 1:1 extension — **Tier 2 · Core**

**What.** The pattern for entities many modules share — `Task`, `Comment`, `Attachment`, `Note`. Core
owns a base table with only the common columns plus `source_app`; a module that needs more adds **its
own extension table** with a `OneToOneField` to the base as its primary key and typed foreign keys to
its own records.

```python
# core
class Comment(AuditedModel):
    body = models.TextField()
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    source_app = models.CharField(max_length=64, db_index=True)   # registry key of the owner

# crm (plugin), its own migration
class DealComment(models.Model):
    comment = models.OneToOneField("core.Comment", on_delete=models.CASCADE, primary_key=True)
    deal = models.ForeignKey("crm.Deal", on_delete=models.CASCADE, related_name="comments")
```

**Why.** A GenericForeignKey has no referential integrity, no cascade, no efficient join and no
database-level scoping; a wide shared table that every plugin adds columns to couples every plugin to
every other. The base table never changes as modules join, and each module's links stay strongly
typed foreign keys.

**Rules.**

- **The base table has no plugin columns and no generic link.** Core services (mentions,
  notifications, search, retention, audit) operate on the base row; the module's extension answers
  "attached to what".
- **Queries go through the extension** (`Comment.objects.filter(dealcomment__deal=deal)` via the
  module's queryset method), and scoping follows the extension's parent.
- **Deleting the parent cascades the extension; the base row is removed by the module's service** (or a
  retention policy for orphans) — stated per entity.
- **GenericForeignKey is allowed only where no foreign key is wanted at all** — evidence tables, which
  use snapshots instead (`DATA_LIFECYCLE.md` § 4.1).

**Enforced by.** `test_extensions.py`: every model with a `OneToOneField` to a core shared entity uses
`primary_key=True`; core shared-entity tables contain no field added by a plugin migration (compare the
core app's migration state with the database columns).

**Configurable, not hard-coded.** `source_app` values come from the module registry.

---

## 11. Ordered child collections — **Tier 2 · Core**

**What.** A helper that replaces the ordered children of a parent (line items, checklist steps, form
fields) with a new ordered list, under a `UniqueConstraint(fields=["parent", "position"])`.

**Why.** A single-pass reassignment violates the unique constraint whenever a kept item moves into a
position another kept item still holds (swap items 1 and 2: the first `UPDATE` collides).

**Rules.**

- **Two passes in one transaction**: first move every kept row to a temporary non-colliding position
  (negate it, or offset by the collection size) and flush; then write the final positions and insert
  new rows; delete removed rows first of all.
- **On PostgreSQL a `deferrable=Deferrable.DEFERRED` unique constraint** is the cleaner alternative —
  but SQLite does not support it (⚠️ C1), so the two-pass helper is the portable default.
- **A reorder endpoint takes the complete ordered id list** and refuses (`409 collection_changed`) if
  the submitted set differs from the current set — reorder must not double as add or delete.
- **Extract the helper at its third genuine consumer**, not its second; the first two write it inline
  against this rule.

**Enforced by.** `test_ordered.py`: swap, reverse, insert-in-middle and remove-and-shift all commit
under the constraint.

**Configurable, not hard-coded.** Not applicable.

---

## 12. Caching by generation counter — **Tier 2 · Core**

**What.** `core.cache.namespaced("catalog")`: keys shaped `"{ns}:{gen}:{key}"`, where `gen` lives at
`"gen:{ns}"`; invalidating the namespace is one atomic `incr`.

**Why.** Delete-by-pattern scans are slow on a large cache and racy against concurrent writers.
Caching a miss made an integration look broken for the whole TTL with no request anyone could
inspect. And a cache bust issued *before* commit let a concurrent request re-populate the cache from
the pre-commit data.

**Rules.**

- **Invalidate by `incr("gen:{ns}")`**; old keys simply age out. A missing generation key initialises
  to 1 (Django's `incr` raises `ValueError` on a missing key — the helper handles it).
- **Bump on commit**: `transaction.on_commit(lambda: ns.bump())` — never inside the transaction that
  changed the data.
- **Cache hits only**: a lookup that failed, timed out or found nothing is **not** cached. (Negative
  caching, where genuinely wanted, is an explicit, short-TTL, separately named namespace.)
- **Cache unavailable → compute directly**, logged and counted; a performance cache must never become
  an outage. *Correctness* caches — the permission-version counter and throttles in
  `AUTH_BLUEPRINT.md` § 17.4 — follow their own fail-closed rules and require a shared cache.
- **A kill switch per namespace** (`cache.<ns>.enabled`) and a TTL setting (`cache.<ns>.ttl_seconds`).
- **Never put a secret in the shared cache** — cache the non-secret fingerprint; keep built clients with
  credentials in process memory.

**Django + Next shape.** `ns = namespaced("catalog"); ns.get_or_compute(key, fn)`, `ns.bump()`. The
`AUTH_BLUEPRINT.md` permission-version counter is built on the same helper so there is one mechanism.

**Enforced by.** `test_cache_namespaces.py`: bump makes the next read miss; a failed compute is not
cached; a bump inside a rolled-back transaction does not happen; cache down → value still returned.

**Configurable, not hard-coded.** `cache.<ns>.enabled` · `cache.<ns>.ttl_seconds`; a shared cache
backend is required outside development (`AUTH_BLUEPRINT.md` A19).

---

## 13. ⚠️ Conflicts with existing docs

| # | Existing doc says | The problem | Recommended fix |
|---|---|---|---|
| **C1** | [ADR-0005](../adr/0005-sqlite-for-dev-postgres-by-url.md) — SQLite for development, PostgreSQL by URL | `select_for_update()` is **silently ignored on SQLite**, so § 2's concurrency guarantee exists only on PostgreSQL (SQLite serialises writers database-wide instead, trading duplicates for `database is locked`). Deferrable unique constraints (§ 11) and the independent-connection reservation (§ 2.4) also behave differently. `TECH_DEBT` DB-12 covers the general case | Concurrency tests for numbering, transitions and bulk actions are `postgres_only` and must run in CI on PostgreSQL; the portable two-pass ordering helper is the default |
| **C2** | `DATA_MODEL.md` § 3 — `Attachment`, `Notification` listed as Phase 2 core entities with no linking rule; `ActivityLog` uses a generic FK | A shared entity linked by GenericForeignKey loses integrity, cascade and scoping | Build `Attachment` (and `Comment`, `Note`, `Task` if added) on the § 10 pattern; the audit log's target becomes a snapshot (`DATA_LIFECYCLE.md` C2) |
| **C3** | `API_DESIGN.md` § Responses — `409` for "a real state clash"; no codes defined for bulk, numbering or transitions | Not a contradiction; the codes need to exist in the one catalogue | Add `stale_version`, `transition_conflict`, `bulk_selection_changed`, `import_preview_stale`, `restore_conflict`, `pricing_incomplete`, `collection_changed` to the error-code catalogue (`API_PLATFORM.md`) |

---

## Pending decisions (for the repository owner)

1. **Money storage** — the two-column helper specified here (recommended: no dependency, explicit
   pairing) or a third-party money field library.
2. **The platform rounding mode** — `ROUND_HALF_UP` (recommended default) or banker's rounding
   (`ROUND_HALF_EVEN`). Chosen once; an ADR.
3. **Which document series are gapless** in the products you expect — decided per series at
   registration; the modules that ship series should say so in their docs.
4. **The rendering stack** — WeasyPrint (recommended; pure HTML/CSS) and the system libraries it adds to
   the image (`OPERATIONS.md`).
5. **Holiday data** — manual entry plus ICS import (recommended), or a maintained holiday-data package
   behind the same import.
6. **The bundle format** — JSON bundle for environment moves plus XLSX/CSV for people (recommended), or
   XLSX only.
7. **One findings queue or several** — one core queue (recommended) versus a queue per module; per-module
   queues fragment exactly the surface a human is meant to watch.

---

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section.
