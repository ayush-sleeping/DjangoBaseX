# Second product — what hurt (BUILD_ORDER 10.1)

> **Status:** Done — 2026-11-14 · owner: the repository owner · the product is
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

**Not yet proven:** notifications, webhooks, import/export and bulk actions on a plugin resource. The merge path
is proven locally (below), with one finding (F8), now fixed in NEW_PROJECT.md.

## Findings

| # | What hurt | Root cause | Outcome |
|---|---|---|---|
| **F1** | The plugin could not use numbering, the state machine or money at all | `core.sdk` (the only module a plugin may import) stopped at 9.3; 9.4 shipped without SDK exports | **Fixed:** SDK 1.2 exports `NumberingSeries`, `peek_number`, `reserve_number`, `StateMachine`, `transition`, `allowed_transitions`, the state-machine errors, `Money`, `MoneyError`, `to_money`, `money_fields`, `money_property` |
| **F2** | A gap-tolerant series failed every API test with `database table is locked` | `reserve()` for a gap-tolerant series writes on its own connection; under `pytest.mark.django_db` the in-memory SQLite test DB is write-locked by the test's own transaction. (First logged as "no core test covers it": wrong. `tests/test_numbering.py` covers it through a `real_db` fixture with no wrapping transaction) | The series is gapless, which suits it. **TRAPS row**; DB-136 closed as a test-environment limit, not a code defect |
| **F3** | Installing the plugin made the core contract test fail (`openapi.json` stale) | drf-spectacular names an enum after its field; a second `status` field renamed core's `StatusEnum` to `InvitationStatusEnum` | **Fixed:** `ENUM_NAME_OVERRIDES` pins `StatusEnum` and `ScopeEnum` in `SPECTACULAR_SETTINGS`. TRAPS row added |
| **F4** | Installing a second plugin broke the first plugin's test | `test_notes.py` asserted the recycle bin lists exactly `["notes.note"]`; the bin lists every registered type | **Fixed:** the assertion is now membership. A plugin test must not assert on a global registry's full contents |
| **F5** | The page re-derives which moves need a reason | The API exposes `allowed_transitions` but not the machine's `reason_required` pairs | **Fixed:** `transition_options()` (SDK 1.3) returns each move with `needs_reason`; the API carries `transitions` and the page reads it (DB-137 closed) |
| **F6** | No text-input dialog: `window.prompt` is lint-banned and `@/core/components` has only `confirm()`/`toast()` | Design-system gap | **Fixed:** `promptText()` + `PromptHost` beside `confirm()`; the page asks for a reason with it (DB-138 closed) |
| **F8** | Every core update conflicts in the product's `DAILY_CHANGES.md` | NEW_PROJECT.md step 3 tells a product to empty the file, and the core prepends an entry to it in every change: both sides edit the same lines forever | **Fixed (owner chose A):** NEW_PROJECT.md step 3 now says to leave the core's `DAILY_CHANGES.md` and `VERSION_SUMMARY.md` alone and keep a product log in a new file |
| **F7** | The estimated value had to be required | `money_fields()` takes options for the amount only; the currency column cannot be made optional | **Fixed:** `money_fields(optional=True)`, `money_pair_check()` (both or neither) and `money_property()` returning None (SDK 1.3, DB-139 closed). The enquiry value stays required by choice |

## The merge path (proven locally, 2026-11-14)

A product was cloned from the core at `d7383c5` (before 10.1), re-originated (`origin` → `core`), and given
the NEW_PROJECT.md checklist: package names in `pyproject.toml`/`uv.lock` and `package.json`/`package-lock.json`,
the README title, the `AGENTS.md` banner, emptied `DAILY_CHANGES.md` and `VERSION_SUMMARY.md`, and its own code
in `backend/project/`. Then `git fetch core && git merge core/main` brought in the three 10.1 commits.

- **One conflict:** `documentation/DAILY_CHANGES.md` (F8). Everything else merged on its own, and the product's
  renames survived.
- After resolving it: `uv lock --check` passed, and the product's pytest ran 2351 passed / 11 skipped (SQLite).
- Done in a throwaway clone in a scratch directory, not a published repository: it proves the git mechanics,
  not a second team's workflow.

**F8 options:** (A) the product leaves the core's `DAILY_CHANGES.md` alone and keeps its own log in a new file
its `AGENTS.md` points at: no conflict ever, no core change. *(Recommended.)* (B) move the core's log to a
core-owned path so the product owns `DAILY_CHANGES.md`: touches `AGENTS.md` (protected) and every reference.
(C) keep emptying it and document `git checkout --ours` on every merge. **The owner chose A (2026-11-14).**

## What did not hurt

Scoping, soft delete, the recycle bin, provenance, audit verbs, permissions, nav and the route mount all
worked from `core.sdk` with the notes plugin as the copy. The model-to-page path took one file per layer.
