"""
Two source scans over the § 18 sources (DATA_LIFECYCLE.md § 4.2, § 4.5):

* only core.audit.record() inserts into core_activity_log — everything else would bypass the
  scrubbing, the savepoint and the never-raises guarantee;
* every action literal passed to record()/log_activity() is registered, and the scan FAILS when it
  finds zero literals (a completeness test that passes on an empty universe proves nothing).
"""

import ast

from core.registry import registry
from tests.architecture.sources import iter_python_sources, rel

WRITER = "core/audit.py"
INSERTS = {"create", "bulk_create", "get_or_create", "update_or_create"}


def _parse(path):
    return ast.parse(path.read_text(), filename=str(path))


def table_writes(tree: ast.AST) -> list[int]:
    """Lines that construct ActivityLog or call ActivityLog.objects.<insert>()."""
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "ActivityLog":
            lines.append(node.lineno)
        if isinstance(func, ast.Attribute) and func.attr in INSERTS:
            base = func.value
            if isinstance(base, ast.Attribute) and base.attr == "objects":
                owner = base.value
                if isinstance(owner, ast.Name) and owner.id == "ActivityLog":
                    lines.append(node.lineno)
    return lines


def action_literals(tree: ast.AST) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        first = node.args[0]
        if name in {"record", "log_activity"} and isinstance(first, ast.Constant):
            if isinstance(first.value, str):
                found.append((node.lineno, first.value))
    return found


def test_only_record_writes_the_table():
    offenders = []
    for path in iter_python_sources():
        if rel(path) == f"backend/{WRITER}":
            continue
        offenders += [f"{rel(path)}:{line}" for line in table_writes(_parse(path))]
    assert offenders == [], f"inserts into core_activity_log outside record(): {offenders}"


def test_positive_control_a_stray_insert_is_caught():
    source = (
        "from core.models import ActivityLog\n"
        "ActivityLog.objects.create(action='x')\n"
        "ActivityLog(action='y')\n"
    )
    assert len(table_writes(ast.parse(source))) == 2


def test_every_audit_action_literal_is_registered_and_the_scan_sees_some():
    literals = [
        (rel(path), line, action)
        for path in iter_python_sources()
        for line, action in action_literals(_parse(path))
    ]
    assert literals, "found zero record()/log_activity() literals: the scan is looking nowhere"
    registered = {a.key for a in registry.audit_actions.actions()}
    missing = sorted({f"{p}:{line} {a}" for p, line, a in literals if a not in registered})
    assert missing == [], (
        f"unregistered audit actions (register them in core/audit_actions.py): {missing}"
    )


def test_positive_control_an_unregistered_literal_is_caught():
    source = "record('crm.deal.invented')\nlog_activity('auth.login')\nrecord(dynamic)\n"
    assert [a for _, a in action_literals(ast.parse(source))] == ["crm.deal.invented", "auth.login"]
