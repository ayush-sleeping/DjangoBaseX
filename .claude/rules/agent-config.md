---
paths:
  - ".claude/**"
  - "AGENTS.md"
  - "CLAUDE.md"
  - "GEMINI.md"
  - ".worktreeinclude"
---

# Editing agent configuration — read before editing

This file holds no rules (ADR-0006, ADR-0007). It tells you where they are.

- `documentation/core/AGENT_TOOLING.md`: what every file under `.claude/` does, and how to add one.
- `documentation/adr/0006-one-agent-contract.md` and `0007-claude-code-harness.md`: rules live only in
  `AGENTS.md`. `.claude/` holds enforcement, procedures and pointers.
- `.claude/hooks/agent_guard.py` reads the protected-file list and the commit types from `AGENTS.md`. If you
  change either section's format, run `python3 .claude/hooks/test_agent_guard.py`.
- `.claude/agent-memory/` is committed and public (`AGENTS.md` § 1 rules 5, 5a, 6).
