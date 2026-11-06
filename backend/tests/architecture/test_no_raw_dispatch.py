"""
No raw .delay() / .apply_async() / send_task() outside core/jobs/ (JOBS_AND_INTEGRATIONS.md § 4).

core.jobs.enqueue() is the one place payloads are checked to be primitive and the publish waits for
the commit. A raw call anywhere else skips both, so without this test enqueue() is optional.
AST, not grep: a comment or a string mentioning `.delay(` is not a call.
"""

import ast

from tests.architecture.sources import BACKEND, iter_python_sources, rel

RAW_DISPATCH = frozenset({"delay", "apply_async", "send_task"})
ALLOWED_DIR = BACKEND / "core" / "jobs"


def raw_dispatches(source: str) -> list[tuple[int, str]]:
    return [
        (node.lineno, node.func.attr)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in RAW_DISPATCH
    ]


def test_no_raw_dispatch_outside_core_jobs():
    scanned, offenders = 0, []
    for path in iter_python_sources():
        if ALLOWED_DIR in path.parents:
            continue
        scanned += 1
        for line, attr in raw_dispatches(path.read_text(encoding="utf-8")):
            offenders.append(f"{rel(path)}:{line} .{attr}()")
    assert scanned, "scanned no files: the scan is looking in the wrong place"
    assert offenders == [], "use core.jobs.enqueue(name, **ids):\n" + "\n".join(offenders)


def test_the_scan_sees_each_form():
    source = "task.delay(1)\ntask.apply_async(kwargs={})\napp.send_task('x')\n# x.delay(2)\n"
    assert [attr for _, attr in raw_dispatches(source)] == ["delay", "apply_async", "send_task"]
