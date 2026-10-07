# ADR-0007: `.claude/` enforces and points at the contract; it never holds rules

**Status:** Accepted
**Date:** 2026-10-07

## Context

[ADR-0006](0006-one-agent-contract.md) makes `AGENTS.md` the only agent contract. Two problems remained:

- **Every rule depended on the agent remembering it.** Claude Code treats `CLAUDE.md` and everything it imports
  as context, not as enforced configuration. The rules that matter most fail silently when they are forgotten:
  "ask before editing a protected file", "no AI attribution in commits", "never force-push" and "never echo
  `.env` values". The official guidance is that hooks and permission rules are the only enforcement layer.
- **The contract was over budget.** It ran to 240 lines, and all of it loaded on every turn. The official
  guidance targets under 200 lines per instruction file, because adherence drops above that. Much of the
  length was procedure (how to commit, how to write a changelog entry) rather than rules.

`ENGINEERING_PRACTICES.md` §§ 39–40 had already specified a guard hook, on-demand skills and an implementer
agent, and left the hooks as owner decision 6. Claude Code's project directory now offers `settings.json`
(permissions, hooks, attribution), `rules/` (optionally scoped by path), `skills/`, `agents/` and
`agent-memory/`. Each of these is a place a second contract could quietly grow.

## Decision

`AGENTS.md` remains the one contract. Under 200 lines, it holds every rule, readable by every agent. `.claude/`
holds three kinds of thing and never a rule:

1. **Enforcement.** `settings.json` sets `attribution` off, allow-lists the § 2 gate commands and denies reading
   real `.env` files. `hooks/agent_guard.py` (PreToolUse) **asks** before any edit to a protected file and
   **refuses** malformed or AI-attributed commit messages, history rewriting (`push --force`, `reset --hard`,
   `--no-verify`, branch deletion, `filter-branch`) and printing `.env` files. The guard reads the protected
   list and the commit types **from `AGENTS.md` itself**, so there is no second list to drift. A self-test proves
   every refusal: `python3 .claude/hooks/test_agent_guard.py`.
2. **Procedures.** Skills (`/verify`, `/changelog`, `/commit`, `/next-task`, `/adr`, `/bug-class-check`,
   `/new-django-app`) give the steps and cite the `AGENTS.md` section or `system-design/` doc that holds the
   rule. `/commit` is user-invoked only.
3. **Pointers.** Path-scoped `rules/*.md` files load when matching files are opened. They name the docs to
   read and copy no rule text. Subagents (`code-reviewer`, `doc-auditor`, `implementer`) carry role
   instructions, and their committed `agent-memory/` holds patterns only.

`GEMINI.md` imports `AGENTS.md`, the same way `CLAUDE.md` does. The hook lives in `.claude/hooks/`, not in the
`scripts/hooks/` that `ENGINEERING_PRACTICES.md` § 39 proposed, because it is Claude Code configuration. A
`commit-msg` git hook for humans remains future work.

## Consequences

- The rules agents forget most are now mechanical in Claude Code. A protected-file edit always reaches the
  user as a prompt, even in auto mode.
- The contract fits its budget, and procedures cost context only when they are used.
- **Enforcement is Claude-only.** Codex, Cursor, Copilot and Gemini get the same rules and no guard. This is
  accepted. The alternative was to duplicate rules per tool, which is the failure ADR-0006 exists to prevent.
- **The guard is coupled to `AGENTS.md`'s formatting.** It parses the `**Protected files…**` paragraph and the
  `Types:` line. The self-test fails if either stops parsing, and the guard falls back to a built-in list rather
  than protecting nothing.
- **Bash parsing is best-effort.** It covers the forms an agent writes, not every shell construct
  (`bash -c "…"`, scripts that run git themselves). It is a guard rail, not a security boundary.
- **`agent-memory/` is committed to a public repository.** Each memory-enabled agent is told what it may never
  record (rules 5, 5a, 6). `doc-auditor` checks it like any other doc.
- **Bulk staging (`git add -A`) and pushes stay allowed by the hook.** The owner chose this on 2026-10-07.
  Rule 1 (ask before commit or push) remains a written rule.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Move backend/frontend-only rules out of `AGENTS.md` into path-scoped `.claude/rules/` | A second contract that only Claude can read. Codex, Cursor and Copilot would lose those rules, and the two sets would drift |
| Hard-block protected-file edits | The owner does legitimately ask for them. A prompt keeps the human in the loop without needing the hook disabled |
| A separate `protected.txt` for the hook (`ENGINEERING_PRACTICES.md` § 39) | It is a second copy of the list. Parsing `AGENTS.md` leaves exactly one |
| Pointer files for every tool (`.github/copilot-instructions.md`, `.cursor/rules/`) | Those tools read `AGENTS.md` natively, so the files would only add surface to drift |
| No harness configuration | It leaves every rule dependent on recall, which is the problem this ADR addresses |
