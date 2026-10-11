"""
Finds every permission code the backend's own code refers to (AUTH_BLUEPRINT § 9.3).

Static, by AST: nothing is imported or run, so a module that never loads is still scanned. Three
shapes count as a reference, and only strings shaped like a code are kept:

  (a) the first argument of any call to a name ending in `has_perm`  (user.has_perm("a.b.c")),
      and every string in the first argument of one ending in `has_perms` (Django's plural);
  (b) any string argument of a call to a name ending in `HasPermission`;
  (c) every string anywhere in the value given to `required_permissions`, as an assignment to a
      name or attribute, or as a keyword argument.

Test code is skipped: tests refer to codes that do not exist on purpose, to prove they are denied.
"""

import ast
from collections import defaultdict
from pathlib import Path

from core.registry import CODE_PATTERN

BACKEND = Path(__file__).resolve().parents[2]

# Directories never scanned, wherever they appear. Hidden directories (.venv, .ruff_cache …) too.
SKIPPED_DIRS = frozenset({"tests", "migrations", "__pycache__", "node_modules"})
REQUIRED_PERMISSIONS = "required_permissions"


def is_test_file(path: Path) -> bool:
    return path.name in {"tests.py", "conftest.py"} or path.name.startswith("test_")


def python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts[:-1]
        if any(part in SKIPPED_DIRS or part.startswith(".") for part in parts):
            continue
        if is_test_file(path):
            continue
        yield path


def find_permission_refs(root: Path = BACKEND) -> dict[str, list[str]]:
    """code → ["relative/path.py:line", …], sorted. A file that does not parse raises."""
    refs: dict[str, list[str]] = defaultdict(list)
    for path in python_files(root):
        where = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _referenced_strings(tree):
            if CODE_PATTERN.match(node.value):
                refs[node.value].append(f"{where}:{node.lineno}")
    return {code: sorted(set(places)) for code, places in sorted(refs.items())}


def _name(node: ast.expr) -> str:
    """`foo` → "foo", `a.b.foo` → "foo": a callee or an assignment target."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _strings(node: ast.AST | None):
    if node is None:
        return
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child


def _direct_string(node: ast.expr):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node


def _referenced_strings(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _name(node.func)
            if name.endswith("has_perm") and node.args:
                yield from _direct_string(node.args[0])
            elif name.endswith("has_perms") and node.args:
                yield from _strings(node.args[0])
            elif name.endswith("HasPermission"):
                for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                    yield from _direct_string(arg)
            for kw in node.keywords:
                if kw.arg == REQUIRED_PERMISSIONS:
                    yield from _strings(kw.value)
        elif isinstance(node, ast.Assign):
            if any(_name(t) == REQUIRED_PERMISSIONS for t in node.targets):
                yield from _strings(node.value)
        elif isinstance(node, ast.AnnAssign):
            if _name(node.target) == REQUIRED_PERMISSIONS:
                yield from _strings(node.value)
