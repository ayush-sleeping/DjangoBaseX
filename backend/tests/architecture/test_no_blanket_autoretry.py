"""
No blanket auto-retry (JOBS_AND_INTEGRATIONS.md § 10): `autoretry_for=(Exception,)` retries a
validation error five times. Classify with core.jobs.retry.RetryPolicy.is_transient instead.
"""

import ast

from tests.architecture.sources import iter_python_sources, parse, rel

BLANKET = frozenset({"Exception", "BaseException"})


def _names(node: ast.AST) -> set[str]:
    elements = node.elts if isinstance(node, (ast.Tuple, ast.List, ast.Set)) else [node]
    out = set()
    for element in elements:
        if isinstance(element, ast.Name):
            out.add(element.id)
        elif isinstance(element, ast.Attribute):
            out.add(element.attr)
    return out


def blanket_autoretries(tree: ast.AST) -> list[int]:
    return [
        kw.value.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "autoretry_for" and _names(kw.value) & BLANKET
    ]


def test_no_blanket_autoretry():
    scanned, found = 0, []
    for path in iter_python_sources():
        scanned += 1
        found += [f"{rel(path)}:{line}" for line in blanket_autoretries(parse(path))]
    assert scanned, "scanned no files: the scan is looking in the wrong place"
    assert found == [], "classify failures instead (RetryPolicy.is_transient):\n" + "\n".join(found)


def test_the_scan_sees_each_form():
    source = (
        "app.task(autoretry_for=(Exception,))\n"
        "shared_task(autoretry_for=[ValueError, builtins.BaseException])\n"
        "app.task(autoretry_for=Exception)\n"
        "app.task(autoretry_for=(ConnectionError,))\n"
    )
    assert blanket_autoretries(ast.parse(source)) == [1, 2, 3]
