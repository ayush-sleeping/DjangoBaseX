"""
No hand-rolled upstream status mapping (JOBS_AND_INTEGRATIONS.md § 20): `status_code in (401,
403)` or `status_code == 401` outside core/providers/ and */adapters/ is the start of a tenth copy
that disagrees with the other nine. Use core.providers.errors.raise_for_upstream().
"""

import ast

from tests.architecture.sources import BACKEND, iter_python_sources, parse, rel

AUTH_STATUSES = frozenset({401, 403})
ALLOWED_DIRS = (BACKEND / "core" / "providers",)


def _constants(node: ast.AST) -> set:
    if isinstance(node, ast.Constant):
        return {node.value}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return {e.value for e in node.elts if isinstance(e, ast.Constant)}
    return set()


def hand_rolled(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        sides = [node.left, *node.comparators]
        names_status = any(isinstance(s, ast.Attribute) and s.attr == "status_code" for s in sides)
        if names_status and any(_constants(s) & AUTH_STATUSES for s in sides):
            lines.append(node.lineno)
    return lines


def test_no_hand_rolled_status_mapping():
    scanned, offenders = 0, []
    for path in iter_python_sources():
        if any(allowed in path.parents for allowed in ALLOWED_DIRS) or "adapters" in path.parts:
            continue
        scanned += 1
        offenders += [f"{rel(path)}:{line}" for line in hand_rolled(parse(path))]
    assert scanned, "scanned no files: the scan is looking in the wrong place"
    assert offenders == [], "use core.providers.errors.raise_for_upstream():\n" + "\n".join(
        offenders
    )


def test_the_scan_sees_each_form():
    source = (
        "if r.status_code in (401, 403): pass\n"
        "if r.status_code == 401: pass\n"
        "if 403 == resp.status_code: pass\n"
        "if r.status_code == 404: pass\n"
        "if r.status_code in [500, 502]: pass\n"
    )
    assert hand_rolled(ast.parse(source)) == [1, 2, 3]
