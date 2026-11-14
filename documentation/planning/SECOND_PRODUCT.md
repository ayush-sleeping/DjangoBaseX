# Second product — what hurt (BUILD_ORDER 10.1)

> **Status:** In progress — started 2026-11-14 · owner: the repository owner · the product is
> [`examples/plugins/enquiries`](../../examples/plugins/enquiries/README.md)

**Why this exists.** "Nothing proves a core is reusable until something else is built on it. Whatever hurts
the second time is the design flaw" (BUILD_ORDER 10.1). This page is the log of what hurt, so each pain
becomes a fix, a debt row or a trap instead of a memory.

## The product

An **enquiries** pipeline (a mini-CRM), chosen by the owner because it exercises the primitives with the
most "add when the first consumer needs it" debt rows. Built as a plugin in `examples/plugins/` beside
`notes`, so it proves the parallel-teams seam and CI installs it on every push.

- Each enquiry gets a document number (`ENQ-YYYY-00001`, yearly reset, gapless).
- Status is a registered state machine: new → contacted → quoted → won; any open state → lost;
  lost → new reopens. Losing and reopening need a reason. Every move lands in state history.
- An estimated value held in the core money type (quantised to the currency's scale).
- Owner-scoped (`visible_to`), soft delete with the recycle bin, provenance, audit verbs, five
  permission codes (view, create, update, transition, delete), a nav entry and a frontend page.

**Not yet proven:** the clone-and-re-origin path (`git merge core/main` into a separate repo), notifications,
webhooks, import/export and bulk actions on a plugin resource. 10.1 stays ◐ until a product outside this
repo merges a core release.

## Findings

| # | What hurt | Root cause | Outcome |
|---|---|---|---|
| **F1** | The plugin could not use numbering, the state machine or money at all | `core.sdk` (the only module a plugin may import) stopped at 9.3; 9.4 shipped without SDK exports | **Fixed:** SDK 1.2 exports `NumberingSeries`, `peek_number`, `reserve_number`, `StateMachine`, `transition`, `allowed_transitions`, the state-machine errors, `Money`, `MoneyError`, `to_money`, `money_fields`, `money_property` |
| **F2** | A gap-tolerant series failed every API test with `database table is locked` | `reserve()` for a gap-tolerant series writes on its own connection; under `pytest.mark.django_db` the in-memory SQLite test DB is write-locked by the test's own transaction. (First logged as "no core test covers it": wrong. `tests/test_numbering.py` covers it through a `real_db` fixture with no wrapping transaction) | The series is gapless, which suits it. **TRAPS row**; DB-136 closed as a test-environment limit, not a code defect |
| **F3** | Installing the plugin made the core contract test fail (`openapi.json` stale) | drf-spectacular names an enum after its field; a second `status` field renamed core's `StatusEnum` to `InvitationStatusEnum` | **Fixed:** `ENUM_NAME_OVERRIDES` pins `StatusEnum` and `ScopeEnum` in `SPECTACULAR_SETTINGS`. TRAPS row added |
| **F4** | Installing a second plugin broke the first plugin's test | `test_notes.py` asserted the recycle bin lists exactly `["notes.note"]`; the bin lists every registered type | **Fixed:** the assertion is now membership. A plugin test must not assert on a global registry's full contents |
| **F5** | The page re-derives which moves need a reason | The API exposes `allowed_transitions` but not the machine's `reason_required` pairs | **Fixed:** `transition_options()` (SDK 1.3) returns each move with `needs_reason`; the API carries `transitions` and the page reads it (DB-137 closed) |
| **F6** | No text-input dialog: `window.prompt` is lint-banned and `@/core/components` has only `confirm()`/`toast()` | Design-system gap | **Fixed:** `promptText()` + `PromptHost` beside `confirm()`; the page asks for a reason with it (DB-138 closed) |
| **F7** | The estimated value had to be required | `money_fields()` takes options for the amount only; the currency column cannot be made optional | **Fixed:** `money_fields(optional=True)`, `money_pair_check()` (both or neither) and `money_property()` returning None (SDK 1.3, DB-139 closed). The enquiry value stays required by choice |

## What did not hurt

Scoping, soft delete, the recycle bin, provenance, audit verbs, permissions, nav and the route mount all
worked from `core.sdk` with the notes plugin as the copy. The model-to-page path took one file per layer.
