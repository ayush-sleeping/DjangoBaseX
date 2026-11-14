"""
Nothing bypasses notify() (NOTIFICATIONS_AND_ALERTING.md § 0 rule 5, § 3): a direct transport call
skips the platform switch, the matrix, preferences and the non-production guard. Also: a notify()
call names a purpose and a subject, never a destination (§ 1).
"""

import ast
from pathlib import Path

from tests.architecture.sources import BACKEND

ALLOWED_DIRS = ("core/notifications/", "core/mail/")
BANNED_NAMES = {
    "send_mail",
    "send_mass_mail",
    "mail_admins",
    "mail_managers",
    "EmailMessage",
    "EmailMultiAlternatives",
}
BANNED_MODULES = ("core.notifications.channels", "core.mail.render")
DESTINATION_KEYWORDS = {"to", "email", "channel", "url", "address", "target", "recipient_email"}


def scanned():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        parts = set(path.relative_to(BACKEND).parts)
        if parts & {".venv", "__pycache__", "node_modules", "migrations", "tests"}:
            continue
        if path.name.startswith("test_") or path.name == "conftest.py":
            continue
        yield rel, ast.parse(path.read_text(), filename=rel)


def test_no_transport_is_used_outside_the_notification_layer():
    offences = []
    for rel, tree in scanned():
        if rel.startswith(ALLOWED_DIRS):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {a.name for a in node.names}
                if node.module in BANNED_MODULES or (
                    node.module == "core.mail" and "render" in names
                ):
                    offences.append(f"{rel}:{node.lineno} imports {node.module}")
                if (
                    node.module
                    and node.module.startswith("django.core.mail")
                    and names & BANNED_NAMES
                ):
                    offences.append(f"{rel}:{node.lineno} imports {sorted(names & BANNED_NAMES)}")
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name in BANNED_NAMES:
                    offences.append(f"{rel}:{node.lineno} calls {name}()")
    assert not offences, "call notify() instead:\n  " + "\n  ".join(offences)


def test_notify_calls_carry_no_destination():
    seen, offences = 0, []
    for rel, tree in scanned():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "notify":
                seen += 1
                bad = {k.arg for k in node.keywords if k.arg in DESTINATION_KEYWORDS}
                if bad:
                    offences.append(f"{rel}:{node.lineno} passes {sorted(bad)}")
                for arg in node.args[1:]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        offences.append(f"{rel}:{node.lineno} passes a string literal")
    assert seen >= 4, f"the scan found {seen} notify() calls: it is looking in the wrong place"
    assert not offences, "\n  ".join(offences)


def test_every_email_has_three_parts():
    subjects = [
        p
        for root in (BACKEND / "core", BACKEND / "users", BACKEND / "rbac", BACKEND / "project")
        for p in root.rglob("*.subject.txt")
    ]
    assert subjects, "no email templates found: the scan is testing nothing"
    for subject in subjects:
        base = Path(str(subject)[: -len(".subject.txt")])
        assert base.with_suffix(".txt").exists() and base.with_suffix(".html").exists(), subject
