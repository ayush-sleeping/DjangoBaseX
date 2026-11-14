# DjangoBaseX — definition of done

> **Status:** Accepted — checked 2026-11-14

"It works" is not done. Before reporting a task complete, score it on every line and **show the evidence**.
A line that doesn't apply is `N/A — <reason>`; a line not verified is said plainly, never implied.

| # | Dimension | Done means | Evidence to show |
|---|---|---|---|
| 1 | **Purpose** | Serves [PURPOSE.md](PURPOSE.md): passes "would the next product want this?" — otherwise it belongs in `project/` or a plugin; respects the non-goals and the priority order | one line linking the change to the purpose |
| 2 | **Boilerplate hygiene** | No product identity, client or single-product model in the core; no other codebase, company or client named anywhere; nothing hard-coded that differs per deployment | `rg -i` for names you know must not appear → 0 hits; `test_no_boilerplate_identity.py` green |
| 3 | **Correctness** | Exactly the behaviour asked for; root cause fixed at the owning boundary; siblings searched | the failing → passing test output |
| 4 | **Invariants** | None in [INVARIANTS.md](INVARIANTS.md) broken; the architecture tests that guard them are green | the numbers touched, and why each still holds |
| 5 | **Acceptance** | A `BUILD_ORDER.md` task meets its **Done when** sentence, literally | the test or command that proves each clause |
| 6 | **System design** | The change lives where the fact is decided; no second source of truth; follows an [ARCHITECTURE.md](ARCHITECTURE.md) recipe; an Accepted ADR is not quietly contradicted | file list mapped to layers |
| 7 | **Code quality** | Matches the gold-standard files in [CODE_STANDARDS.md](CODE_STANDARDS.md); no second way of doing a thing; Ruff and ESLint clean | gate output |
| 8 | **UI/UX** | Every state (loading, empty with a next action, error, forbidden), light + dark, responsive, accessible, strings translated ([UI_STANDARDS.md](UI_STANDARDS.md)) | ASCII sketch with real breakpoints + states covered |
| 9 | **Tests** | What [TESTING.md](TESTING.md) requires for this change type: permission-denied test per endpoint, `makemigrations --check` after a model change, failing-first for a bug; fixtures built through the real path | test names + result; new vs pre-existing failures reported separately |
| 10 | **Security** | Route refuses anonymous callers; permission declared and in the catalog; no secret or `.env` value in code, docs or output ([SECURITY.md](SECURITY.md)) | denied test + the pre-push `grep` from AGENTS § 1 |
| 11 | **Performance** | No N+1 (`select_related`/`prefetch_related`), lists paginated, slow work in a registered job | query count or reasoning |
| 12 | **Docs** | `DAILY_CHANGES.md` entry; `VERSION_SUMMARY.md` for a shippable feature; changed `core/` / `system-design/` docs; new doc indexed in `INDEX.md`; ADR if a decision was made; a known defect left behind is a `TECH_DEBT.md` row — all in the same change | file list |
| 13 | **Blast radius** | Dependents checked (`rg -l "<name>"`); files that usually change with yours checked (`git log --format= --name-only -- <file> \| sort \| uniq -c \| sort -rn \| head`) | short summary |
| 14 | **Release-ready** | Conventional commit drafted; staged by explicit path; **owner asked and said yes** before any commit; no AI attribution ([RELEASE.md](RELEASE.md)) | the draft message; approval asked |

**The gate** is AGENTS.md § 2 — run the commands, trust exit codes, not printed text.

Report every claim with a label: *observed* (ran it) · *derived* (read the code) · *inferred* (hypothesis) ·
*unknown*. List what was not verified.
