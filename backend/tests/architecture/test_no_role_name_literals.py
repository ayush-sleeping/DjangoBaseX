"""
Roles are classified by column, never by a name typed into code (RBAC_DESIGN.md; CONFIGURATION.md
§ 18; BUILD_ORDER 5.6).

The bug it prevents: `if role.name == "Manager"` works until an admin renames the role, or a product
calls it "Supervisor", and then quietly returns False: no error, just a permission check that no
longer fires. Code asks a column (`is_system`, `is_elevated`, `mfa_required`) or a permission, and
the one system role code must refer to is the named constant `rbac.services.ADMINISTRATOR`.

How (AST, production code only): a string constant
  - passed to any call named `has_role`;
  - compared with a `.name` or `.slug` attribute of an expression that mentions a role or group;
  - given to a `name`/`slug` lookup on a call whose receiver mentions a role or group
    (`Role.objects.get(name="…")`), or to any `role__name=`, `roles__slug__in=`, `groups__name=`
    keyword.

Blind spots: a literal bound to a variable first and compared later; a role found by its
public_id. Excluded by path: rbac/seeding.py (it projects the catalog) and migrations.

Do NOT silence this by adding an exception — fix the code. An allow-list entry needs a reason.
"""

import ast
import re
from pathlib import Path

from tests.architecture._ratchet import assert_ratchet
from tests.architecture.sources import Hit, iter_python_sources, parse, rel

EXCLUDED = {"backend/rbac/seeding.py"}
ROLE_WORD = re.compile(r"role|group", re.IGNORECASE)
LOOKUP_KEYWORD = re.compile(r"^(name|slug)(__(in|iexact|exact))?$")
RELATED_KEYWORD = re.compile(r"(^|__)(roles?|groups?)__(name|slug)(__\w+)?$")

# path::value -> why it is allowed. Do not add an entry without a reason.
ALLOWED: dict[str, str] = {}


def _strings(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [s for element in node.elts for s in _strings(element)]
    return []


def _mentions_role(node: ast.AST) -> bool:
    return bool(ROLE_WORD.search(ast.unparse(node)))


def _is_role_attribute(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in {"name", "slug"}
        and _mentions_role(node.value)
    )


def _call_name(node: ast.Call) -> str:
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def role_name_hits(files) -> list[Hit]:
    hits = []
    for path in files:
        if rel(path) in EXCLUDED:
            continue
        for node in ast.walk(parse(path)):
            found: list[str] = []
            if isinstance(node, ast.Call):
                if _call_name(node) == "has_role":
                    found += [s for arg in node.args for s in _strings(arg)]
                for keyword in node.keywords:
                    name = keyword.arg or ""
                    receiver_is_role = isinstance(node.func, ast.Attribute) and _mentions_role(
                        node.func.value
                    )
                    if RELATED_KEYWORD.search(name) or (
                        receiver_is_role and LOOKUP_KEYWORD.match(name)
                    ):
                        found += _strings(keyword.value)
            elif isinstance(node, ast.Compare):
                sides = [node.left, *node.comparators]
                if any(_is_role_attribute(side) for side in sides):
                    found += [s for side in sides for s in _strings(side)]
            hits += [Hit(rel(path), node.lineno, value) for value in found]
    return sorted(hits, key=lambda h: (h.path, h.line))


def test_no_role_name_literals_in_production_code():
    assert_ratchet(role_name_hits(iter_python_sources()), ALLOWED, rule="no_role_name_literals")


def test_catches_role_names_typed_into_code(tmp_path: Path):
    code = tmp_path / "views.py"
    code.write_text(
        "def check(user, role, Role, UserRole, ADMIN):\n"
        '    if user.has_role("Manager"): pass\n'
        '    if role.name == "Manager": pass\n'
        '    if user.primary_role.slug in ("auditor", "owner"): pass\n'
        '    Role.objects.get(name="Supervisor")\n'
        '    UserRole.objects.filter(role__slug="auditor")\n'
        '    user.groups.filter(name__in=["staff"])\n'
        "    Role.objects.get(slug=ADMIN)\n"  # a named constant: fine
        "    if role.is_elevated: pass\n"  # a column: fine
        '    if user.name == "Ada": pass\n'  # not a role
    )
    assert [str(h) for h in role_name_hits([code])] == [
        "views.py:2: Manager",
        "views.py:3: Manager",
        "views.py:4: auditor",
        "views.py:4: owner",
        "views.py:5: Supervisor",
        "views.py:6: auditor",
        "views.py:7: staff",
    ]
