## What and why

<!-- What was wrong or missing, what it cost, and what changed. One short paragraph. -->

**BUILD_ORDER / TECH_DEBT item:**

## How it is proven

<!-- The test that fails without this change (name it), and the gate commands you ran with their real result.
     "Which line did you remove to prove this red?" -->

## Definition of done

Full table: [`documentation/DEFINITION_OF_DONE.md`](../documentation/DEFINITION_OF_DONE.md). Score every line; write `N/A - reason` rather than leaving one blank.

- [ ] Serves [`PURPOSE.md`](../documentation/PURPOSE.md); no product identity, client or other codebase named
- [ ] No [`INVARIANTS.md`](../documentation/INVARIANTS.md) rule broken; architecture tests green
- [ ] Bug fix: failing test first; the done-when of the `BUILD_ORDER.md` task met literally
- [ ] Ruff, ESLint, `manage.py check`, `makemigrations --check` and the test suites green (`AGENTS.md` section 2)
- [ ] Permission-denied test for every new endpoint; no secret or `.env` value in code, docs or output
- [ ] `DAILY_CHANGES.md` entry; `CHANGELOG.md` / `UPGRADING.md` if an env key, setting default or required step changed; new docs indexed
- [ ] Dependents checked (`rg -l`); no second way of doing something that already exists

## Bug classes checked ([`BUG_CLASSES.md`](../documentation/system-design/BUG_CLASSES.md))

Tick the area rows your diff touches and name the `BC-` ids you reviewed, using the review map at the top of that file.

- [ ] Endpoints, roles, sign-in, rate limits (BC-01 to BC-14, BC-17)
- [ ] Secrets, logging, templates, outbound HTTP, uploads (BC-14 to BC-23)
- [ ] Money, numbering, quotas (BC-24 to BC-30)
- [ ] Jobs, caches, settings, flags, migrations, seeders (BC-31 to BC-41)
- [ ] Frontend data display, integrations, tests and guards (BC-42 to BC-45)
- [ ] None apply: say why

Ids reviewed:

## Riskiest decision for review

