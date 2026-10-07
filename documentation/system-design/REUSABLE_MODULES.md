# Reusable modules — optional plugins every kind of product keeps rebuilding

**The specification for the optional modules — billing, approvals, documents, ingestion, alerts,
automation, help centre, helpdesk, tenancy, search, AI assistant and feedback — that ERP, CRM,
e-commerce and SaaS products each end up building, written down once, with the rules that
real incidents taught.**

> 🔜 **Blueprint — nothing in this file is built yet.** It is the specification to build against. Priority and
> sequencing live in [`../planning/PLATFORM_BLUEPRINT.md`](../planning/PLATFORM_BLUEPRINT.md) and
> [`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md). When a section is built, move its "how it works" into
> `documentation/core/` and leave the rules here.

---

## Scope — read first

**Owns:** the design of each **optional** module listed in the contents — its tables, service API,
invariants, jobs, registry contributions, permissions, frontend surfaces, enforcement tests,
configuration keys and known traps. It also owns **which core seams each module needs**
(§ 1, § 16), because a module that other plugins extend cannot exist without one.

**Does not own** — link, do not re-specify:

| Topic | Owner |
|---|---|
| Money type, rounding, currency data, document number sequences, state-machine helper, business calendar, bulk actions, import/export, findings queue, PDF rendering | [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) |
| Registry mechanism, plugin discovery, soft-disable, SDK facade, event bus, UI slots | [`EXTENSIBILITY.md`](EXTENSIBILITY.md) |
| Jobs, schedules, outbox, idempotency ledger, reconciler framework, locks, webhooks in/out, SSRF-safe client, encrypted credential store, non-prod outbound guard, integration registry | [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) |
| Audit/activity engine, retention engine, soft delete, provenance, **delegation grants** | [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md) |
| Notification routing, digests, ops alert dispatcher, incidents | [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md) |
| Settings registry, feature flags, kill switches, vocabularies, branding *data* | [`CONFIGURATION.md`](CONFIGURATION.md) |
| Error envelope, idempotency keys, machine principals, uploads | [`API_PLATFORM.md`](API_PLATFORM.md) |
| Theming/white-label *rendering*, DataTable, nav gate, permission provider | [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md) |
| One scrubber, health, metrics, "zero is not a fact" | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
| Users, sessions, **invitations**, RBAC catalog | [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md), [`RBAC_DESIGN.md`](RBAC_DESIGN.md) |
| The review checklist of recurring bug classes | [`BUG_CLASSES.md`](BUG_CLASSES.md) |

**How each module is written.** Every module below answers the same ten questions, in this order:
**purpose & who needs it · data model · service API & invariants · jobs · registries (contributes /
consumes) · permissions · frontend · enforced by · configuration keys · traps.** Where a question
has no interesting answer it is omitted rather than padded.

**Naming follows the plugin rules** in
[`../planning/PLUGIN_DEVELOPMENT.md`](../planning/PLUGIN_DEVELOPMENT.md): app label = plugin name,
tables `<name>_*`, permissions `<name>.<feature>.<action>`, routes `/api/<name>/`. Examples below
use those prefixes (`billing_ledger_entry`, `approvals.proposals.decide`).

---

## 0. The rules in one screen

1. **A module is optional. Deleting it leaves a working platform** — and every plugin that
   contributed to it keeps booting, with its contributions inert. → [§ 1](#1-the-module-contract--tier-2--core-seam--process)
2. **A module other plugins extend keeps its engine in the plugin and its extension point in core.**
   A contributor never imports the engine plugin. → [§ 1](#1-the-module-contract--tier-2--core-seam--process)
3. **Every ledger has exactly one mutation entrypoint**, and a source-guard test fails any other
   write to the balance or the entry table. → [§ 2.4](#24-the-ledger--fifo-buckets-an-append-only-journal-one-entrypoint)
4. **The balance is a cached projection** of buckets and entries, reconciled nightly, never the truth. → [§ 2.4](#24-the-ledger--fifo-buckets-an-append-only-journal-one-entrypoint)
5. **Metered ≠ billed.** A billable type exists only when rate resolver, collector, line builder,
   unbilled aggregator and tax code all exist — a completeness test enumerates the registry. → [§ 2.8](#28-metered--billed--the-billable-type-registry)
6. **Collectors bill `[cursor, now)` and nothing else**, under a per-row lock with a committed
   re-read. Closing a meter is one more forward step, never `rate × lifetime`. → [§ 2.7](#27-metering--forward-only-cursor-collectors)
7. **Payment success comes only from a verified gateway path**, re-fetched from the gateway and
   matched on amount *and* currency against a server-created intent row. → [§ 2.13](#213-payments--intent-row-verify-webhooks-refunds)
8. **Every outbound money move is write-ahead**: PENDING row, commit, call, settle. An ambiguous
   outcome stays PENDING and blocks retries. → [§ 2.17](#217-credit-notes-and-outbound-money--write-ahead)
9. **One `settle()` entrypoint, a server-side method allow-list, one lock order** (document, then
   ledger account) on every path. → [§ 2.12](#212-settlement--one-entrypoint-one-lock-order)
10. **Tax context is required on the document path and fails closed to the higher-tax mode.** The tax
    point is decided once — never taxed at top-up *and* at consumption. → [§ 2.15](#215-tax--a-pluggable-jurisdiction-that-fails-closed)
11. **Currency is an attribute of the ledger account.** A mismatch is a hard reject; there is no 1:1
    conversion. → [§ 2.3](#23-accounts-billing-model-and-currency)
12. **Destructive automated steps (suspend, terminate, delete) default off, default dry-run, and
    write an audit row for every decision** — including "skipped". → [§ 2.18](#218-collections-and-dunning)
13. **Maker ≠ checker, and the superuser bypass does not cover separation of duties.** Thresholds count
    applied **and** pending proposals over a rolling window, so a grant cannot be split. → [§ 3](#3-approvals--maker-checker--tier-3--module)
14. **Apply re-checks the proposer's permission and scope at apply time.** An approval never launders
    a right the proposer has lost. → [§ 3](#3-approvals--maker-checker--tier-3--module)
15. **Ingestion never silently creates and never infers a delete from absence.** Unmatched data is a
    pending change a human decides. → [§ 5](#5-data-ingestion--sync-framework--tier-3--module)
16. **An evaluation that failed is not an evaluation that found nothing.** Alert and sync sweeps never
    resolve or apply on an errored run. → [§ 6](#6-alert-rules-engine--tier-3--module)
17. **Every nav route has a help article or a written exemption**, and every feature ships its help
    page in the same change. → [§ 8](#8-knowledge-base--in-app-help-centre--tier-3--module--process-rule)
18. **A tenant header is display, never authority.** Resolution precedence is verified custom domain,
    then subdomain, then header — and the header only for reads. → [§ 10](#10-organisations-tenancy--white-label--tier-3--module-pending-d3)
19. **Search and the AI assistant can never see more than the list endpoint would show** — every hit
    and every tool result passes through `visible_to(user)`. → [§ 11](#11-global-search--tier-2--core-seam--tier-3--module), [§ 12](#12-ai-assistant--tier-3--module)
20. **User-supplied text is data, never instructions.** Any automation that feeds it to a model or an
    agent is operator-triggered, sandboxed and credential-scoped. → [§ 12](#12-ai-assistant--tier-3--module), [§ 13](#13-feedback--bug-report-widget--tier-3--module)

---

## 1. The module contract — **Tier 2 · Core** (seam) + **Process**

**What.** The rules that make a module *optional* in fact rather than in name, and the one core seam
that lets other plugins extend a module without importing it.

**Why.** The plugin rules forbid one plugin importing another
([`../planning/CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md) § 4). Almost every
module here is *extended* by other plugins: a `compute` plugin declares a billable type, an
`inventory` plugin declares an alert source, every plugin declares approval handlers, merge fields,
search entities and AI tools. If the extension point lives in the engine plugin, every contributor
must `import djx_billing` — the exact coupling the architecture exists to prevent, and a contributor
that cannot boot when billing is not installed.

**Rules.**
- **The engine is the plugin; the extension point is core.** A contributor registers a declarative
  spec (key, label, callables) against a **named extension point** in `core.registry`. The engine
  plugin reads the extension point at boot. Core knows the *name* of the point, never its vocabulary.
- **Prefer one generic, namespaced contribution registry** —
  `registry.contributions.register("billing.billable_types", spec)` — over a new named registry per
  module. The engine declares the point and its spec shape in its own `ready()`; core stores
  contributions keyed by point name. This keeps core from growing a registry per optional module.
  The mechanism belongs in [`EXTENSIBILITY.md`](EXTENSIBILITY.md); this file lists the points each
  module needs (§ 16).
- **Absent engine ⇒ inert contributions, not a crash.** If `billing` is not installed, the
  `compute` plugin's billable-type registration is stored and never read. A system check reports
  "contributions to an extension point no installed module declares" as a **warning**, not an error.
- **Present engine ⇒ contributions are validated at boot.** The engine validates every contribution
  against its declared shape in a system check, and a broken contribution is an **error** — a
  billable type missing its collector must not boot quietly (§ 2.8).
- **Every module fails closed** on its own missing configuration: no gateway credentials means no
  payments (never a platform fallback), no tax adapter means no tax document, no source means no
  alert — each with a named reason, never a silent default.
- **Every destructive automated action ships default-off and dry-run-first**, with a feature flag
  from [`CONFIGURATION.md`](CONFIGURATION.md) and an audit row per decision.
- **Every module ships its help pages** (§ 8) and registers its permissions, nav, jobs and health
  checks through the core registries like any plugin.
- **A module's user-facing surfaces respect soft-disable** ([`EXTENSIBILITY.md`](EXTENSIBILITY.md)):
  nav, routes, search entities, help pages, alert sources and automation actions all disappear
  together when the module is disabled.

**Enforced by.**
- `tests/architecture/test_plugin_boundary.py` (already planned) — no plugin imports another.
- `tests/architecture/test_extension_points.py` — every contribution names a point some installed
  module declares, or is reported inert; every declared point's contributions pass shape validation.
  Positive control: a fixture plugin registering a malformed spec makes it fail.
- `tests/architecture/test_module_removable.py` — boots the platform with each optional module
  removed from `INSTALLED_APPS` and asserts `manage.py check` passes and the remaining plugins'
  smoke tests stay green.

**Configurable, not hard-coded.** Which modules are installed is `INSTALLED_APPS`/`plugin.toml`;
whether each is *enabled* is a flag (`<module>.enabled`).

---

## 2. Billing, ledger & payments — **Tier 3 · Module**

**Purpose.** Charging money for things: prepaid balances, usage metering, subscriptions, invoices,
payments through gateways, refunds, credit notes, tax, collections. **Who needs it:** every SaaS
(subscriptions, usage), every e-commerce product (orders, payments, refunds), most ERPs (invoicing,
receivables) and CRMs that quote and bill. It is the module with the **most expensive failure
modes in this file** — every rule below exists because its absence charged a real customer the
wrong amount.

> ⚠️ **Build order inside the module matters more than anywhere else.** Money primitive and period
> clock → ledger with its source guard → billable-type registry with its completeness test →
> collectors → documents → settlement → payments. A collector written before the ledger's single
> entrypoint exists will write the balance directly, and the guard will then have a backlog on day
> one.

### 2.0 Module map

| Sub-package (`djx_billing/…`) | Owns | § |
|---|---|---|
| `money.py` | Thin re-export of the core money primitive plus billing's precision rules | 2.1 |
| `periods.py` | The single period clock | 2.1 |
| `credit_policy.py` | Credit taxonomy and policy table | 2.4 |
| `ledger/` | Ledger accounts, buckets, entries, holds — the one entrypoint | 2.4–2.5 |
| `metering/` | Meters, collectors, close, finalize | 2.7–2.9 |
| `rating/` | Tariffs, rate stamping, re-rate, discount engine, coupons | 2.10 |
| `documents/` | Invoices, statements, pre-invoices, credit notes, snapshots | 2.11, 2.16–2.17 |
| `settlement.py` | `settle()` | 2.12 |
| `payments/` | Intent rows, gateway adapters, webhooks, refunds, per-tenant gateways | 2.13–2.14 |
| `tax/` | Tax context resolver, jurisdiction adapters, registrations | 2.6, 2.15 |
| `collections/` | Auto-pay, tranches, bank-transfer matching, dunning, executors | 2.18 |
| `gates/` | `assert_can_incur_cost`, quotas, budgets | 2.19 |
| `subscriptions/` | Fixed-period billing and commitments | 2.20 |
| `reconcilers/` | One per transient state | 2.21 |
| `accounting_sync/` | Downstream projection to an external ledger | 2.22 |
| `wholesale/` | Reseller wholesale ledger and quota pools | 2.23 |

### 2.1 Money and the period clock

**Money** is specified in [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md): `Decimal` only, one
`to_money()` helper, one rounding mode, request schemas that refuse floats, and a source-scan test
that fails a new float field named like money. Billing adds three precision rules:

- **Amounts** are quantized to the **currency's minor units** — a data attribute of the currency,
  never an assumed two places — **before every write** to a balance, bucket, entry or document.
- **Rates and unit prices** carry more precision than amounts (six decimal places is a sensible
  floor): a per-hour rate rounded to minor units loses real revenue at volume.
- **Quantities** carry their own precision (four places), separate from both.

**The period clock** is one module, `periods.py`, that owns "how many hours is a month, a quarter, a
year". **Both the quote/estimate code and the rating engine import it.** A real incident: the
customer-facing estimate priced a month at 730 hours while the engine priced it at 720, so every
quote and every invoice disagreed by about 1.4%, and nobody could say which was right.

- `hours_for(period)` resolves an enum or alias; unknown periods raise.
- Hours-per-month is one setting (`billing.hours_per_month`, default `730` = 8,760 ÷ 12). Changing
  it is a pricing change and is stamped onto new meters, never applied to open ones (§ 2.10).

**Enforced by.** `djx_billing/tests/test_period_clock_single_source.py` — scans the plugin for
numeric literals `720`, `730`, `744`, `8760` outside `periods.py` and fails; a **quote/invoice
parity test** prices the same usage through the estimate path and the invoice path and asserts equal
totals.

### 2.2 The billing account — the thing that pays

`billing_account` is the payer: one per paying subject (a user, or an organisation if tenancy exists
— § 10). It carries:

| Column | Notes |
|---|---|
| `subject_type`, `subject_id` | Who this account bills. Unique together |
| `billing_model` | `TextChoices`: `PREPAID` \| `POSTPAID`. **Explicit, never derived from a group name at call time** |
| `currency` | FK to the currency data (§ 2.3). Immutable once any entry exists |
| `billing_enabled` | Master gate; generation and collectors skip a disabled account and say so |
| `group` | Commercial tier (pricing, quota defaults, dunning policy) — FK, `SET_NULL` |
| `credit_limit`, `due_days` | Postpaid only; nullable, resolved through the override hierarchy (§ 2.19) |
| `auto_charge_enabled` | Postpaid auto-pay opt-in |

**Rule: prepaid and postpaid have separate sources of truth, and each document generator reads only
its own.** Prepaid spend is the **ledger** (debits already taken). Postpaid spend is the **meter
accrual**. A real incident: prepaid usage rows kept their accrued-cost column empty *on purpose*, so
they would not appear on invoices — a load-bearing blank that the next developer "fixed", putting
already-paid hours onto a collectible invoice. **Greenfield design: make the mode an explicit
column on every usage slice** (`settlement_mode`, § 2.9) so no generator relies on an empty field.

**Rule: switching billing model mid-period closes every open slice at the switch instant** and opens
new ones under the new mode. A slice never spans two modes.

### 2.3 Accounts, billing model and currency

**Currency is an attribute of the ledger account.** An account has one currency; invoices take their
currency from the account; every cross-document money move asserts equal currency.

- **A mismatch is a hard reject** (`CurrencyMismatch`, a 409). A real incident: a capture in one
  currency settled an invoice in another at 1:1 — for one currency pair that was an 80× error.
- **No FX service ⇒ no conversion.** If a product needs FX, it is a separate module with dated rates
  and a stamped rate on every converted entry, never a multiply in a settlement path.
- **Gateway adapters declare their supported currencies** (§ 2.13); creating an intent in an
  unsupported currency is refused before redirect, not after capture.
- **Coupons, tranches, credit notes and wholesale entries** all carry currency and are checked the
  same way.

**Enforced by.** `test_currency_guard.py` — for every settlement method in the allow-list, a
cross-currency attempt raises; a source guard asserts every function in `settlement.py` and
`payments/` that moves money calls `assert_same_currency` (AST scan for the call).

### 2.4 The ledger — FIFO buckets, an append-only journal, one entrypoint

**What.** The prepaid balance, modelled as **credit buckets** (where money came from, when it
expires, what it may pay for) plus an **append-only journal** of entries, with the account's
`balance` as a **cached projection** of both.

**Why.** A real incident: twelve code paths did `balance -= x` and built a journal row by hand. The
buckets drifted above the true balance; promotional-credit expiry then deducted
`min(bucket_remaining, balance)` — which was the customer's own paid money. Another: refunds used
plain FIFO, consumed a live promotional bucket, and the customer kept both the money and the refund.

**Credit taxonomy and policy table.** `credit_policy.py` holds a **frozen table** keyed by credit
type. Types are data; the columns are the policy:

| Column | Meaning |
|---|---|
| `refundable` | May be paid back out to the customer |
| `in_tax_base` | Counts as consideration for tax (§ 2.6) |
| `transferable` | May move between accounts |
| `excluded_billable_types` | Billable types this credit may not pay for |
| `fifo_class` | Consumption priority (lower first) |
| `label` | Display |

A sensible default set: `DIRECT` (paid money — refundable, in tax base, consumed **last**), `PROMO`,
`COMPENSATION`, `REFERRAL`, `SIGNUP_BONUS`. **`policy_for(type)` never raises**: an unknown type falls
back to the **most restrictive** policy (non-refundable, excluded from nothing it could harm, first
to be consumed), so a new credit type added without a policy row can never be refunded as cash.

**Data model.**

```
billing_ledger_account   id, billing_account FK (unique per kind), kind (CUSTOMER|WHOLESALE),
                         currency, balance DECIMAL (cached), negative_since TIMESTAMP NULL
billing_credit_bucket    id, ledger_account FK, credit_type, status (ACTIVE|HELD|EXHAUSTED|EXPIRED|CANCELLED),
                         original_amount, remaining_amount, expires_at NULL, source_reference NULL, created_at
billing_ledger_entry     id, ledger_account FK, entry_type (CREDIT|DEBIT|HOLD|HOLD_RELEASE), amount,
                         balance_after, reference_type, reference_id, performed_by NULL, ip, user_agent,
                         note, metadata JSONB (credits_consumed: [{bucket, amount}]), created_at
```

DB constraints — **in the database, not only in a serializer**
([`DATA_MODEL.md`](DATA_MODEL.md) § 4):
- `CHECK (amount > 0)` on entries — the sign is the `entry_type`.
- `CHECK (0 <= remaining_amount AND remaining_amount <= original_amount)` on buckets.
- **Partial unique `(ledger_account, credit_type, source_reference) WHERE source_reference IS NOT
  NULL`** — the replay guard. A gateway payment id, a coupon code or a compensation ticket can create
  at most one bucket per account, however many times the webhook, the retry or the admin fires.
- Indexes `(ledger_account, created_at)` and `(reference_type, reference_id)`.
- **Append-only at the database**: a migration installs a trigger refusing `UPDATE`/`DELETE` on
  `billing_ledger_entry` (and `REVOKE UPDATE, DELETE` from the application role where the deployment
  allows it). A model `save()` override is not enough — the shell and data migrations bypass it.

**The one entrypoint.** `ledger/services.py`:

```python
def adjust(account, signed_amount, *, allow_negative: bool, reference_type, reference_id,
           actor=None, credit_type="DIRECT", source_reference=None, expires_at=None,
           billable_type=None, prefer_source_reference=None, metadata=None) -> LedgerEntry:
    """THE only writer of balance, buckets and entries. Never commits."""
```

**Rules.**
- **`allow_negative` is keyword-only with no default.** The affordability decision belongs to the
  caller and must be visible at the call site.
- **A zero amount is rejected.** Amounts are quantized first.
- **It never commits.** The caller owns the transaction; bulk callers wrap each row in a savepoint
  (`transaction.atomic()` nested) so one bad row cannot poison a batch.
- **It locks the ledger account** (`select_for_update()`) before reading buckets.
- **Debit is FIFO by policy:** eligible buckets are `ACTIVE`, unexpired, `remaining > 0`, and not
  excluding the `billable_type`; ordered by `fifo_class`, then `expires_at ASC NULLS LAST`, then
  `created_at`. `prefer_source_reference` pulls a named bucket to the front (refunds, below).
  Emptied buckets become `EXHAUSTED`. **One entry per call**, with the per-bucket breakdown in
  `metadata.credits_consumed`.
- **Non-refundable credit into an overdrawn account becomes a `HELD` bucket** that does not raise the
  balance; it is released once the balance is back at or above zero. Otherwise a promotional grant
  silently pays off debt.
- **Refundable credit into an overdrawn account performs debt recovery:** one entry for the recovered
  debt, one for the remainder. If the caller supplies an explicit audit id, it goes on **exactly one**
  of them (a real incident: the id on both rows raised a primary-key violation and rolled back the
  admin's credit).
- **A gateway refund reverses the original top-up's own bucket** — `prefer_source_reference =
  <gateway payment id>`, `allow_negative=True` (the gateway is authoritative; the money has left).
- **Expiry** runs a savepoint per bucket, clamps the deduction to `max(balance, 0)`, expires `HELD`
  buckets without a deduction, and **skips buckets under an open hold** (§ 2.5).
- **Never load the journal through a reverse relation.** A real incident: a default-lazy relationship
  loaded about 40,000 entries every time an account was read. Serializers page entries explicitly.
- **Low-balance warnings fire when the balance is negative too.** A real incident: the warning
  required `balance >= 0`, so overdrawn accounts went silent and drifted deep negative with no signal.

**Enforced by.**
- **`djx_billing/tests/test_ledger_single_entrypoint.py` — the source guard.** Regexes over the whole
  repository (core, project, every plugin) excluding `ledger/services.py`, with comments and strings
  stripped so the prose explaining the ban does not trip it:
  - `LedgerEntry(`, `LedgerEntry.objects.(create|bulk_create|update)`, `CreditBucket.objects.(create|update)`
  - `\.balance\s*[-+*/]?=`, `update\([^)]*balance\s*=`, `F\(["']balance["']\)`
  
  The allow-list is keyed **per offending expression**, not per file, and is **two-way**: every entry
  must still match something, so a fixed site cannot leave a stale exemption behind. The wholesale
  ledger (§ 2.23) has its own entrypoint and its own guard. Positive control: a fixture file with
  `account.balance -= x` makes the test fail.
- `test_credit_class_fifo.py`, `test_debt_recovery.py`, `test_refund_targets_source_bucket.py`,
  `test_expiry_clamps_to_balance.py`, `test_unknown_credit_type_is_most_restrictive.py`.
- **The nightly drift reconciler** (§ 2.21): `max(balance, 0) − Σ remaining(ACTIVE, unexpired)` in
  both directions, tolerance one minor unit. **Read-only** — it reports; repair is a reviewed script.

### 2.5 Holds and reservations

A **hold** reserves money for an open document (a pre-invoice, § 2.16) so it cannot be spent twice.

- `hold(account, amount, reference)` = FIFO debit with `entry_type=HOLD`, `allow_negative=False`.
  The balance drops at hold time.
- `release_hold(reference)` restores buckets one by one, **idempotent through `released`/`consumed`
  flags in the hold entry's metadata**. A bucket that expired while held is marked `EXPIRED` and **not
  resurrected**.
- `consume_hold(reference)` writes the terminal `DEBIT` (the balance was already taken).
- Expiry defers buckets under an open hold.
- **Settling a held document from balance** releases its holds, re-quotes, then either pays or
  re-holds **the same** document — it never creates a second one.

**Enforced by.** `test_hold_release_is_idempotent.py`, `test_expired_bucket_not_resurrected.py`, and
the partial unique index "one OPEN pre-invoice per subject" (§ 2.16).

### 2.6 The tax point — decided once

A top-up can be taxed as a **sale of credits** (tax at capture; the consumption document is then a
non-tax **statement**) or treated as an **advance** (tax at consumption on a tax invoice). **Never
both.** A real incident: tax was declared on the top-up and again on the month-end consumption
document — double declaration, and a correction exercise across every affected customer.

- `billing.tax_point` = `TOP_UP` | `CONSUMPTION`. The installed jurisdiction adapter (§ 2.15) declares
  which it permits; a system check refuses a combination the adapter forbids.
- **`TOP_UP`:** the gateway charges `credits × (1 + rate)`; **only the pre-tax credits are credited**;
  the split (`credits_amount`, `tax_amount`, `tax_rate`, `tax_context` snapshot) is **frozen on the
  payment intent at order time** so later edits to the customer's tax state cannot change the tax at
  capture. At capture a **born-PAID tax invoice** is minted, idempotent through
  `source_payment_intent` + a partial unique index. Month-end becomes a `STATEMENT` on its own number
  series.
- **Only `in_tax_base` credits count as consideration.** Promotional credit consumed is outside the
  base; the document shows `gross`, `promo_applied`, `taxable = gross − promo`, with a `CHECK` on the
  identity.

**Enforced by.** `test_tax_point_never_double.py` — with `TOP_UP`, every statement carries zero tax
and every captured top-up has exactly one tax invoice; with `CONSUMPTION`, no top-up carries tax.

### 2.7 Metering — forward-only cursor collectors

**What.** A **meter** records that a billable thing is running at a stamped rate; a **collector**
periodically converts elapsed time into money.

**Data model (greenfield).**

```
billing_meter        id, billable_type FK, subject_type, subject_id, billing_account FK,
                     rate_stamp DECIMAL(.,6), rate_currency, opened_at, cursor_at, closed_at NULL,
                     status (OPEN|CLOSED), close_reason
billing_usage_slice  id, meter FK, period_start, period_end, quantity DECIMAL(.,4), amount,
                     settlement_mode (PREPAID_LEDGER|POSTPAID_ACCRUAL), status (UNBILLED|BILLED|SETTLED),
                     document_line FK NULL, ledger_entry_ids JSONB
```

Partial indexes on `status='OPEN'` and `status='UNBILLED'`; unique `(meter, period_start,
settlement_mode)`; partial unique **one OPEN meter per `(billable_type, subject_type, subject_id)`**.

**The collector algorithm** — one per billable type, identical shape:

1. **Table-wide try-lock:** `pg_try_advisory_xact_lock(<stable key for this collector>)`. If another
   run holds it, return immediately **without persisting a cycle row** (no phantom zero cycles).
   Keys are derived by a documented stable hash of the collector's registry key; a test asserts
   every registered key is distinct.
2. For each OPEN meter, in its own savepoint:
   1. **Fail closed on terminal subject state.** `billable_type.is_billable(subject)` false (deleted,
      shelved, deleting, provisioning-not-confirmed) ⇒ close the meter, bill nothing. A real incident:
      a machine that could not start was charged for 19 hours because the meter opened on the
      provider's "accepted" rather than on "running".
   2. **Fail closed on a governing subscription** (§ 2.20) ⇒ close at zero.
   3. **Per-row lock, then re-read the committed cursor** — `select_for_update()` on the meter (or
      `pg_advisory_xact_lock(hash('meter:<id>'))` where row locks are unavailable). **The re-read is
      what prevents the double debit**: a parallel worker holding a stale in-memory cursor bills the
      same interval again.
   4. `elapsed = now − cursor_at`. **Below the minimum increment** (`billing.collector.min_increment_seconds`,
      default 60) ⇒ skip; this stops scheduler restarts producing micro-charges.
   5. `amount = quantize(rate_stamp × elapsed_hours)`; skip if `≤ 0`.
   6. Branch on the account's billing model:
      - **`POSTPAID`:** add quantity and amount to the current period's slice.
      - **`PREPAID`:** `ledger.adjust(−amount, allow_negative=True, billable_type=…)` and record the
        entry id on the slice (`settlement_mode=PREPAID_LEDGER`, `status=SETTLED`).
   7. Advance `cursor_at = now`.
   8. Prepaid side effects: stamp `negative_since` on the first negative crossing; low-balance
      warning deduped per day; hand suspension to the dunning evaluator (§ 2.18) — never suspend from
      the collector.
3. Cycle telemetry (`billing_cycle` row: counts, sum, duration, errors) is **non-fatal** — a
   telemetry failure never rolls back billing.

**Rules.**
- **Transaction-scoped advisory locks only.** With PgBouncer in transaction pooling mode a
  session-scoped lock attaches to whichever server connection happened to serve the query and leaks
  to the next client ([`OPERATIONS.md`](OPERATIONS.md)).
- **Collectors run on a dedicated `billing` queue with staggered schedules** (minute offsets across
  the hour, one per billable type), so a slow collector never delays login emails and collectors
  never contend with each other.
- **Closing a meter is `close_meter(meter, at, *, force_zero=False)` — one more forward step:**
  `remaining = rate × (at − cursor_at)`, add it, set `cursor_at = at`, `closed_at = at`. A second close
  adds zero. **Never recompute `rate × (end − start)`.** A real incident: eight closers used three
  formulas; the lifetime ones threw away postpaid accrual (wrong once the rate had been re-stamped)
  and stamped already-paid prepaid hours as cost, which became real money when the account later
  switched to postpaid.
- **The prepaid tail on close** (the last partial interval) is policy: `billing.prepaid_close_tail`
  = `RECORD` (default — recorded on the slice, not debited; always under-charges, never over-charges)
  | `COLLECT` (debited through the ledger).
- **Finalize before invoicing:** `finalize_account_metering(account, at)` repairs closed-but-OPEN
  rows, advances every accruing postpaid meter to `at` with the same forward step, and **flushes
  without committing** so the invoice sees current totals inside its own transaction.

**Enforced by.**
- `test_collector_parallel_idempotency.py` — two workers run the same collector over the same meters
  concurrently (real Postgres, two connections); the second bills nothing. Asserts the per-row lock
  and the committed re-read are present.
- **`test_no_lifetime_recompute.py` — source guard** over the whole repository for
  `rate … (end|closed_at|now) − (start|opened_at)` in both operand orders, including wrapped forms,
  plus `test_every_closer_routes_through_close_meter.py` (AST: any assignment to a meter's
  `closed_at` outside `metering/close.py` fails). **The allow-list may not exempt "other meter
  tables"** — a real residue: the guard excluded three secondary meter tables "as out of scope", and
  the exact bug survived on them.
- `test_close_is_idempotent.py`, `test_terminal_subject_closes_meter.py`,
  `test_governing_subscription_zero_cost.py`.

### 2.8 Metered ≠ billed — the billable-type registry

**What.** A thing is billed only when **all** of these exist: a rate resolver, a collector, a
document line builder, an unbilled aggregator and a tax code. A real incident: a resource type had
meters, but no collector — so it was free, for months, and nothing noticed because metering "worked".

**Extension point `billing.billable_types`:**

```python
BillableType(
    key="compute.instance", label="Instances",
    rate_resolver=resolve_instance_rate,     # (subject, at) -> (rate, currency) | raises NoTariff
    collector_schedule="2 * * * *",
    line_builder=build_instance_lines,       # (slices) -> [DocumentLine]
    unbilled_aggregator=unbilled_instances,  # (account, at) -> Decimal
    tax_code="standard_service",             # resolved by every installed jurisdiction
    is_billable=instance_is_billable,        # fail-closed terminal-state check
    subject_label=instance_label,
)
```

The contributing plugin (`compute`) registers this without importing billing (§ 1). The seeder writes
`billing_billable_type(key, label)` rows so meters hold a **real foreign key** to the type — a meter
cannot reference a type the code does not declare.

**Enforced by.** **`test_billable_type_completeness.py`** — iterates the registry and fails if any
hook is missing; asserts a scheduled job exists for every type; asserts every `tax_code` resolves in
every installed jurisdiction adapter; asserts every `billing_billable_type` row has a live
registration. It derives its universe from the registry and **fails, not skips, when the registry is
empty** (a completeness test over nothing proves nothing).

### 2.9 Rated slices, not cumulative rows

If meter rows are lifetime-cumulative, every invoice must compute deltas against a per-resource
"already invoiced" pool: consume the pool once across a resource's rows, remove settled rows from it,
cap closed rows to the period, add catch-up lines, and regenerate strictly in chronological order.
Each of those steps exists because its absence caused an under- or over-bill.

**Greenfield recommendation: period-bounded rated slices** — one `billing_usage_slice` per meter per
billing period (§ 2.7). An invoice sums `UNBILLED` slices in its period and marks them `BILLED`.
There is no delta arithmetic, no pool, and no ordering constraint. **Choose this unless a product
genuinely needs lifetime-cumulative rows**, and if it does, write the ordering rule into its ADR.

### 2.10 Rating, re-rating and the discount engine

- **Tariffs** hold rates at rate precision, per billable type, optionally per region/tier, with a
  `discountable` flag.
- **The rate is stamped onto the meter when it opens.** Price changes never touch open meters.
- **Re-rate is forward-only:** close at the old rate at instant T, open a new meter at the new rate
  from T. It **fails closed when no tariff resolves** — no meter opens at zero by accident.
- **Zero-rate meters are invisible** (the cursor advances but nothing is charged). The zero-rate sweep
  re-prices them **forward-only**, never by re-stamping the existing row — re-stamping would bill the
  whole lifetime, because the cursor of a zero-rate meter may never have moved.
- **The discount engine is a pure function** `apply(base_lines, context) -> [Adjustment]`, ordered
  **group → commitment → coupon → margin-cap clamp**, with **largest-remainder allocation** of fixed
  discounts across lines (so the parts sum exactly to the discount). Lines whose rate was already
  stamped net of a discount are marked `already_net` and skipped — a real incident discounted a group
  rate twice, once in the stamp and once at the header.
- **Adjustments are persisted** (`billing_adjustment`: kind, amount, rule reference, and **one of**
  `subscription_line` / `document_line` / `usage_slice` FKs with a `CHECK` that exactly one is set —
  not a generic FK) so every discount on every line is explainable later.
- **Coupons:** kind `WALLET_CREDIT` | `ORDER_DISCOUNT` with an XOR `CHECK` on the amount columns;
  redemption locks the coupon row; a wallet-credit coupon creates a `PROMO` bucket with
  `source_reference = code`, so the bucket replay index **is** the one-redemption-per-account rule.
  Estimates apply a code only after a successful, rate-limited validation left a short-lived marker —
  **failing closed** — so the estimate endpoint is not a coupon-enumeration oracle.

### 2.11 Documents — invoices and statements

**Data model.** `billing_document`:

| Group | Columns |
|---|---|
| Identity | `public_id` (UUID, the URL id — [`DATA_MODEL.md`](DATA_MODEL.md) D2), `number` (unique, § numbering), `document_kind` (`INVOICE` \| `STATEMENT`), `series` |
| Subject | `billing_account` FK, `period_start`, `period_end` |
| State | `status` (`DRAFT` \| `PENDING` \| `PARTIALLY_PAID` \| `PAID` \| `OVERDUE` \| `CANCELLED`), `due_at`, dunning stage (§ 2.18) |
| Money | `subtotal`, `discount_amount`, `promo_applied`, `taxable_amount`, `tax_breakdown` JSONB + `total_tax`, `withholding_amount`, `total_amount`, `amount_paid`, `amount_due`, `currency` |
| **Frozen snapshots** | `customer_snapshot` JSONB (legal name, address, tax id), `supplier_snapshot`, `tax_context_snapshot` (mode, reason, registration reference, jurisdiction adapter + version) |
| Sync | `external_ref` NULL, `external_payment_ref` NULL (§ 2.22) |

`billing_document_line`: `quantity (.,4)`, `unit_price (.,6)`, `amount`, `tax_code`, `tax_rate`,
`period_start`, `period_end`, `billable_type`, `source` references.

**DB constraints:** `total_amount >= 0`, `amount_paid >= 0`, `amount_due >= 0`,
`0 <= discount_amount <= subtotal`, `taxable_amount = subtotal − discount_amount − promo_applied`.
**Slot uniqueness:** partial unique `(billing_account, period_start, period_end, document_kind) WHERE
status <> 'CANCELLED'`.

**Generation** — `generate_period_document(account, period, *, dry_run=False)`:
1. Resolve the account; refuse if `billing_enabled` is false (with a named reason).
2. **`pg_advisory_xact_lock(hash('doc:<account>:<period>'))`**, then check the slot. A real
   incident: concurrent generators each created an invoice for the same slot.
3. Finalize metering (§ 2.7), build lines from each billable type's line builder.
4. Apply the discount engine (§ 2.10).
5. Compute tax through the tax context (§ 2.15) — required, never defaulted.
6. Set settlement fields by billing model: **prepaid** ⇒ a born-PAID receipt/statement,
   `amount_due = 0`, never collectible, never aged, never dunned; **postpaid** ⇒ `PENDING`, collectible.
7. Currency from the account.
8. **Mint the number** from the right series ([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) —
   document number sequences; separate series so a non-tax statement never consumes a tax-invoice
   number; the cold-start trap — `FOR UPDATE` on an empty result locks nothing — is the primitive's
   problem, not billing's).
9. Due date from the override hierarchy (§ 2.19).
10. Persist; mark slices `BILLED`.
11. Commit, **then** emit the event through the outbox; notify (not for prepaid receipts).

`dry_run=True` builds everything, persists nothing, **mints no number**, and returns the document for
a preview screen.

**Rules.**
- **One owner per slot.** A real incident: a generic monthly job ran an hour before the postpaid job
  and took the slot, so auto-pay never ran. Each account's slot is generated by exactly one scheduled
  job selected by billing model.
- **Snapshots are frozen at generation.** Later edits to the customer never relabel history.
- **Cancel** reverts that document's slices from `BILLED` to `UNBILLED` **by foreign key**, never by
  period guesswork. **Supersede** of a PAID document requires credit-note coverage (§ 2.17) — credit
  notes never change a document's status.
- **Void is a conditional UPDATE**, not a locked read:
  `UPDATE … SET status='CANCELLED' WHERE id=%s AND status IN (…) AND amount_paid = 0` and check the
  row count. Not every payment path takes the same lock, so a predicate is the only safe guard.
- **Key every lookup on `document.billing_account`**, never on "the user's primary account". A real
  incident debited the wrong tenant's balance this way.

**Enforced by.** `test_document_slot_unique.py` (concurrent generation, one survives),
`test_dry_run_mints_nothing.py`, `test_snapshot_frozen.py`, `test_void_conditional_update.py`,
`test_cancel_reverts_by_fk.py`, and the money `CHECK`s themselves (a test inserts a violating row
through the ORM and expects `IntegrityError`).

### 2.12 Settlement — one entrypoint, one lock order

```python
def settle(document, *, method: str, reference: str, amount=None, actor, source="customer") -> Settlement:
```

**Rules.**
- **Lock the document first** (`select_for_update()`), then the ledger account. **Every** path —
  customer pay, auto-pay, credit-note application, offline payment, admin — uses this order. A real
  incident: auto-pay locked balance-then-invoice while everything else locked invoice-then-balance;
  the two deadlocked, and two overlapping balance payments both debited.
- **Reject** `PAID`, `CANCELLED`, `DRAFT`.
- **Explicit method allow-list**, server-side. Customer endpoints accept only internal-balance methods
  (`balance`, `balance_partial`); gateway methods are accepted only from the verified gateway paths
  (§ 2.13). A real incident: an unknown `payment_method` fell through to an unconditional
  full-settlement block — a client-reachable "mark anything PAID".
- **`balance_partial` fails closed** on a missing or empty account. It once fell through to full
  settlement with zero cash.
- **`amount_paid += collected`** — record the cash actually taken, never overwrite with
  `total_amount` (withholding makes these differ).
- **Currency guard** on every path (§ 2.3).
- **Idempotency first:** the same `reference` on an already-PAID document returns success *before*
  the method check, so a retried legitimate payment is not turned into an error.
- **After a document becomes PAID, run the `billing.on_document_paid` hooks** (an extension point —
  e.g. release payment-gated resources). Because every PAID writer goes through `settle()`, the hook
  cannot be skipped; a reconciler sweeps "PAID but still gated" anyway (§ 2.21). A real incident: one
  of four PAID writers released gated resources; the other three left customers blocked after paying.

**Enforced by.** `test_settlement_integrity.py` — unknown method raises; customer endpoint returns
400 for a gateway method; the idempotent retry still returns 200; empty account with
`balance_partial` raises; withholding documents record actual cash; cross-currency raises. A source
guard asserts no code outside `settlement.py` assigns `status = PAID` or `amount_paid`.

### 2.13 Payments — intent row, verify, webhooks, refunds

**Gateway adapters** register at extension point `billing.gateways`:

```python
class GatewayAdapter(Protocol):
    key: str; supported_currencies: frozenset[str]
    def create_intent(self, conn, intent) -> RedirectOrClientSecret: ...
    def verify_client_return(self, conn, payload) -> VerifiedPayment: ...   # signature first
    def parse_webhook(self, conn, raw_body: bytes, headers) -> GatewayEvent: ...
    def fetch_payment(self, conn, provider_payment_id) -> VerifiedPayment: ...
    def refund(self, conn, intent, amount, idempotency_key) -> RefundResult: ...
    def test_connection(self, conn) -> ProbeResult: ...
```

**Data model.** `billing_payment_intent`: `public_id`, `provider`, `connection_ref`, `order_ref`,
`provider_payment_id` (unique, nullable until capture), `amount`, `currency`, `purpose`
(`TOP_UP` | `DOCUMENT` | `PRE_INVOICE`, registry-extensible), `subject_ref` (the document or account —
**set server-side**), `status` (`CREATED` | `AUTHORIZED` | `CAPTURED` | `FAILED` | `REFUNDED` |
`PARTIALLY_REFUNDED`), **`credited_at`** (the idempotency marker), `ledger_entry` FK,
`webhook_event_id`, frozen tax split (§ 2.6). **Partial unique `(provider, order_ref)`** —
`connection_ref` deliberately *not* in the key, because NULLs are distinct in a unique index and the
key would stop being unique. `billing_payment_refund`: unique `(intent, provider_refund_id)`.

**Rules.**
- **The intent row is created server-side before redirect.** Nothing about amount, currency, purpose
  or subject is ever read back from the gateway's customer-controlled notes/metadata. A real incident:
  the document id in gateway notes was customer-editable — the handler must assert the document's
  account equals the intent's account.
- **Client return (`/verify`):** **signature first.** Unknown order, bad signature and a disabled
  tenant gateway all return **the identical 400** — no order-existence oracle. Then ownership, then the
  `credited_at` check, then **re-fetch from the gateway** and require captured, then **amount and
  currency must equal the intent row**, then route by purpose.
- **Webhook:** HMAC over the **raw body** with a constant-time compare; **ingress/intent connection
  match in both directions** (the ingress's gateway connection must equal the intent's — a real
  incident: one tenant forged a validly signed webhook for another tenant's order using their own
  gateway secret); `select_for_update()` on the intent; replay check on `webhook_event_id`;
  `credited_at` check; amount and currency; a mismatch sets the intent `FAILED` **with no credit**.
- **Verify and webhook race** — both may arrive; both re-lock the intent and re-check `credited_at`
  inside the lock. Credit is **idempotent on the intent row**, not on a cache.
- **Duplicate capture** (a different reference for an already-paid document) sets the new intent
  `FAILED`, emits `billing.duplicate_payment` **inside the same transaction** (outbox), and surfaces
  to an operator for refund. It is never silently marked credited.
- **Return 2xx only once the event is durably recorded** (processed, or recorded as rejected).
  Unexpected errors return 5xx so the gateway redelivers; idempotency makes redelivery safe.
- **Refunds are idempotent by a unique child row** — insert with conflict-ignore on
  `(intent, provider_refund_id)`. A real incident: idempotency keyed on "the last refund id" field
  over-debited when retries interleaved.
- **DB markers, never Redis, for money.** A cache-based dedupe fails open when the cache is down; it
  is acceptable for non-money webhooks only ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).
- **The return page never marks anything paid.** It polls the intent's status.

**Enforced by.** `test_verify_signature_first_identical_errors.py`, `test_webhook_ingress_binding.py`,
`test_amount_currency_mismatch_no_credit.py`, `test_verify_webhook_race.py` (two threads),
`test_duplicate_capture_failed_and_event.py`, `test_refund_idempotent_interleaved.py`.

### 2.14 Per-tenant gateway credentials

When tenants (resellers, marketplace sellers) collect with their own gateway accounts:

- `billing_gateway_connection`: `scope` (platform | tenant), `tenant` FK NULL, `provider`, key id,
  **encrypted secret and webhook secret** (through the credential store in
  [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)), an opaque **`routing_token`** for the
  per-tenant webhook URL (never an enumerable tenant code), `verified_at` (set **only** by a passing
  `test_connection`, and required for enablement). Partial unique: one active row per
  `(tenant, provider)`. **A tenant row can never become the platform default** — separate scope,
  checked by constraint.
- **The resolver fails closed:** tenant scope uses **only** that tenant's verified connection;
  otherwise `PaymentConfigError` (409). A decryption error propagates. **There is never a platform
  fallback** — silently collecting a tenant's customer's money into the platform account is worse than
  refusing.
- **The resolved `connection_ref` is stamped on the intent**, so refunds and reconciliation go back
  to the account that captured it.
- **Per-tenant ingress:** `POST /api/billing/webhooks/<provider>/t/<routing_token>/`, and the ingress
  binding rule (§ 2.13) applies.

### 2.15 Tax — a pluggable jurisdiction that fails closed

**What.** A `TaxContext` resolver plus a document tax API that *requires* the context. VAT, GST and
sales-tax regimes are **jurisdiction adapters**, not the default.

**Extension point `billing.tax_jurisdictions`:**

```python
class TaxJurisdiction(Protocol):
    key: str; version: str
    permitted_tax_points: frozenset[str]
    def resolve_context(self, account, supplier, on_date) -> TaxContext: ...
    def compute(self, lines, ctx: TaxContext) -> TaxBreakdown: ...
    def estimate(self, amount, hint) -> TaxBreakdown: ...      # display only; never on a document
    def document_texts(self, ctx) -> list[str]: ...            # mandatory legends, verbatim constants
```

`TaxContext(mode, components, zero_rated_reason, registration_ref, place_of_supply)`.

**Rules.**
- **`compute()` requires a context; there is no `is_export=False` parameter to forget.** A real
  incident: a boolean flag on a legal document's tax call was forgotten on one path and produced wrong
  documents. The estimate function is separate and is never called by document code (a source guard
  asserts `documents/` never imports `estimate`).
- **Resolution fails closed to the higher-tax mode.** A zero-rated or exempt mode requires **every**
  piece of evidence — the customer's attestation, valid tax ids on both sides, and an **active dated
  registration whose validity covers the document date and whose supplier id equals the current
  supplier id**. Any gap resolves to the taxed mode, never the other way.
- **A blank or unknown country is domestic.** There is never an accidental export.
- **Registrations are a dated registry**: `billing_tax_registration(supplier_tax_id, kind,
  valid_from, valid_to, reference)` with a uniqueness constraint per `(supplier_tax_id, kind,
  valid_from)`, so a back-dated document resolves against the registration of its own date.
- **Supplier identity is read from the database at calculation time**, never from an import-time
  singleton that goes stale after an admin edit.
- **The context is snapshotted onto the document** (§ 2.11) with the adapter key and version, and a
  coherence validator asserts lines and header agree.
- **Withholding tax** (a customer deducting tax at source) is a document field, a settlement
  consideration (`amount_paid` records cash, § 2.12) and a matching input (§ 2.18) — adapters declare
  whether it applies.
- **No jurisdiction installed ⇒ no tax documents.** Generation refuses with a named reason rather
  than issuing a zero-tax invoice.

**Enforced by.** `test_tax_context_required.py`, `test_exemption_fails_closed.py` (remove each
evidence item in turn; every removal yields the taxed mode), `test_blank_country_domestic.py`,
`test_registration_dated.py`.

### 2.16 Pre-invoices (pro-forma) — holds, deferred action, late payment

A **pre-invoice** asks a prepaid customer to cover a shortfall before something happens (a new
subscription, an upgrade, a top-up).

- `billing_pre_invoice`: `status` (`OPEN` | `PAID` | `EXPIRED` | `CANCELLED`), `kind` (registry:
  `NEW`, `RENEWAL`, `UPGRADE`, `CYCLE_CHANGE`, `TOP_UP`), line items, money split (`gross`, `promo`,
  `taxable`, `tax`, `total`, `balance_applied`, `amount_payable`), **`deferred_action`** (a registered
  action key + arguments to run on payment), `converted_document` FK, own number series.
- **Constraints:** `CHECK (amount_payable > 0)`, `CHECK (taxable = gross − promo)`, **partial unique
  one OPEN pre-invoice per subject** and one OPEN top-up per account.
- **`mark_paid()` is a pure DB mutation** — no commit, no task dispatch. It returns post-commit
  dispatches that the caller runs after its outer commit.
- It **re-locks** the row. **If it is no longer OPEN** (the expiry sweep won, or a duplicate webhook),
  the money is **credited to the account as refundable credit and an operator is notified — never
  dropped, and never converted into an invoice for a closed document.**
- Gateway money writes a **CREDIT + DEBIT pair** in the ledger so the path is auditable.
- The hourly expiry sweep releases holds idempotently.

### 2.17 Credit notes and outbound money — write-ahead

- `billing_credit_note`: reason (`REFUND` | `ADJUSTMENT` | `COMPENSATION` | `BALANCE_REFUND`), status
  (`DRAFT` | `PENDING_APPROVAL` | `OPEN` | `PARTIALLY_CONSUMED` | `APPLIED` | `REFUNDED` | `VOID` |
  `SYNC_FAILED`), tax snapshots, `applied_amount`, `refunded_amount`; child tables for lines,
  **applications** (many-to-many with documents) and **refunds**.
- **The write-ahead refund lifecycle** — the pattern for *every* outbound money move:
  1. `validate_refund` locks the note and checks: gateway modes need an issued note; **no PENDING
     refund exists** (the in-flight guard); the amount fits the unapplied balance **and** the
     refundable share actually collected.
  2. `begin_refund` inserts a PENDING refund row and reserves `refunded_amount`. **The caller commits
     before calling the gateway.**
  3. The gateway call.
  4. `complete_refund` or `fail_refund` (releases the reservation).
  5. **`record_refund_ambiguous`** on timeout: **leave the row PENDING and keep the reservation.** A
     retry is blocked until a reconciler (§ 2.21) asks the gateway what happened. An ambiguous outcome
     is "maybe happened", never "didn't happen".
- **Credit notes never change a document's status.** Correcting a paid document is a supersede.
- A credit note over the approval threshold is a proposal (§ 3), not a direct write.

### 2.18 Collections and dunning

**Postpaid period close**, per account: generate the document; net successful mid-period tranches
(locked; PENDING tranches surfaced, never applied; excess recorded as credit for an operator);
then, if not PAID and auto-charge is on, balance first, then the saved payment method **scoped to the
document's account** (never a user-level fallback), then gateways.

> ⚠️ **Auto-charge must charge `amount_due`, never `total_amount`.** A partially paid document
> (tranches applied, a prior partial payment) charged in full collects the difference twice. This was
> a real defect found in a mature codebase whose own comment said the opposite. A test charges a
> partially paid document and asserts the gateway amount.

**Mid-period tranches** (optional, default off): a write-ahead ledger with a unique
`idempotency_key = "<account>:<period>:tranche:<n>"`; a PENDING tranche blocks the next; one tranche
per account per sweep; the per-charge ceiling is **configuration** (payment methods such as mandates
carry regulatory caps that differ per market).

**Bank-transfer matching** (virtual accounts or statement import): a credited transfer creates a row
unique on the bank's reference; the matcher tries exact `amount_due`, then `amount_due −
withholding`, then computed withholding; it **auto-matches only when exactly one document matches**;
partially paid documents are never auto-matched; a pre-invoice reference in the payer reference is
tried first; everything else goes to the findings queue
([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md)).

**Offline payments** are an append-only ledger plus void. External sync uses a **`SYNCING` claim
state** so a reconciler and a manual re-sync cannot double-post; attempts are capped; withholding is
carried by the closing payment only.

**Dunning — pure evaluator → persisted stage → separate executor.**
- **One monotonic stage machine per document:** `NONE → REMINDER_SENT → DUE → OVERDUE → GRACE →
  SUSPENDED → CURE → TERMINATION_NOTICE_SENT → TERMINATED`. The only backwards move is a reset to
  `NONE` on payment.
- `evaluate(document, policy, now) -> DunningDecision(next_stage, message_key, actions)` is **pure**
  — no I/O, fully unit-testable.
- `advance()` persists the stage and is idempotent (same stage ⇒ no-op). **If enqueueing the message
  fails, the transition is deferred** to the next run — a customer is never suspended for a notice
  they were never sent.
- **The dunning module never suspends anything itself.** An executor per subject type (registered at
  `billing.suspension_executors`) acts on `actions`, idempotently (keyed on the last suspend/resume
  record), collecting errors rather than raising on a worker hot path.
- **Destructive steps default off**: `billing.suspension.enabled=false`,
  `billing.termination.enabled=false`, `billing.termination.dry_run=true`. Every attempt writes a row:
  `DRY_RUN` | `EXECUTED` | `FAILED` | `SKIPPED_COMMITTED` | `SKIPPED_EXEMPT`.
- **Termination deletes the provider resource before cancelling the subscription** (otherwise a
  cancelled subscription leaves a running, unbilled resource), forfeits without refund per policy,
  runs in a savepoint, and **defers settlement to the regular period document** rather than
  generating one early (which would pre-empt the slot, § 2.11).
- **Exemptions resolve most-specific-first with expiry:** subscription → user → account → group
  (`DO_NOT_SUSPEND` | `EXTEND_UNTIL(date)`), re-checked inside the executor, via the policy-override
  pattern in [`CONFIGURATION.md`](CONFIGURATION.md).
- **Prepaid wallet-triggered suspension** requires *all* of: balance below a configured threshold,
  the flag on, and a tolerance window elapsed (amount or hours since `negative_since`).
- Dunning policy per group or account: touches, cadence, quiet hours, channel caps, with a
  **single-scope `CHECK`** (exactly one of group/account set).

### 2.19 Gates — cost, credit limit, quota, budget

**`assert_can_incur_cost(account, billable_type, estimate)`** — one service, called from HTTP and from
workers, raising a **domain exception** (`BillableCreateBlocked(code, reason)`), never an HTTP
exception, so a worker can consume it.

- Order: account lifecycle (operational, onboarding complete) → product guards registered at
  `billing.create_guards` → money gate.
- **Postpaid:** exposure = unpaid issued documents + unbilled accrual + `estimate`, against the credit
  limit resolved **override → approved credit approval → group** (one shared, pure predicate that
  never raises — a real incident had approval validity checked four different ways).
- **Prepaid:** the ledger account must exist (402) and cover `billing.gate.prepaid_estimate_hours`
  (default 24) of the estimate, or be above zero when there is no estimate.
- **An evaluator or infrastructure error fails closed** (503), never open.
- `account is None` is a loud 500 — it is a wiring bug.
- **Every billable create path calls it.** A real incident: only one resource type's create was
  gated; five others bypassed it. The billable-type registration declares its create service, and a
  test calls each through the gate with an empty account and expects refusal.

**Quotas:** `billing_quota_definition(key, unit, default, trial_default, paid_default)`, overrides
(user → account → group, each optionally narrowed by scope dimensions such as region), and
`billing_quota_enforcement_log` recording every decision. Count **live** resources **in the same scope
as the limit**. **Check-then-create races** — two concurrent creates both pass a count — so enforcement
takes a transaction-scoped advisory lock on `(account, quota_key)` (or reserves against a counter row
under `select_for_update()`) for the count-and-create.

**Budgets:** thresholds with action `ALERT` | `BLOCK`, evaluated hourly, reading **the same spend
figure the dashboard shows** (one spend service), feeding the gate.

### 2.20 Subscriptions and commitments beside metering

- `billing_subscription`: `CHECK amount_paid >= 0`, `CHECK discount >= 0`, `CHECK ends_at > starts_at`,
  **partial unique one governing subscription per `(subject_type, subject_id)`**, paid split
  (`paid_direct`, `paid_promo`, `paid_tax`), `locked_until`, `pre_invoice` FK.
- **`GOVERNING_STATUSES = (ACTIVE, SUSPENDED, PENDING_RENEWAL)`** is **one named constant** and the
  single source of "a subscription governs billing for this subject". A real incident: treating only
  `ACTIVE` as governing let the hourly meter bill alongside a suspended or renewing subscription —
  double billing.
- **Settlement order:** promotional credit first (outside the tax base), then refundable credit, then
  a born-PAID document, or a pre-invoice for the shortfall. Never commits.
- **Atomicity:** the outer operation (e.g. change billing cycle) owns the commit; inner calls take a
  nested savepoint, so a rollback is bounded to that operation and never touches the caller's session.

### 2.21 Reconcilers — every transient state has one

The rule from [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md) applied to money:

| Reconciler | Schedule | Does |
|---|---|---|
| `reconcile_ledger_drift` | daily | **Read-only** balance-vs-buckets drift report, both directions; repair by reviewed script |
| `expire_credits` | daily | Bucket expiry with clamp (§ 2.4) |
| `reconcile_meters` | hourly | Close meters on non-billable subjects; open missing meters (excluding governed subjects) |
| `reconcile_orphan_meters` | hourly | Close meters whose subject is gone — a fire-and-forget close is lost during a broker outage |
| `reconcile_zero_rate_meters` | daily | Forward-only re-price (§ 2.10) |
| `release_paid_but_gated` | 5 min | PAID document, resource still gated → run `on_document_paid` hooks |
| `reconcile_ambiguous_refunds` | 15 min | Ask the gateway about PENDING refunds older than N minutes |
| `reconcile_stuck_intents` | 15 min | `CREATED`/`AUTHORIZED` intents past TTL → re-fetch; capture found ⇒ credit via the normal path |
| `reconcile_born_paid_sync` | hourly | Born-PAID documents missing their external payment record (§ 2.22) |
| `reconcile_failed_syncs` | 30 min | Retry external sync with an attempt cap |
| `reconcile_bank_transfers` | 6 h | Unmatched transfers |
| `expire_pre_invoices` | hourly | Release holds on expired pre-invoices |

A reconciler **only reports or moves state forward through the same service entrypoints** — it never
writes around them.

### 2.22 Accounting-system sync — a downstream, idempotent projection

The external accounting system is a **projection** of local truth, never a source.

- An adapter per system (extension point `billing.accounting_adapters`); per-document tasks with
  retry and backoff.
- **Idempotent on the external id stored locally** (`external_ref`); early return if already synced,
  if the document is a `STATEMENT` (never synced), or if sync is disabled for that tenant.
- **Enqueue after commit, and only when the document is newly paid** — a real incident double-recorded
  payments when verify and webhook both enqueued.
- Raise a typed "not ready" error when the document is not yet visible (uncommitted race) so the task
  retries rather than failing permanently.
- **Sentinel values for "not applicable"** (e.g. born-PAID receipts that need no payment record), so a
  reconciler can tell "done" from "not needed" from "missing".
- **Consolidate lines** where the external system cannot carry local precision (one line at the
  taxable amount, credit notes net of header discount so the external note never exceeds the local).
- Sweepers catch every miss (§ 2.21).

### 2.23 Reseller wholesale ledger

For a reseller hierarchy (§ 10): a **separate** wholesale ledger (`kind=WHOLESALE`) at wholesale
rates, with its **own single entrypoint and its own source guard** — never a second set of exemptions
in the customer ledger's guard. Plus quota pools (allocated / distributed / reserved per quota and
scope) and monthly aggregation.

**Price resolution for a reseller's customer:** customer-specific override → reseller-wide override →
formula `platform × (1 − wholesale_discount) × (1 + tier_markup)`, all `Decimal`, clamped at zero,
markup capped by `billing.max_markup_percent`. ⚠️ **If the pricing context cannot be loaded, refuse
to quote** — a real implementation failed open to platform pricing with only a warning, quoting a
reseller's customers the wrong price.

### 2.24 Billing — permissions, jobs, frontend, configuration, traps

**Permissions** (`billing.<feature>.<action>`):

| Permission | Grants |
|---|---|
| `billing.accounts.view` / `.manage` | See / edit billing accounts, model, limits |
| `billing.ledger.view` | Balance, buckets, entries |
| `billing.ledger.adjust` | Manual credit/debit — **routed through approvals (§ 3) when installed** |
| `billing.documents.view` / `.generate` / `.void` / `.supersede` | Document lifecycle |
| `billing.payments.view` / `.refund` | Intents and refunds |
| `billing.gateways.manage` | Gateway connections (step-up re-auth required, [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 6.9) |
| `billing.tariffs.manage`, `billing.coupons.manage`, `billing.tax.manage` | Pricing and tax configuration |
| `billing.dunning.manage` / `.execute_destructive` | Policy / turning destructive steps on |
| `billing.quotas.manage`, `billing.reconcile.view` | Quotas; reconciler reports |
| `billing.self.pay`, `billing.self.view` | Customer self-service on their own account |

**Registries contributed:** permissions, navigation, api_routes, jobs (every collector and reconciler),
events (`billing.document.issued`, `billing.document.paid`, `billing.payment.captured`,
`billing.duplicate_payment`, `billing.refund.completed`, `billing.dunning.stage_changed`), health
(gateway credential liveness), search (documents by number), alert sources (drift, stuck intents),
approval handlers (ledger adjust, credit limit, coupon grant, tariff change). **Extension points
declared:** `billing.billable_types`, `billing.gateways`, `billing.tax_jurisdictions`,
`billing.accounting_adapters`, `billing.suspension_executors`, `billing.create_guards`,
`billing.on_document_paid`, `billing.pre_invoice_actions`.

**Frontend surfaces:** account overview (balance with bucket breakdown and expiry), ledger with
filters, documents list and detail rendered **from the snapshot**, a **dry-run preview** screen,
payment flow (redirect → return page that **polls** the intent), admin adjust form (money entered as
**strings**, parsed as decimals on the server — a JavaScript `number` is a float), gateway connection
screen with *Test connection* → verified, dunning timeline per document, reconciler reports, quota
usage bars, coupon management.

**Configuration keys** (settings registry, [`CONFIGURATION.md`](CONFIGURATION.md)):
`billing.enabled`, `billing.hours_per_month`, `billing.collector.min_increment_seconds`,
`billing.tax_point`, `billing.prepaid_close_tail`, `billing.low_balance_threshold`,
`billing.negative_tolerance_amount`, `billing.negative_tolerance_hours`, `billing.suspension.enabled`,
`billing.termination.enabled`, `billing.termination.dry_run`, `billing.gate.prepaid_estimate_hours`,
`billing.pre_invoice.expiry_hours`, `billing.discount_engine.enabled`, `billing.autocharge.enabled`,
`billing.tranches.enabled`, `billing.tranches.max_amount`, `billing.drift.tolerance_minor_units`,
`billing.accounting_sync.enabled`, `billing.max_markup_percent`, `billing.coupon.validation_ttl_seconds`.

**Traps, in one list.** Float money in a request schema · two period clocks · direct balance writes ·
refund consuming promo credit · expiry clawing back paid money · stale cursor double debit · meter
opened on "accepted" · lifetime recompute on close · guard exempting "other" meter tables · load-bearing
empty cost column · metered-but-never-billed type · two generators for one slot · `FOR UPDATE` on an
empty sequence · wrong-tenant account lookup · unknown method falling through to PAID · auto-pay
charging `total_amount` · verify/webhook race · cross-tenant forged webhook · Redis dedupe for money ·
timeout treated as failure · cross-currency 1:1 · tax on top-up *and* consumption · pricing failing
open · lock-order deadlock · only one of four PAID writers releasing gated resources.

---
## 3. Approvals / maker-checker — **Tier 3 · Module**

**Purpose.** Separation of duties: a person proposes a change to something sensitive (a credit
grant, a credit limit, a price, a role grant, a supplier's bank details, a large refund), a
*different* person approves it, and the system applies it. **Who needs it:** every ERP (purchase
approvals, vendor master changes), every product with money (billing adjustments), CRMs (discount
approvals), SaaS back offices (privilege changes). Two shapes live here: **change proposals** for
single mutations (§ 3.1) and **approval chains** for documents (§ 3.2).

### 3.1 Change proposals

**Data model.** `approvals_proposal`:

| Column | Notes |
|---|---|
| `public_id` | URL id |
| `kind` | Handler key, validated against the extension point; FK to a seeded `approvals_kind` catalog |
| `target_type`, `target_id`, `target_scope` | What is changed, and the tenant/scope it belongs to (snapshotted) |
| `payload` JSONB | The requested change, **JSON-normalised** by the handler |
| `before` JSONB | Snapshot of the fields the payload touches, taken at propose time |
| `amount`, `currency` | Nullable; the value used for threshold arithmetic |
| `status` | `DRAFT` \| `PENDING` \| `APPROVED` \| `APPLIED` \| `FAILED` \| `REJECTED` \| `WITHDRAWN` \| `EXPIRED` |
| `proposed_by`, `decided_by` NULL, `decided_at`, `decision_note` | `decided_by` NULL + `threshold_bypass` = system decided |
| `applied_at`, `apply_error` | `apply_error` is a sanitised message, never a stack trace |
| `threshold_bypass`, `break_glass` | Booleans, both audited |
| `expires_at` | Stale proposals cannot be approved against a changed world |

Indexes `(status, kind)` and `(proposed_by, created_at)`. **A database constraint carries the core
rule:** `CHECK (decided_by IS NULL OR decided_by <> proposed_by OR break_glass)`.

**Extension point `approvals.handlers`** — any plugin registers a kind without importing approvals:

```python
ApprovalHandler(
    kind="billing.ledger_adjust", label="Balance adjustment",
    propose_permission="billing.ledger.adjust", decide_permission="billing.ledger.approve",
    validate=validate_adjust_payload,      # raises ValidationError; returns normalised payload
    snapshot=snapshot_account,             # (target) -> dict of the fields payload touches
    amount_of=lambda p: (Decimal(p["amount"]).copy_abs(), p["currency"]),
    scope_of=account_scope,                # (target) -> tenant/scope key
    apply=apply_adjust,                    # (proposal, *, actor) -> None; raises to FAIL
    describe=describe_adjust,              # (before, payload) -> [DiffRow] for the inbox
    threshold_setting="billing.approvals.adjust_threshold",
)
```

**Service API and invariants** (`approvals/services.py`):

- **`propose(kind, target, payload, *, actor)`**
  - Handler validates and normalises; `before` is snapshotted.
  - **Auto-approval threshold** from the handler's setting — **default `0`, so nothing auto-approves
    until an owner deliberately raises it.**
  - The comparison is **`rolling_sum + amount <= threshold`** where `rolling_sum` is the proposer's
    `APPLIED` **and `PENDING`** proposals of the same kind **for the same target** over
    `approvals.threshold_window_days` (default 30). Counting pending too means ten small grants filed
    in a minute cannot each slip under the line.
  - The window sum is taken under `pg_advisory_xact_lock(hash('approvals:<proposer>:<kind>:<target>'))`
    so two concurrent proposals cannot both pass.
  - Under the threshold ⇒ applied **in the same transaction**, `decided_by=NULL`,
    `threshold_bypass=True`, and audited as "system-approved under threshold X".
- **`approve(proposal, *, actor, note)`**
  - `select_for_update()`; require `PENDING` and not expired.
  - **Proposer ≠ approver.** Self-approval only if `approvals.allow_self_approve` is on, and then it
    sets `break_glass=True`, writes an audit row **and raises an ops alert** — it is an emergency lever,
    not a convenience.
  - ⚠️ **The superuser bypass does not apply.** [`RBAC_DESIGN.md`](RBAC_DESIGN.md) lets a superuser
    pass every permission check; separation of duties is not a permission check. A superuser approving
    their own proposal is break-glass like anyone else (see § 17).
  - Approver holds `approvals.proposals.decide` **and** the handler's `decide_permission`, and can see
    the target (`visible_to`).
  - **Staleness:** if the target's current snapshot of the touched fields differs from `before`, refuse
    with `409 stale_proposal` — someone changed it since the proposal was written, and the approver is
    looking at a diff that is no longer true.
  - **Apply inside a savepoint.** On exception the status becomes `FAILED` with `apply_error`, the
    outer transaction commits the failure, and **the approver gets a 200 showing FAILED, never a 500**.
- **The handler re-checks the proposer's permission and scope at apply time** — including a reseller
  parent scope. A proposer who lost the role, or never had scope over that tenant, cannot have the
  change laundered through someone else's approval.
- **`reject`, `withdraw`** (proposer only, while PENDING), **`expire`** (sweep after
  `approvals.pending_ttl_days`).
- **Every transition writes an audit row** ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)) and notifies
  through [`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md): approvers on `PENDING`,
  the proposer on decision.

**Jobs:** `expire_pending_proposals` (hourly); `reconcile_stuck_approved` — `APPROVED` is a transient
state inside one transaction, so any row sitting in it for more than a minute is a crash and raises an
ops alert.

**Permissions:** `approvals.proposals.view` (own), `approvals.proposals.view_all`,
`approvals.proposals.decide`, `approvals.settings.manage`.

**Frontend:** a **generic approvals inbox** driven by the registry — kinds the user may decide,
filtered by scope; a detail view rendering `describe(before, payload)` as an Old → New table; approve
/ reject with a mandatory note on reject; a "my proposals" view; a banner on any target that has a
pending proposal ("a change to this is awaiting approval"). Product screens call `propose` instead of
writing — the form's submit button says **"Submit for approval"** when a handler exists and the
amount exceeds the threshold (the server decides; the label is a courtesy).

**Enforced by.** `approvals/tests/test_maker_checker.py` — self-approve refused; superuser
self-approve refused unless break-glass; split grants within the window are pending; concurrent
proposals serialise; apply failure yields FAILED + 200; proposer lost permission ⇒ FAILED; stale
target ⇒ 409. `test_default_threshold_is_zero.py`. `test_handler_completeness.py` — every registered
handler declares every hook and both permissions exist in the catalog.

**Configuration keys:** `approvals.enabled`, `approvals.threshold_window_days`,
`approvals.allow_self_approve` (default `false`), `approvals.pending_ttl_days`, and one threshold key
per handler (default `0`).

**Traps.** Thresholds summing only applied proposals · checking the proposer's rights at propose time
only · the superuser bypassing four-eyes · a 500 on apply failure leaving the approver unsure whether
it applied · approving a diff that no longer matches the target.

### 3.2 Approval chains for documents

For documents that pass through several reviewers (reports, purchase orders, incident write-ups):

- `approvals_chain_template(scope_type, scope_id, document_kind, steps JSONB)` — ordered steps, each
  `{role | user, min_approvals, can_edit}`.
- **At submit, the chain is snapshotted** into `approvals_chain_instance` + `approvals_chain_step`
  rows on the document. **Editing the template never changes an in-flight document** — the people
  reviewing it were decided when it was submitted.
- Steps are sequential; the author can never approve their own step; rejection returns the document
  to draft with the note; the final approval freezes the document (§ 4).
- The same inbox (§ 3.1) lists pending chain steps.

---

## 4. Templated documents — **Tier 3 · Module**

**Purpose.** Documents built from tenant-editable templates with merge fields (delivery notes,
quotations, contracts, letters, certificates) and **generated structured documents** (reports, RCAs,
inspection records) with review and signatures. **Who needs it:** ERP (delivery notes, purchase
orders), CRM (quotes, proposals), e-commerce (packing slips), SaaS (certificates, reports). PDF
rendering itself is the primitive in [`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md); this module is
templates, data, lifecycle and signatures.

**Data model.**

```
documents_template          id, scope_type, scope_id NULL, kind, name, body_html, is_system,
                            version, is_active, updated_by
documents_template_version  template FK, version, body_html, created_by, created_at    (immutable)
documents_document          public_id, kind, template_version FK NULL, status (DRAFT|UNDER_REVIEW|FINAL|VOID),
                            data JSONB (structured sections), number (sequence primitive),
                            chain_instance FK NULL, final_file NULL, final_sha256, finalised_at
documents_signature         user FK, image (PNG), created_at
```

Partial unique **one active template per `(scope_type, scope_id, kind)`**.

**Extension points:** `documents.kinds` — `DocumentKind(key, label, sections_schema, protected,
permission_prefix)`; `documents.merge_fields` — `MergeField(kind, token, label, resolver(ctx) -> str,
sample, is_html=False)`.

**Rules.**
- **Merge tokens come from a registry, per kind.** Saving a template with an unknown `{{token}}` is
  **refused** — never silently rendered blank. The editor's token picker is generated from the same
  registry.
- **Substitution is not a template language.** Tenant-authored HTML is never executed as a Django or
  Jinja template; tokens are replaced by resolver output, **HTML-escaped unless the field declares
  `is_html`**. If a product genuinely needs logic in templates, it uses a sandboxed environment and an
  ADR.
- **The WYSIWYG editor round-trips raw HTML** (a TipTap-class editor), and the HTML is **sanitised
  against an allow-list** on save *and* at render, so stored bytes and printed bytes agree.
- **Resolution is most-specific-wins:** tenant template → platform system template. `is_system`
  templates cannot be deleted; a tenant "edits" one by copying it.
- **Protected kinds cannot be tenant-overridden** — anything that carries a single-use token
  (verification, reset, invitation). A real incident: tenant-authored bodies on those messages could
  have exfiltrated the token or phished with the platform's authority. **Unknown kinds are protected
  by default** so a future kind fails closed.
- **Previews are never downloadable as final.** Drafts render as an HTML preview with a DRAFT
  watermark; the PDF endpoint refuses unless `status=FINAL`. The final PDF is rendered **once**,
  stored, hashed, and immutable; a correction is a new version, never a re-render in place.
- **Approval chain snapshotted at submit** (§ 3.2). **Signatures** print on the approval blocks at
  finalisation. Uploaded signature images are **rasterised to PNG at upload** — an SVG can carry
  script.
- **Rendering uses the PDF primitive's no-network fetcher** — a tenant-controlled logo URL is never
  fetched server-side (SSRF); images are inlined from storage.

**Jobs:** `render_final_document` (Celery, on the documents queue), retention of drafts.

**Permissions:** `documents.templates.view` / `.manage`, `documents.documents.view` / `.create` /
`.submit` / `.finalise` / `.void`, plus per-kind permissions via `permission_prefix`.

**Frontend:** template editor with token picker and a live preview using `sample` values; document
form generated from `sections_schema`; review screen with the chain's progress; signature capture
(draw or upload).

**Enforced by.** `test_unknown_token_refused.py`, `test_merge_values_escaped.py`,
`test_protected_kind_not_overridable.py`, `test_draft_pdf_refused.py`, `test_chain_snapshot_frozen.py`,
`test_render_no_network.py` (a template with an external image URL renders with no outbound request —
the HTTP client is patched to fail the test if called).

**Configuration keys:** `documents.enabled`, `documents.sanitizer_profile`,
`documents.draft_retention_days`.

---

## 5. Data ingestion / sync framework — **Tier 3 · Module**

**Purpose.** One intake pipeline for every inbound feed — CSV upload, spreadsheet, partner API,
device telemetry, e-mail attachment — so that records arriving from outside go through the same
matching, review and audit. **Who needs it:** ERP (supplier catalogues, stock counts), CRM (lead
imports, enrichment feeds), e-commerce (marketplace listings, supplier feeds), SaaS (directory sync).
Import/export of the product's *own* data is the primitive in
[`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md); this module is for *external* sources.

**Data model.**

```
ingest_source          key, adapter_key, target_key, config JSONB, credential_ref NULL, enabled,
                       schedule, baseline_at NULL, last_run_at, consecutive_failures, next_attempt_at
ingest_run             source FK, started_at, finished_at, status (OK|EMPTY|FAILED|PARTIAL),
                       seen, applied, pending, errors, summary JSONB
ingest_pending_change  source FK, run FK, entity_type, match_key, operation (CREATE|UPDATE|REMOVE|MERGE),
                       proposed JSONB, current JSONB, status (PENDING|CLAIMED|ACCEPTED|DISMISSED|SUPERSEDED),
                       claimed_by, decided_by, decided_at, reason, first_seen_at, last_seen_at
```

Partial unique **one open pending change per `(source, entity_type, match_key)`** where status is
`PENDING` or `CLAIMED` — a re-run updates `last_seen_at` and `proposed` instead of stacking duplicates
(the findings-queue shape).

**Extension points:** `ingest.adapters` — `Adapter(key, fetch(source, since) -> Iterable[Record],
to_changeset(records) -> ChangeSet, config_schema)`; `ingest.targets` — registered by the owning
plugin: `Target(key, entity_type, match(change) -> Match, apply_ops={upsert, update, remove},
normaliser_profile)`.

**Rules.**
- **Every source is a thin adapter producing the shared `ChangeSet` DTO.** The owning plugin has a
  **closed set of audited apply operations**; adapters never write models.
- **No silent creates.** A matched record is refreshed; **an unmatched record becomes a pending
  `CREATE`** a human claims or dismisses. An exact match on a strong identifier (serial, external id)
  may auto-adopt, and says so in the run summary.
- **Absence never means delete.** Feeds are additive-authoritative: a record missing from this run
  becomes, at most, a pending `REMOVE`. A partial export must never delete half the catalogue.
- **Adapters own only their fields.** A human-declared field is never overwritten by a
  machine-reported one; provenance records which is which ([`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)).
- **Name resolution is normalised-exact, per profile** (company: strip legal suffixes; catalogue:
  keep model numbers), **never fuzzy or trigram.** Near-duplicates go to a confirmation queue. A real
  incident: fuzzy matching auto-created duplicate vendors and product models that took weeks to merge.
- **First sync against an empty target is a baseline** — one audited operation, not ten thousand
  pending creates. `baseline_at` records it.
- **Bulk levers exist and are permissioned:** *accept all* (filtered, with a count confirmation) and
  *re-baseline* (resets `baseline_at` and dismisses open changes, audited with the count).
- **A pull that collected nothing is a failure** (`EMPTY`) unless the source declares an empty result
  valid — an expired credential looks exactly like "no changes".
- **Every run reports what it applied**, not what it saw.
- **Backoff per dead target:** from the third consecutive failure, `next_attempt_at` backs off
  exponentially (1 h → 2 h → 4 h, capped at 24 h, configurable). Scheduled sweeps skip backed-off
  sources; a manual *Refresh now* ignores the backoff. **Bounded concurrency** across sources. A real
  incident: one dead target multiplied its timeout by the fleet size and stalled every sync.
- **Delta cursors advance only after the run commits** — a crash mid-run re-reads, never skips.
- **Unchanged sections are skipped by per-section content hash**; metadata (timestamps, fetch ids) is
  never part of the hash.
- **Never cache a failed lookup** ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).

**Jobs:** one scheduled job per enabled source (registered with the job registry), a backoff-aware
sweep, `expire_dismissed_changes`.

**Permissions:** `ingest.sources.view` / `.manage`, `ingest.changes.review`,
`ingest.changes.bulk_accept`, `ingest.sources.rebaseline`.

**Frontend:** sources list with health (last run, applied/pending/errors, backoff state), run history,
**the review queue** (claim, accept, dismiss with reason, diff of `current` vs `proposed`), bulk
accept with a typed count confirmation.

**Enforced by.** `test_no_silent_create.py`, `test_absence_is_not_delete.py`,
`test_empty_pull_is_failure.py`, `test_baseline_on_empty_target.py`, `test_backoff_schedule.py`,
`test_pending_change_deduped.py`, `test_adapter_cannot_write_models.py` (AST: adapter modules import
no model from a target plugin).

**Configuration keys:** `ingest.enabled`, `ingest.backoff.start_after_failures`,
`ingest.backoff.base_hours`, `ingest.backoff.cap_hours`, `ingest.max_concurrency`,
`ingest.dismissed_retention_days`.

---

## 6. Alert rules engine — **Tier 3 · Module**

**Purpose.** Business-condition alerts that any plugin can contribute and operators can tune: stock
below reorder level, contract expiring, SLA at risk, payment stuck, sync failing. **Who needs it:**
ERP (reorder, expiry), CRM (stale deals), e-commerce (low stock, failed fulfilment), SaaS (quota
near limit). Operational alerting for the platform itself (worker down, error spike) is
[`NOTIFICATIONS_AND_ALERTING.md`](NOTIFICATIONS_AND_ALERTING.md); this module is the in-app rules
engine.

**Data model.**

```
alerts_rule   id, name, source_key, config JSONB, is_active, is_system, level NULL (override),
              scope_type, scope_id NULL, last_evaluated_at, last_error NULL
alerts_event  id, rule FK, source_key, breach_key, title, detail, level, url, scope_type, scope_id,
              status (OPEN|RESOLVED), opened_at, last_seen_at, resolved_at, acknowledged_by, acknowledged_at
```

Partial unique **`(rule, breach_key) WHERE status='OPEN'`**.

**Extension point `alerts.sources`:**

```python
AlertSource(key="inventory.low_stock", label="Low stock", level="warning",
            config_schema={...JSON Schema...}, permission="inventory.stock.view",
            evaluate=evaluate_low_stock,       # (ctx, config) -> list[Breach(key, title, detail, url, scope)]
            default_rule={"name": "Stock below reorder level", "config": {"threshold_pct": 100}},
            can_disable=True)
```

**Rules.**
- **Rules are data (`source key + JSON config`); sources are code.** Config is validated against the
  source's schema on save.
- **A source's `default_rule` is auto-provisioned as a locked system rule** by an idempotent seeder:
  it cannot be deleted or re-sourced; it can be disabled only if the source says `can_disable`.
- **A beat sweep** (every `alerts.sweep_minutes`, default 10; its schedule registered through the job
  registry, single-flight) evaluates each active rule and **reconciles** events: new breach keys open
  events and notify; existing keys bump `last_seen_at`; missing keys resolve.
- ⚠️ **An evaluation that raised resolves nothing.** It sets `last_error`, leaves open events open,
  and surfaces the rule as erroring. Treating an exception as "no breaches" mass-resolves every alert
  exactly when the system is least healthy — the "zero is not a fact" rule in
  [`OBSERVABILITY.md`](OBSERVABILITY.md).
- **Breach keys are stable** — `<entity>:<id>:<condition>` — and never contain a volatile value (a
  count, a percentage), or every sweep churns resolve/open and notifies each time.
- **Immediate resolve on recovery:** domain code calls `alerts.resolve_breach(source_key, key)` the
  moment the condition clears (stock received, invoice paid), rather than waiting for the sweep.
- **Notify on state change only** — opening, resolving, level escalation — never on every sweep.
- **The badge reads OPEN events visible to the user** (scope + source permission), never a live
  re-evaluation, so the badge and the list always agree.
- Evaluation has a per-source timeout and runs each source in isolation — one slow source never
  delays the others.

**Permissions:** `alerts.events.view`, `alerts.events.acknowledge`, `alerts.rules.manage`, plus the
source's own permission for visibility.

**Frontend:** a bell badge + list of open events (filter by level, source, scope), event detail with
"seen since / last seen", rule editor generated from `config_schema`, rules list showing `last_error`.

**Enforced by.** `test_error_resolves_nothing.py`, `test_breach_key_stable.py`,
`test_system_rule_provisioned_and_locked.py`, `test_resolve_on_recovery.py`,
`test_badge_matches_list.py`, `test_source_completeness.py` (every source has a schema, a permission
that exists, and a valid default rule).

**Configuration keys:** `alerts.enabled`, `alerts.sweep_minutes`, `alerts.source_timeout_seconds`,
`alerts.resolved_retention_days`.

---

## 7. Automation engine — **Tier 3 · Module**

**Purpose.** Trigger → action rules operators configure without code: "when an order ships, e-mail
the customer", "every Monday, export last week's leads", "when a webhook arrives, create a ticket".
**Who needs it:** all four product kinds, eventually. The **idempotent run ledger** it is built on is
the same shape as the core job-run ledger ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).

**Data model.**

```
automation_rule  id, name, trigger_kind (MANUAL|SCHEDULE|EVENT|WEBHOOK|API), trigger_config JSONB,
                 action_key, action_config JSONB, enabled, source_app, owner FK,
                 idempotency (NONE|PER_TRIGGER|KEY), idempotency_template, max_retries, retry_backoff_seconds,
                 webhook_token_hash NULL
automation_run   id, rule FK SET_NULL, action_key (snapshot), status (PENDING|RUNNING|SUCCEEDED|FAILED|
                 RETRYING|SKIPPED_DUPLICATE|SKIPPED_LOOP|CANCELLED), attempt, idempotency_key, depth,
                 input JSONB, output JSONB, error, actor, scheduled_for, started_at, finished_at
```

**Partial `UniqueConstraint(action_key, idempotency_key) WHERE idempotency_key <> ''`** — at-least-once
delivery plus dedupe, enforced by the database, not by a check-then-insert.

**Extension points:** `automation.actions` — `Action(key, label, config_schema, input_schema,
run(ctx, config, input) -> output, required_permission, effect: INTERNAL|OUTBOUND|DESTRUCTIVE)`;
`automation.templates` — blueprints plugins register ("Notify on new order"); events come from the
core event bus catalog.

**Rules.**
- **Triggers:** *manual* is "Run now"; *schedule* binds a schedule in the job registry; *event* uses
  **one wildcard subscriber on the core event bus** that routes by event name to enabled rules — never
  a subscriber per rule; *webhook* is a per-rule URL whose token is **hashed at rest** and shown once;
  *api* is a machine principal holding the `automation.rules.trigger` ability
  ([`API_PLATFORM.md`](API_PLATFORM.md)).
- **Idempotency modes:** `NONE`; `PER_TRIGGER` (key = the triggering event id or schedule slot);
  `KEY` (key rendered from `idempotency_template` with **allow-listed placeholders only**). A duplicate
  records `SKIPPED_DUPLICATE` and does nothing else.
- **The engine:** resolve the action by key (unknown ⇒ run `FAILED`, rule auto-disabled with reason) →
  idempotency → create the ledger row → execute → record. The Celery task re-enqueues with
  exponential backoff up to `max_retries` (capped by `automation.max_retries_ceiling`).
- **Actions run with the rule owner's permissions, re-checked at run time.** An owner who is
  deactivated or loses the permission ⇒ the rule is disabled with a reason, not run as a ghost.
- **Loop protection:** a run triggered by an event that another automation run emitted carries
  `depth + 1`; beyond `automation.max_depth` (default 3) the run records `SKIPPED_LOOP`.
- **Outbound and destructive actions obey the non-prod outbound guard**
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)); `DESTRUCTIVE` actions require
  `automation.rules.manage_destructive` to configure.
- **Optional providers** (AI, OCR, inbound e-mail) register only when named in
  `automation.optional_providers` and are absent-tolerant.
- **Worker-unreachable banner:** the rules screen reads worker liveness from the job monitor and shows
  "automations are not running" when no worker has heartbeated — a rule that silently never fires is
  the failure this prevents.

**Permissions:** `automation.rules.view` / `.manage` / `.manage_destructive`, `automation.runs.view`,
`automation.rules.trigger` (ability for machines).

**Frontend:** rule builder (trigger picker, action picker, forms generated from schemas), template
gallery, run history with input/output/error, "Run now", worker banner.

**Enforced by.** `test_run_ledger_dedupe.py` (two concurrent deliveries, one run),
`test_owner_permission_rechecked.py`, `test_loop_depth.py`, `test_unknown_action_disables_rule.py`,
`test_webhook_token_hashed.py`, `test_action_completeness.py`.

**Configuration keys:** `automation.enabled`, `automation.max_depth`,
`automation.max_retries_ceiling`, `automation.optional_providers`, `automation.run_retention_days`.

---
## 8. Knowledge base / in-app help centre — **Tier 3 · Module** (+ **Process** rule)

**Purpose.** Operator and customer help that lives beside the code it describes, bound to the screen
the reader is on, and **checked in CI** so it cannot silently fall behind. **Who needs it:** every
product with users who are not its developers.

**Layout.** Each plugin (and `project/`) ships `help/**/*.md` plus `help/images/`. The module is
model-less: it discovers pages by walking each installed app's `help/` directory, keyed by slug
`<app>/<path>`, and **hides pages of soft-disabled plugins**. This fits the plugin rule that a plugin
documents itself in its own repo ([`../planning/CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md)
§ 0) — operator help is content that ships *with* the feature.

**Front-matter** (strict parser; a malformed block raises with the file path):

```yaml
---
title: Approving a balance adjustment
order: 20
routes: ["/approvals/**", "/billing/accounts/*/adjust"]   # * = one segment, ** = many
nav: approvals
summary: Who can approve, what the threshold means, and what FAILED means.
audience: operator            # operator | customer | both
---
```

**Rules.**
- **Most specific wins** when several pages bind a route: longest literal prefix, then fewest
  wildcards, then `order`, then slug. A page with no `routes` binds by convention (id-like segments
  become `view`).
- **The tree is grouped by the live navigation registry's sections**, not by Django app — the reader
  thinks in screens, not packages.
- **Fingerprint cache:** the index is keyed by a fingerprint of every help directory (file set +
  mtimes), so an edit appears without a restart and an unchanged tree is never re-parsed.
- **Every feature ships or corrects its help page in the same change.** Help written afterwards is
  written by someone who has forgotten the details. Demo data must reproduce the screenshots.
- **Coverage gate:** every route in the navigation registry has a bound article **or** an entry in
  `help/exemptions.yaml` with a written rationale.
- **Launch state comes from feature flags** ([`CONFIGURATION.md`](CONFIGURATION.md)), not a second
  file: an article for a dark feature is an internal draft; flipping the flag publishes it. A real
  incident: a flag flip went live while its article stayed hidden, because launch state lived in two
  places.
- **Markdown is rendered with raw HTML disabled** (or an allow-list sanitiser); image paths are
  validated to stay inside the plugin's `help/images/`.
- **Public help (and any machine-readable site summary) is served only on platform hosts** — on a
  white-label host (§ 10) it returns 404, so tenant domains do not duplicate the platform's content or
  leak the platform's name.

**Optional generation, validated against facts.** Articles may be drafted by a model, but only
through a pipeline that validates every article against **facts extracted from the registries**:
permissions, nav labels and routes, API paths, error codes, feature flags, settings keys. Validator
rules: every backticked permission exists · every breadcrumb/button label exists in nav or route
facts · every API path exists · **no bare number that does not appear in the facts** · links resolve ·
troubleshooting error codes exist · images exist · launch state respected · no unfilled placeholders ·
front-matter valid. This is the strongest argument for making every core registry introspectable.

**Screenshot pipeline (optional):** a Playwright capture list, a seed step that provisions realistic
state, **PII masking on every capture** (e-mails, names, tenant names, addresses, amounts marked
private, tokens), a host allow-list with an explicit confirmation to run against production, size caps,
a manifest with SHA-256 and source commit, and a weekly drift check that **updates one tracking issue**
rather than opening a new one each week.

**API:** `GET /api/kb/for/?path=<pathname>` → bound article(s); `GET /api/kb/tree/`;
`GET /api/kb/pages/<slug>/`. Results are filtered by `audience` and the article's nav section's
permission.

**Frontend:** a help side-panel that follows the pathname, a help-centre page grouped by nav section,
search over titles and summaries (§ 11).

**Enforced by.** `manage.py kb_check` in CI (front-matter, duplicate slugs, glob syntax, image paths,
label collisions) · `test_kb_nav_coverage.py` (universe = the nav registry; **fails when the registry
is empty**) · `test_kb_launch_state.py` · `test_kb_hidden_on_tenant_hosts.py` ·
`test_kb_soft_disabled_hidden.py`.

**Configuration keys:** `kb.enabled`, `kb.public_enabled`, `kb.generation.enabled` (default `false`).

---

## 9. Helpdesk / support — **Tier 3 · Module**

**Purpose.** Tickets from customers and staff, worked by agents against business-hours SLAs. **Who
needs it:** SaaS and e-commerce (customer support), ERP (internal service desk), CRM (case
management).

**Data model (outline).** `helpdesk_ticket` (public_id, number, requester, organisation/scope,
subject, status, priority, channel, assignee, group, `sla_policy_snapshot` JSONB,
`first_response_due_at`, `resolution_due_at`, `first_responded_at`, `resolved_at`, `paused_at`,
`accumulated_pause_seconds`, `merged_into` FK NULL, `anonymised_at`), `helpdesk_message` (ticket,
author, `visibility` PUBLIC | INTERNAL, body, via), `helpdesk_attachment`, `helpdesk_watcher`,
`helpdesk_csat` (ticket unique, token hash, rating, comment, responded_at), `helpdesk_sla_policy`,
`helpdesk_inbound_mail` (raw message ref, parsed status, loop flags).

**Rules.**
- **Statuses go through the state-machine primitive** ([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md)),
  and **a status never contradicts a write-once timestamp**: a ticket with `first_responded_at` cannot
  return to `NEW`.
- **SLA is resolved and stamped at creation.** The policy (targets per priority) is copied onto the
  ticket, so editing the policy never retroactively changes open tickets' deadlines.
- **The clock is a business calendar** — weekly schedule, holidays, **timezone from configuration**,
  never a hard-coded default ([`DOMAIN_PRIMITIVES.md`](DOMAIN_PRIMITIVES.md) business calendar).
- **Pause accounting:** entering a pending-on-customer status sets `paused_at`; leaving adds the
  business-time elapsed to `accumulated_pause_seconds`. Deadlines are computed from creation +
  target + pause, never from `updated_at`.
- A **public** agent reply satisfies first response; *solved* satisfies resolution; **reopening resets
  the resolution target** (not first response).
- **A sweep every 60 s** raises warnings at `helpdesk.sla.warning_pct` (default 75%) and records
  breaches, committing in small batches so a long backlog never holds a lock for minutes. Breach is a
  **derived fact** plus a recorded event — never a boolean someone can forget to update.
- **Internal notes never reach the requester.** Two serializers per audience; a **property test**
  walks every requester-facing payload for internal message ids and bodies.
- **Anonymous and requester views mask internal statuses** (a spammer is not told they were
  classified as spam).
- **Watchers** are notified per their preferences; **merge** closes the source as merged with a
  pointer, moves or links messages, notifies the requester, is audited, and **never crosses tenants**.
- **CSAT:** a single-use token per solved ticket, sent after a configurable delay, one response.
- **Inbound e-mail:** provider webhook or poll; thread by a reply token in the address plus
  `In-Reply-To`/`References`; **loop detection** (`Auto-Submitted`, bulk precedence, per-sender rate);
  attachments through the upload validator ([`API_PLATFORM.md`](API_PLATFORM.md)); an unknown-sender
  policy (create / reject / hold).
- **Outbound mail goes through the outbox** ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).
- **Retention by data class:** closed tickets are **anonymised, not deleted**, after
  `helpdesk.retention.anonymise_after_days` — identity, bodies, payloads and AI fields scrubbed; rows,
  statuses and timestamps kept for metrics. Attachments are deleted **in storage first**; a row whose
  object cannot be deleted is skipped untouched and retried (never half-erased). Registered with the
  retention engine in [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md).
- **AI features default off** (`helpdesk.ai.enabled=false`), and when on, **PII is masked before any
  text leaves the system** (`helpdesk.ai.pii_mode=mask`). Suggested replies are drafts an agent sends.

**Jobs:** `sla_sweep` (60 s), `poll_inbound_mail`, `send_csat_surveys`, `enforce_helpdesk_retention`.

**Permissions:** `helpdesk.tickets.view` / `.view_all` / `.reply` / `.internal_note` / `.assign` /
`.merge`, `helpdesk.sla.manage`, `helpdesk.settings.manage`, customer `helpdesk.self.create` /
`.self.view`.

**Metrics:** first-response histogram, breach counter, backlog gauge ([`OBSERVABILITY.md`](OBSERVABILITY.md)).

**Frontend:** agent console (queues, SLA countdowns, internal/public composer with an unmistakable
internal state), customer portal, CSAT page, SLA policy editor with a calendar preview.

**Enforced by.** `test_sla_stamped_at_creation.py`, `test_pause_accounting.py`,
`test_status_never_contradicts_timestamp.py`, `test_internal_never_in_requester_payload.py`,
`test_merge_same_tenant_only.py`, `test_mail_loop_detection.py`, `test_retention_anonymise.py`,
`test_ai_default_off_and_masked.py`.

**Configuration keys:** `helpdesk.enabled`, `helpdesk.sla.warning_pct`, `helpdesk.calendar`,
`helpdesk.csat.delay_hours`, `helpdesk.inbound.unknown_sender_policy`,
`helpdesk.retention.anonymise_after_days`, `helpdesk.ai.enabled`, `helpdesk.ai.pii_mode`.

---

## 10. Organisations, tenancy & white-label — **Tier 3 · Module** (pending D3)

> 🚧 **This section depends on an open decision** — [`DATA_MODEL.md`](DATA_MODEL.md) **D3** ("Is
> there multi-tenancy in the core?"). It presents the evidence and the design either way. **Do not
> build it until D3 is an ADR.**

### 10.1 The decision evidence

| | **A — No tenant in core** (current D3 recommendation) | **B — Core-owned tenant table, products extend it** |
|---|---|---|
| Core schema | Users only; `visible_to()` is the seam | `core_organisation(id, public_id, name, slug, status, parent NULL)`; `User`↔org membership |
| Product adds tenancy | Adds a model and touches every scoped table and signature | Adds a 1:1 extension (`OneToOneField(primary_key=True)` or multi-table inheritance) with its own columns |
| Measured retrofit cost | In one mature codebase, adding tenancy after the fact was **a sweep across roughly 258 function signatures**, and until the tenant table moved into the core the core schema **could not even be created** without a product table | Paid once, in the core, tested once |
| Cost to a single-tenant product | None | One table with one row, and a membership check that always passes |
| Auth impact | None | The per-request auth guard branches on org **status** |

**Why the status vocabulary must be core-owned if B is chosen:** the authentication path — which is
core — branches on it. `PENDING` is refused (onboarding must not grant login), `SUSPENDED` revokes
sessions with a distinct message, `ACTIVE` passes. If a product owned the vocabulary, the core auth
guard would have to import the product. **No polymorphic discriminator** on the core table: the core
must be able to load `user.organisation` without the product's model loaded.

**Recommendation for the owner:** if the products planned on this base include *any* B2B SaaS or
reseller product, choose **B** now; the evidence says the retrofit is the most expensive change on
the data model page. If every planned product is single-tenant back office, keep **A** and record the
measured retrofit cost in the ADR so the choice is made knowingly.

### 10.2 The design (whichever way D3 goes, these are the rules)

**Scoping** — extends [`DATA_MODEL.md`](DATA_MODEL.md) § 5:
- **Every model with an organisation FK registers its scope** (`registry.scopes.register(Model,
  owner="organisation")`), and a test enumerates `apps.get_models()` and fails for any
  org-bearing model not registered. An unregistered model **raises** on scoping rather than returning
  the queryset unfiltered.
- **Reads and writes are scoped separately.** `visible_to(user)` for reads; `writable_by(user)` /
  `assert_writable(obj, user)` in `get_object()` for update and delete. A real incident: reads were
  tenant-scoped, writes were not — a user who could not *see* a row could `PATCH` it by id, change its
  e-mail and drive a password reset.
- **"No organisation and not admin" ⇒ `.none()`.** Machine and anonymous callers get only a model's
  declared public predicate, or nothing.
- **A scoping helper never returns `None` to mean "all".** A real incident: an admin-bypass helper
  returned `None` for "no restriction", a caller built an unscoped query from it, and non-admins saw
  every tenant. The admin path is an explicit, audited `unscoped(reason=…)`.
- **Soft-deleted organisations are excluded in every membership check** — a real gap: list helpers
  filtered them, but the object-access and permission checks did not.
- **Optional model-level safety net** (recommended if B): a default manager filtering on a
  request-scoped tenant held in a `contextvar` **set and reset in a `finally` in the same middleware**,
  `base_manager_name` so related-object access is scoped too, and `Model.unscoped(reason=…)` as the
  logged bypass. Decide explicitly what the admin, `dumpdata` and migrations see (they use the base
  manager).
- **Delegation grants AND with the tenant wall** — a grant can never cross a tenant (§ 14).
- **RBAC is checked in the owning organisation**, never the caller-chosen one.

**Active organisation:** carried **in the URL** (`/o/<slug>/…`) for deep links, or at minimum as an
`X-Organization-Id` header validated for membership on every request (400 malformed, 403 non-member).
**No fallback to "the user's primary organisation" for writes.** Frontend cache keys include the
organisation id ([`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)). A real incident: when the org context
was omitted, the backend fell back to the primary org and returned the wrong tenant's data.

**Last owner protection:** a database trigger refuses deleting or demoting the last owner of an
organisation (exempting the cascade when the organisation itself is deleted).

**Tenant resolution for white-label** — middleware, precedence:
1. **Verified custom domain** (from the proxy-matched `Host`, **never `X-Forwarded-Host`** unless the
   trusted-proxy configuration says so),
2. **subdomain** of a platform domain,
3. **tenant header** — **for reads and display only.** A client-supplied tenant header is fine for
   rendering a login page's branding; it is never authority for a state-changing request. Signup
   derives the tenant from `Host` and requires `Origin` to match the verified domain.

Platform hosts are an explicit list and skip resolution. Lookups use a positive/negative TTL cache
with a hard size cap, invalidated across replicas by a generation counter in the cache.

**Custom domains:** normalise (strip scheme, path, userinfo, port, trailing dot; lowercase); refuse
platform hosts and suffixes; unique constraint (the race is caught by the constraint, not a pre-check);
one source for the verification-token format; DNS TXT check with a result enum (`MATCH` | `MISMATCH` |
`NXDOMAIN` | `NO_ANSWER` | `ERROR`); **a reconciler promotes only on `MATCH` and never marks FAILED on a
transient error**; **verified domains are re-verified periodically** (a real gap: a lapsed or
transferred domain kept working forever). Edge configuration, if generated, uses explicit
`server_name` only (never a catch-all), **fails closed when no certificate exists**, writes atomically,
and reloads only after a config test passes.

**Dynamic CORS:** verified tenant domains are allowed without a restart — `django-cors-headers`'
`check_request_enabled` signal backed by the verified-domain table — and the tenant header is in the
allowed headers or cross-origin portals fail preflight.

**Per-tenant configuration**, each resolved most-specific-first (tenant → parent → platform):
branding (logo, colours, names, support and legal links — **colours accepted only as hex or HSL
triplets ≤ 64 chars, normalised server-side and re-validated client-side; derived tokens built only
from validated input**; rendering is [`FRONTEND_PLATFORM.md`](FRONTEND_PLATFORM.md)), settings,
pricing overrides (§ 2.23), gateway connections (§ 2.14), e-mail and document templates (protected
kinds excluded, § 4), notification senders, and **integration enablement per scope** (platform scope
default-on, tenant scope default-off, organisation overrides sparse; its config JSON is **never** a
place for secrets).

**Reseller hierarchy:** `parent` on the organisation plus a `kind` (`DIRECT` | `RESELLER` |
`RESELLER_CUSTOMER`). Scope checks accept parent membership where the design says so. **An orphaned
customer (parent missing) fails closed to its own scope**, never to platform scope.

**Per-host cookies:** session cookies are **host-only** (no `Domain` attribute), so a session on one
tenant domain never applies on another, and the cookie name is derived from the project identity
([`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md)). Changing a tenant's domain **resets every flag derived from
the old one** (e.g. an OAuth origin registration) on every code path that changes it.

**Capability hints:** the public branding endpoint returns host-scoped **hints** (payments shown?
signup open? support mode?) for the pre-auth UI; `/api/me/bootstrap` returns the org-scoped
**authority**. The UI fails **open** only for *hiding* surfaces while loading; anything that widens
access (signup) fails **closed** when its setting is missing.

**Frontend (Next.js 16):** the root layout fetches branding server-side per request (React `cache()`,
a short timeout, `redirect: 'error'`, skipped on platform hosts) so the **first paint is branded**; a
provider re-applies title/favicon/CSS variables on navigation and undoes only what it applied.
`proxy.ts` (Next 16's renamed middleware) may *route* by host but is never an authorization point.

**Enforced by.** `test_every_org_model_scoped.py`, `test_write_path_scoped.py` (cross-tenant `PATCH`
404s), `test_zero_membership_sees_nothing.py` (every list endpoint as a user in no organisation),
`test_header_not_authority.py`, `test_forwarded_host_ignored.py`, `test_orphan_customer_fails_closed.py`,
`test_brand_colour_grammar.py`, `test_last_owner_trigger.py`, and a **different-tenant actor fixture**
used by every plugin's scoping tests (a bypass role or a user in no tenant passes before *and* after
a fix and proves nothing).

**Configuration keys:** `tenancy.platform_hosts`, `tenancy.header_resolution_enabled` (kill switch
retiring the header path), `tenancy.domain_reverify_days`, `tenancy.domain_cache_ttl_seconds`,
`tenancy.signup.require_origin_match`.

---

## 11. Global search — **Tier 2 · Core** (seam) + **Tier 3 · Module**

**Split.** The `search` registry and its security rules are core — they are already in
[`../planning/CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md) § 2, and every
back office wants a search box. The **module** adds DB-configurable entity rows, the search log and
reports, an external engine adapter, and the command palette's result page.

**Registration** (code, in each plugin's `ready()`):

```python
registry.search.register(SearchEntity(
    key="billing.documents", label="Invoices", group="Billing", icon="receipt",
    model="billing.Document", fields=("number", "customer_snapshot__name"),
    permission="billing.documents.view", url_name="billing:document-detail", url_arg="public_id",
    title="{number}", subtitle="{customer_name} · {status}",
))
```

**Rules — treat configured entity rows as hostile input.** If an admin can edit which fields are
searched, the configuration is an attack surface:
- **L1 — per-entity permission.** Unknown permission codes are flagged by the seeder and a system
  check; a real incident: entities gated on non-existent permission names were invisible to everyone
  but superusers for two months.
- **L2 — model allow-list by dict membership.** A DB row names a registry **key**; resolution is a
  dictionary lookup. **Never `import_string` or `apps.get_model` on admin-supplied text** — a test
  asserts resolution imports nothing.
- **L3 — field allow-list plus a sensitive denylist.** Only fields declared in the registration are
  searchable or displayable; names matching `password|token|secret|key|hash|otp|session` are
  unreachable from search *and* from display templates, even if declared.
- **Row scoping through `visible_to(user)` on every hit.** Search must never become a way to enumerate
  what the list endpoint refuses.
- **Minimum query length** (2), **per-entity and total result caps**, rate-limited endpoint.
- **Display templates use allow-listed `{placeholder}` tokens only**; a hit whose route arguments do not
  resolve is dropped, not rendered as a broken link.
- **Withheld areas are named.** A source that errored or timed out is reported in the response
  (`withheld: [{key, label, reason}]`) so an empty result is never a false "nothing exists". Sources the
  user lacks permission for are simply absent.
- **An external engine is an adapter, not an authority.** Postgres full-text (`SearchVector` + GIN,
  language from configuration) is the default; a Meilisearch/OpenSearch adapter may rank, but ids it
  returns are **re-queried through `visible_to()`** before anything is shown — an index returns
  cross-tenant ids.
- **Search log** (`search_log`: user, query, result_count, duration_ms, at) with retention, feeding a
  "most searched, zero results" report.
- **`manage.py search_reconcile`** reports entities whose model is gone and fields the backend cannot
  index (a real incident: a computed field silently removed an entity from results).

**Frontend:** the command palette (`/` or ⌘K, with a typing-target guard) draws navigation entries from
the nav registry (already permission- and flag-filtered) plus plugin-registered actions and search
hits; a full results page grouped by entity.

**Enforced by.** `tests/core/test_search_security.py` — no permission ⇒ no hits; unscoped rows never
returned; unknown key resolves to nothing and imports nothing; sensitive field unreachable even when
declared; min length; caps; unresolved route hit dropped; withheld named. `test_search_permissions_exist.py`.

**Configuration keys:** `search.min_query_length`, `search.per_entity_limit`, `search.total_limit`,
`search.backend` (`postgres` | adapter key), `search.log_retention_days`.

---

## 12. AI assistant — **Tier 3 · Module**

**Purpose.** A conversational assistant that answers from live data and can take permitted actions.
**Who needs it:** increasingly all four product kinds. It is the module where a design mistake most
directly becomes a data leak.

**Extension point `ai.tools`:** `AiTool(key, description, input_schema, permission, run(ctx, input),
effect: READ|WRITE)`. Plugins register their own tools.

**Rules.**
- **Tools the user cannot use are never described to the model.** `tools_for(user)` filters by
  permission before the request is built. A tool the model has never heard of cannot be talked into
  running.
- **Tools are ORM-backed services that call `visible_to(user)`** — the assistant is scoped exactly
  like the user. **`WRITE` tools produce a proposal or a draft the user confirms**, never a silent
  mutation.
- **A raw-SQL tool, if offered at all, is for platform administrators only**, and:
  - runs in a **read-only transaction** (`SET TRANSACTION READ ONLY`) — the one control that holds even
    if the query builder is wrong — and preferably on a separate **SELECT-only database role**;
  - reads **allow-listed views**, not tables filtered by a denylist (allow-lists fail closed; schema
    discovery is limited to the same allow-list);
  - caps rows (`ai.db_tool.max_rows`, default 50), binds parameters, allow-lists operators, resolves
    identifiers against the allow-list;
  - **redacts columns** by name and suffix (`_token`, `_secret`, `_password`, `_key`, `_hash`).
- **A deterministic output guard runs on every reply:** known secret shapes (vendor-prefixed keys,
  ciphertext patterns, private keys) are redacted. PII is not blocked by default (the user may be
  entitled to it); a currency or number pattern is *flagged*, never hard-coded to one market.
- **The provider SDK is imported lazily** — an optional feature must not break boot when its package
  or key is absent. The provider key comes from the encrypted credential store
  ([`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)).
- **Check the provider's refusal stop reason before reading content**, and render refusals as
  refusals, not as empty answers. Use the provider SDK's tool runner rather than a hand-written loop.
- **Retrieved content and tool results are data.** They are delimited as such in the prompt; nothing
  inside them is followed as an instruction.
- **Anything that processes untrusted user text autonomously** (triage bots, coding agents, bulk
  summarisation of inbound mail) is **admin-triggered only**, runs with an **explicit environment and
  secret allow-list** (never the whole process environment, never a credential in a URL) and a tool
  allow-list with no shell.
- **Per-user daily cost caps** and an audit row per tool call (tool, input hash, result count).
- **Conversations belong to their user**, with retention, and are not visible to administrators
  without an audited reason.

**Permissions:** `ai.assistant.use`, `ai.assistant.sql_tool` (administrators), `ai.settings.manage`,
`ai.conversations.audit`.

**Frontend:** a chat panel with tool-call disclosure ("looked up 3 invoices"), confirmation cards for
write tools, a refusal state, a cost/limit indicator.

**Enforced by.** `test_unpermitted_tools_not_described.py` (inspects the outbound request),
`test_tool_scoped_as_user.py` (different-tenant fixture), `test_sql_tool_read_only.py` (an `INSERT`
through the tool fails at the database), `test_output_guard.py`, `test_sdk_absent_boots.py`,
`test_refusal_handled.py`, `test_agent_env_allow_list.py`.

**Configuration keys:** `ai.enabled` (default `false`), `ai.provider`, `ai.model`,
`ai.db_tool.enabled` (default `false`), `ai.db_tool.max_rows`, `ai.daily_cost_cap`,
`ai.conversation_retention_days`.

---

## 13. Feedback / bug-report widget — **Tier 3 · Module**

**Purpose.** A floating "report a problem" widget that captures enough context to reproduce the
issue. **Who needs it:** every product in beta, and every internal tool.

- **Widget** in a UI slot ([`EXTENSIBILITY.md`](EXTENSIBILITY.md)), shown only if the module is
  enabled and the user holds `feedback.reports.create`.
- **Console capture:** a ring buffer of the last N console lines, **passed through the one scrubber**
  ([`OBSERVABILITY.md`](OBSERVABILITY.md)) before upload.
- **Screenshot with masking:** DOM masking before capture — inputs, elements marked `data-private`,
  e-mail and token patterns — so the image never contains what the page was careful to hide.
- **Route inference:** the pathname is mapped to a module and nav section through the nav registry,
  so reports arrive pre-sorted.
- `feedback_report(user, route, module_key, text, console JSONB, screenshot file, user_agent, release,
  status, forwarded_ref)`; size caps; rate limit per user.
- **Forwarding to an issue tracker** is an integration adapter behind the non-prod outbound guard.
- ⚠️ **Report text is untrusted data.** A real incident: an in-app bug report fed an automatic
  code-fix agent that held repository credentials — a customer-reachable prompt-injection path to
  secrets. **Any automation on a report is operator-triggered, sandboxed, credential-scoped, with an
  environment allow-list, and never re-exposed as a user-reachable dispatch.**

**Permissions:** `feedback.reports.create`, `feedback.reports.view`, `feedback.reports.triage`.
**Configuration keys:** `feedback.enabled`, `feedback.console_lines`, `feedback.max_screenshot_kb`,
`feedback.forward_adapter`.

---

## 14. Data-access delegation — owned by [`DATA_LIFECYCLE.md`](DATA_LIFECYCLE.md)

"While I'm on leave, X can see my records" — per-module user-to-user grants independent of roles and
reporting lines. The rules that matter to modules here: the accessible set is **seeded with self**
(never an empty list a caller could read as "no restriction"); `manage` does not imply more rows than
`view` unless stated; `'*'` grants extend to modules installed later; **grants AND with the tenant
wall** and never cross it; the scope applies to lists, **filter dropdowns and counters** alike.
Grants are data scope, not permissions, so they do not contradict
[`RBAC_DESIGN.md`](RBAC_DESIGN.md)'s "no per-user grants".

---

## 15. Brief entries

### 15.1 Invitations — core, owned by [`AUTH_BLUEPRINT.md`](AUTH_BLUEPRINT.md) § 3.5

Invitations are core. What tenancy (§ 10) adds: an invitation carries the organisation and the role
scope; **it cannot grant more than the sender holds**; a preview endpoint shows the address and role
before asking for anything (the invitee's only signal the link is genuine); acceptance goes through
**one shared apply action** for every acceptance path (password, SSO); the e-mail comes from the
invitation row, never the request; acceptance never re-credentials an existing account; the
`accept_url` is returned to the inviter **only** when the mail was not actually delivered.

### 15.2 Integrations console — mechanism owned by [`JOBS_AND_INTEGRATIONS.md`](JOBS_AND_INTEGRATIONS.md)

The optional admin screen over the integration registry: one row per *relationship* (inbound route
group, outbound service, scheduled fetch), usage read through pluggable probes, **an explicit
"untracked" state** surfaced as a first-class figure with a one-click filter, windowed counts but
**all-time recency** (a windowed "last called" made the busiest integration read "never"), and a
throwing probe degrading its row to untracked instead of failing the page.

### 15.3 Agent / connector switches — **Tier 3 · Module** on a core capability seam

For connectors that let external agents (MCP-style tool servers, automation platforms) act through the
platform API:
- **A core master switch AND a per-branch switch**, where a branch is an ability namespace a plugin
  owns (`billing:*`). Effective = master ∧ branch.
- **Keyed on the caller, not the endpoint:** a boolean on the machine consumer marks it as an agent
  connector, so other consumers of the same endpoints (a website feed, a CRM push) are untouched when
  the connector is switched off. No consumer's name appears in code.
- **Distinct refusal codes** (`connector_disabled` vs `connector_branch_disabled`), outer cause
  reported first; the connector's **status endpoint stays readable while off**.
- **Admin screens show own state and effective state** and flag "ACTIVE but NOT IN EFFECT" — a branch
  that reads active while nothing works is the failure a switch hierarchy creates.
- Kill switches themselves are [`CONFIGURATION.md`](CONFIGURATION.md)'s; machine principals and
  abilities are [`API_PLATFORM.md`](API_PLATFORM.md)'s.

---

## 16. Summary — modules, who wants them, the core seams they need

| Module | ERP | CRM | E-com | SaaS | Core seams it needs | Build priority |
|---|:-:|:-:|:-:|:-:|---|---|
| **Approvals / maker-checker** (§ 3) | ✔ | ✔ | ✔ | ✔ | Extension point `approvals.handlers`; permission catalog; audit; notifications | **1** — small, and billing, RBAC and master-data edits all route through it |
| **Global search** (§ 11) | ✔ | ✔ | ✔ | ✔ | `search` registry (planned); `visible_to()` on every model; nav registry for the palette | **1** (core seam) · 3 (module) |
| **Knowledge base** (§ 8) | ✔ | ✔ | ✔ | ✔ | Introspectable nav, permission, flag, error-code registries; soft-disable signal; host classification | **2** — the "ships with its help page" rule is cheapest from the start |
| **Billing, ledger & payments** (§ 2) | ✔ | ◐ | ✔ | ✔ | Money + numbering + calendar primitives; outbox; credential store; job registry with queues; advisory-lock helper; extension points `billing.*`; approvals | **2** — largest; start with ledger + guard, then documents, then payments |
| **Tenancy & white-label** (§ 10) | ◐ | ✔ | ◐ | ✔ | **D3 decision**; `registry.scopes`; org-status gate in auth; host resolver middleware; dynamic CORS hook; branding data | **Decide first**, build when the first multi-tenant product starts |
| **Templated documents** (§ 4) | ✔ | ✔ | ✔ | ◐ | PDF primitive; numbering; storage; extension points `documents.kinds`, `documents.merge_fields`; approvals chains | 3 |
| **Automation engine** (§ 7) | ✔ | ✔ | ✔ | ✔ | Event bus + catalog; job registry schedules; run ledger; machine abilities; outbound guard | 3 |
| **Alert rules engine** (§ 6) | ✔ | ✔ | ✔ | ✔ | Extension point `alerts.sources`; job registry; notifications; scoping | 3 |
| **Data ingestion / sync** (§ 5) | ✔ | ✔ | ✔ | ◐ | Extension points `ingest.adapters`, `ingest.targets`; credential store; provenance; findings-queue shape | 3 (1 for an integration-heavy product) |
| **Helpdesk** (§ 9) | ◐ | ✔ | ✔ | ✔ | State-machine + calendar primitives; outbox; upload validator; retention engine | 4 |
| **AI assistant** (§ 12) | ◐ | ✔ | ◐ | ✔ | Extension point `ai.tools`; credential store; read-only DB role; scrubber | 4 |
| **Feedback widget** (§ 13) | ◐ | ◐ | ◐ | ✔ | UI slot; scrubber; nav registry; outbound guard | 4 |
| **Agent connector switches** (§ 15.3) | ◐ | ✔ | ◐ | ✔ | Capability/kill-switch registry; machine principal flag | When a connector ships |

✔ = typically needed · ◐ = sometimes. Priority is relative among modules; platform sequencing lives in
[`../planning/BUILD_ORDER.md`](../planning/BUILD_ORDER.md).

---

## 17. ⚠️ Conflicts with existing docs

| # | Doc & section | What it says | What the research shows | Fix |
|---|---|---|---|---|
| 1 | [`DATA_MODEL.md`](DATA_MODEL.md) § 1 **D3** | Recommends *no* organisation model in core, relying on `visible_to()` to make a later retrofit "one method per model" | A measured retrofit touched ~258 signatures, and the core schema could not be created without a product table until the tenant table moved into core. `visible_to()` covers **reads** only — writes, counters, filter dropdowns, search and AI tools all needed changes too | Re-open D3 with the evidence in § 10.1; whichever way it goes, record the retrofit cost in the ADR and add write-path scoping (`writable_by`) to § 5 |
| 2 | [`DATA_MODEL.md`](DATA_MODEL.md) § 5 | "`visible_to()` … fails closed" (reads) | Reads scoped but writes unscoped was a real cross-tenant takeover path | Add `writable_by(user)` / `assert_writable()` for update and delete, and a "`None` never means all" rule |
| 3 | [`DATA_MODEL.md`](DATA_MODEL.md) § 3 "Phase 2+" | Lists `SearchableEntity` as a core entity | The core needs the `search` *registry*; DB-configurable entity rows are the optional module's table (§ 11) | Move `SearchableEntity` to the search module (`search_entity`), keep the registry in core |
| 4 | [`RBAC_DESIGN.md`](RBAC_DESIGN.md) "The superuser question" | "One `is_superuser` flag that bypasses every check" | Separation of duties (proposer ≠ approver) is not a permission check; a superuser self-approving defeats four-eyes | State that the superuser bypass covers permission checks only, never maker-checker; superuser self-approval is break-glass (§ 3.1) |
| 5 | [`../planning/CORE_ARCHITECTURE_PLAN.md`](../planning/CORE_ARCHITECTURE_PLAN.md) § 2 | Eight named registries; "a registry holds a key, a label, and a callable — never a plugin's … schema" | Modules extended by other plugins (billing, approvals, alerts, documents, ingest, automation, AI) need extension points **in core** or contributors must import the engine plugin, violating § 4. Alert sources and automation actions also carry a declarative JSON Schema for their config | Add a generic namespaced contribution registry (§ 1) to the list, and clarify that a declarative JSON Schema *as data* is permitted (a DB schema or serializer class is not) |
| 6 | [`API_DESIGN.md`](API_DESIGN.md) § Machine callers | "A machine caller is a principal with permissions, checked by the same RBAC layer" | Connector switches (§ 15.3) and automation API triggers (§ 7) key on **abilities** of a machine principal distinct from user permissions | Owned by [`API_PLATFORM.md`](API_PLATFORM.md), which records the full contradiction; noted here because §§ 7 and 15.3 assume abilities |

---

## Pending decisions (for the repository owner)

1. **D3 — tenancy in core** (§ 10.1). The single most expensive open question on this page.
2. **Extension points: one generic contribution registry, or one named registry per module?** (§ 1).
   Recommendation: generic, so core does not grow a registry for every optional module.
3. **Billing tax point default** — `TOP_UP` or `CONSUMPTION` (§ 2.6). Depends on the first
   jurisdiction adapter; the module must support both.
4. **Prepaid close tail** — `RECORD` (under-charge, never over-charge) or `COLLECT` (§ 2.7).
5. **Hours per month** — fixed 730 for predictable pricing, or calendar-exact per month (§ 2.1). Fixed
   is simpler to quote; calendar-exact matches wall-clock bills. Choose before the first tariff.
6. **Metering storage** — plain PostgreSQL with declarative partitioning (recommended) or a time-series
   extension. Note: compressed time-series chunks do not support row locks, which forces advisory
   locks everywhere (§ 2.7).
7. **Search entity configuration** — registry-only (simpler, safer) or DB-configurable rows (§ 11).
8. **Break-glass self-approval** — allowed at all in production, or build-time disabled (§ 3.1).
9. **Which module is built first** after the platform phases (§ 16 suggests approvals + the search
   seam).

---

## Doc accuracy

> Written 2026-09-29 from research across several production codebases. Nothing here is implemented; verify
> against the code before relying on any section.
