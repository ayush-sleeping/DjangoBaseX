---
name: commit
description: Commit (and, only if asked, push) the current work after the user has approved it. Runs the pre-push checks from AGENTS.md § 1 and writes a § 4 conventional message.
disable-model-invocation: true
argument-hint: "[push]"
allowed-tools: Bash(git status *) Bash(git diff *) Bash(git log *) Bash(git config user.email)
---

# Commit

Only the user starts this skill. Invoking it is their approval to commit (`AGENTS.md` § 1 rule 1). Push only
if `$ARGUMENTS` contains `push` or the user said so in this conversation.

## State

- Branch: !`git branch --show-current`
- Author email: !`git config user.email`
- Changes: !`git status --porcelain`
- Recent subjects, to match their style: !`git log --format=%s -8`

## Procedure

1. **Check the gate ran.** If there is no `/verify` report for this work in the conversation, run `/verify`
   first. Do not commit over a red check without the user's explicit say-so.
2. **Check the changelog.** `documentation/DAILY_CHANGES.md` must have this task's entry (rule 8). If it is
   missing, write it with `/changelog`.
3. **Stage explicit paths.** Review each path in the list above. Never stage the files in rule 7: `.env`,
   `.env.local`, `db.sqlite3`, `.venv/`, `node_modules/`, `__pycache__/`, `.next/`, `.ruff_cache/`,
   `tsconfig.tsbuildinfo`, `.claude/settings.local.json`.
4. **Scan what is staged:**
   - `git diff --cached | grep -iE "secret|password|token|api[_-]?key"`. Read every hit. Prose and obviously
     fake placeholders are fine. A real value stops the commit.
   - Rule 5a: confirm that no name of another codebase, product or client appears, including any name you
     know from this session or from memory.
5. **Write the message** (`AGENTS.md` § 4):
   - The subject is `<type>(<scope>): <description>`: imperative, lower-case scope, 72 characters or fewer,
     no trailing period.
   - Leave a blank line after the subject. The body says *what* changed and *why*. Do not narrate how the
     work was done.
   - No AI attribution: no `Co-Authored-By` naming a tool, and no "Generated with" line.
   - Use `git commit -F - <<'EOF' … EOF` for multi-line messages.

   The guard hook enforces the format and the attribution rule, so a refusal means the message is wrong.
   Fix the message and run the commit again.
6. **Push** only if asked: `git push origin <branch>`. Never force-push. The hook refuses it, and the user
   runs it themselves.
7. **Report** the commit hash and subject, what was pushed and where, and confirm the tree is clean
   (`git status -sb`).
