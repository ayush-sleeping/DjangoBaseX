---
name: changelog
description: Write the documentation/DAILY_CHANGES.md entry for the current task, and update the other registers the change requires. Use at the end of every task, in the same change as the code (AGENTS.md § 1 rule 8).
---

# Changelog entry

The rule and the template are in `documentation/DAILY_CHANGES.md` § Format. This is the procedure.

1. **Read the top of `documentation/DAILY_CHANGES.md`.** Entries run newest first. If today's `## YYYY-MM-DD`
   heading already exists, add a `###` entry under it. Otherwise insert a new date heading above the latest
   one, followed by a `---` separator.
2. **Fill every field with facts:**
   - **What:** one or two lines.
   - **Why:** the reason. For a fix, also say how the problem showed up.
   - **Files:** every changed path. Cross-check it against `git status --porcelain`.
   - **Verification:** the commands that ran and their real results, including failures and skipped checks.
     Copy these from the `/verify` report. Never write them from memory.
   - **Notes / Still open:** anything the next person would otherwise have to rediscover.
3. **Update the other registers this change needs** (`AGENTS.md` § 4, "Recorded in"):
   - a new subsystem: a `documentation/core/` doc and a row in `documentation/INDEX.md`
   - a new convention: the owning `documentation/system-design/` doc
   - a settled decision: the `/adr` skill
   - a defect you found but are not fixing: a ranked row in `documentation/planning/TECH_DEBT.md`
   - a shippable feature: `documentation/VERSION_SUMMARY.md`
   - something moving from planned to real: `documentation/planning/ROADMAP.md` and the task's ⬜ in
     `BUILD_ORDER.md`
4. **Public-repo check** (`AGENTS.md` § 1 rules 5, 5a, 6): no credential values, no `.env` values, no internal
   URLs, and no name of any other codebase, product or client.
