---
name: next-task
description: Pick up the next unfinished task from documentation/planning/BUILD_ORDER.md and plan it against its acceptance criteria. Use when handed this project with no specific task, or when asked "what's next".
allowed-tools: Bash(grep *)
---

# Next task

`AGENTS.md` § 0: with no specific task, start at the lowest-numbered unfinished item in `BUILD_ORDER.md`.

## Open tasks, in order

!`grep -nE "^### .*⬜" documentation/planning/BUILD_ORDER.md | head -8`

## Procedure

1. **Take the first line above** and read that task's whole section in `documentation/planning/BUILD_ORDER.md`.
   It contains the acceptance criteria and the docs it depends on.
2. **If it is marked 🚧 DECISION, stop.** It is a question for the repository owner, not work for you. Present
   the options and the recommendation from the linked doc, then ask. Do not answer it by starting to code.
3. **Check that its prerequisites are real.** Planning docs are intent, not current state (`AGENTS.md` § 6), so
   confirm each prerequisite in the code. Check `documentation/ADR.md` for Accepted decisions the task must
   respect.
4. **Read the Start Here doc** for the area. `documentation/INDEX.md` maps tasks to docs.
5. **Plan before editing.** List the files you will touch, the acceptance criteria and how each will be proven,
   which § 2 checks apply, and which registers the change updates (`/changelog`). For a change that is large
   or crosses apps, share the plan before you write code.
6. **When done**, run `/verify` and `/changelog`, and mark the task ✅ in `BUILD_ORDER.md` only once every
   acceptance criterion is proven. Then ask before committing.
