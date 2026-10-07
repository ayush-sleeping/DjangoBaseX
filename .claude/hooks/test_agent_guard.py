#!/usr/bin/env python3
"""Self-test for agent_guard.py. Run: python3 .claude/hooks/test_agent_guard.py

Standard library only, so it runs before the backend test stack exists (BUILD_ORDER 2.1).
Every refusal is proven by a case that triggers it and a neighbouring case that must pass.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import agent_guard as guard

ROOT = guard.PROJECT_DIR


def bash(command: str) -> str | None:
    result = guard.evaluate({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)})
    return result["hookSpecificOutput"]["permissionDecision"] if result else None


def edit(path: str, tool: str = "Edit") -> str | None:
    result = guard.evaluate({"tool_name": tool, "tool_input": {"file_path": path}, "cwd": str(ROOT)})
    return result["hookSpecificOutput"]["permissionDecision"] if result else None


class ContractParsing(unittest.TestCase):
    def test_protected_list_is_read_from_agents_md(self):
        protected = guard.protected_files()
        self.assertIn("AGENTS.md", protected)
        self.assertIn("backend/config/settings.py", protected)
        self.assertIn("frontend/package.json", protected)

    def test_commit_types_are_read_from_agents_md(self):
        self.assertIn("feat", guard.commit_types())
        self.assertIn("docs", guard.commit_types())


class FileTools(unittest.TestCase):
    def test_protected_files_ask(self):
        for path in ("AGENTS.md", "backend/config/settings.py", ".gitignore", "frontend/tsconfig.json"):
            self.assertEqual(edit(str(ROOT / path)), "ask", path)
        self.assertEqual(edit(str(ROOT / "CLAUDE.md"), tool="Write"), "ask")

    def test_bare_names_match_at_any_depth(self):
        self.assertEqual(edit(str(ROOT / "backend/.env")), "ask")
        self.assertEqual(edit(str(ROOT / "frontend/CLAUDE.md")), "ask")

    def test_generated_frontend_agents_md_is_refused(self):
        self.assertEqual(edit(str(ROOT / "frontend/AGENTS.md")), "deny")

    def test_ordinary_files_pass(self):
        self.assertIsNone(edit(str(ROOT / "backend/core/views.py")))
        self.assertIsNone(edit(str(ROOT / "documentation/DAILY_CHANGES.md")))
        self.assertIsNone(edit("/tmp/elsewhere/AGENTS.md"))


class CommitMessages(unittest.TestCase):
    def test_conventional_messages_pass(self):
        self.assertIsNone(bash('git commit -m "feat(users): add the custom user model"'))
        self.assertIsNone(bash('git commit -m "docs: correct the changelog note"'))
        self.assertIsNone(bash('git add AGENTS.md && git commit -m "docs(agents): trim the contract"'))

    def test_heredoc_messages_are_checked(self):
        ok = "git commit -F - <<'EOF'\ndocs: add a thing\n\nBody text.\nEOF"
        bad = "git commit -F - <<'EOF'\ndocs: add a thing\n\nCo-Authored-By: Claude <noreply@anthropic.com>\nEOF"
        self.assertIsNone(bash(ok))
        self.assertEqual(bash(bad), "deny")

    def test_cat_heredoc_inside_m_is_checked(self):
        bad = 'git commit -m "$(cat <<\'EOF\'\nfix: x\n\nGenerated with [Claude Code](https://claude.com/claude-code)\nEOF\n)"'
        self.assertEqual(bash(bad), "deny")

    def test_format_violations_are_refused(self):
        self.assertEqual(bash('git commit -m "Added stuff"'), "deny")
        self.assertEqual(bash('git commit -m "feature: add x"'), "deny")
        self.assertEqual(bash('git commit -m "feat(Users): add x"'), "deny")
        self.assertEqual(bash('git commit -m "feat: add x."'), "deny")
        self.assertEqual(bash('git commit -m "feat: ' + "x" * 80 + '"'), "deny")
        self.assertEqual(bash('git commit -m "feat: add x" -m "🤖 made by a bot"'), "deny")

    def test_mentioning_tools_in_a_message_is_fine(self):
        self.assertIsNone(bash('git commit -m "docs(agents): follow the official docs" -m "See code.claude.com/docs."'))

    def test_commit_without_message_flag_passes(self):
        self.assertIsNone(bash("git commit --amend --no-edit"))


class HistoryRewriting(unittest.TestCase):
    def test_refused(self):
        for command in (
            "git push --force origin main",
            "git push -f",
            "git push --force-with-lease",
            "git push origin +main",
            "git push origin --delete old",
            "git push origin :old",
            "git reset --hard HEAD~1",
            "git branch -D old",
            "git branch -d old",
            'git commit --no-verify -m "fix: x"',
            'git commit -n -m "fix: x"',
            "git filter-branch --tree-filter x",
            "cd backend && git reset --hard",
            "git status\ngit push --force",
        ):
            self.assertEqual(bash(command), "deny", command)

    def test_ordinary_git_passes(self):
        for command in ("git push origin main", "git status", "git reset HEAD file", "git branch feature/x", "git log -5"):
            self.assertIsNone(bash(command), command)


class BashWritesAndEnv(unittest.TestCase):
    def test_writing_a_protected_file_asks(self):
        for command in ("sed -i '' 's/a/b/' AGENTS.md", "echo x >> .gitignore", "cat x | tee backend/pyproject.toml", "rm CLAUDE.md"):
            self.assertEqual(bash(command), "ask", command)

    def test_reading_protected_files_passes(self):
        self.assertIsNone(bash("cat AGENTS.md"))
        self.assertIsNone(bash("sed -n 1,20p backend/config/settings.py"))

    def test_printing_env_values_is_refused(self):
        self.assertEqual(bash("cat backend/.env"), "deny")
        self.assertEqual(bash("head -5 frontend/.env.local"), "deny")

    def test_env_example_and_key_names_pass(self):
        self.assertIsNone(bash("cat backend/.env.example"))
        self.assertIsNone(bash("grep -oE '^[A-Z_]+=' backend/.env"))


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    unittest.main(verbosity=1)
