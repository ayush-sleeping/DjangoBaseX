"""
Secrets are read from the environment in one place: settings (CONFIGURATION.md § 18; AGENTS.md § 3;
BUILD_ORDER 5.6).

The bug it prevents: a module that reads `os.environ["STRIPE_SECRET_KEY"]` itself escapes the boot
audit (core.config_audit judges only what settings hold), escapes the test settings' pinning, and
breaks the day the variable is renamed. A credential-shaped key is read by config/settings.py and
reaches code as a setting.

How (AST, production code incl. scripts/ and management commands): a string constant naming a
credential-shaped key (KEY, SECRET, TOKEN, PASSWORD) given to `os.environ[…]`, `os.environ.get`,
`os.getenv`, `environ.get`, or a django-environ reader (`env(…)`, `env.str(…)`, …) outside
config/settings*.py.

A key given as a module-level constant (`PASSWORD_ENV = "…"`) is resolved first.

Blind spots: a key name built at runtime or imported from another module; a read through a helper
defined elsewhere. Complementary
guard: test_production_boot.py proves the audit sees every secret settings read.

Do NOT silence this by adding an exception — fix the code. An allow-list entry needs a reason.
"""

import ast
import re
from pathlib import Path

from tests.architecture._ratchet import assert_ratchet
from tests.architecture.sources import Hit, iter_python_sources, parse, rel

SETTINGS = re.compile(r"^backend/config/settings[^/]*\.py$")
SECRET_SHAPED = re.compile(r"KEY|SECRET|TOKEN|PASSWORD")
ENV_READERS = {"env", "getenv"}
ENV_METHODS = {"get", "str", "bool", "int", "list", "json", "url", "db_url", "cache_url"}

# path::KEY -> why it is allowed. Do not add an entry without a reason.
ALLOWED: dict[str, str] = {
    "backend/rbac/management/commands/bootstrap_admin.py::BOOTSTRAP_ADMIN_PASSWORD": (
        "One-shot CLI input for a non-interactive first account (setup.sh passes it through the "
        "environment, never argv). It is a password to set, not configuration, so it is never a "
        "setting."
    ),
}


def _is_environ(node: ast.AST) -> bool:
    """`os.environ` or a bare `environ` (from os import environ)."""
    if isinstance(node, ast.Attribute):
        return node.attr == "environ" and isinstance(node.value, ast.Name)
    return isinstance(node, ast.Name) and node.id == "environ"


def _key_read(node: ast.AST) -> ast.AST | None:
    """The key expression of an environment read, or None."""
    if isinstance(node, ast.Subscript) and _is_environ(node.value):
        return node.slice
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id in ENV_READERS:
        return node.args[0]  # env("X") / getenv("X")
    if isinstance(func, ast.Attribute):
        receiver = func.value
        if func.attr == "getenv" or (func.attr == "get" and _is_environ(receiver)):
            return node.args[0]  # os.getenv("X"), os.environ.get("X")
        if func.attr in ENV_METHODS and isinstance(receiver, ast.Name) and receiver.id == "env":
            return node.args[0]  # env.str("X")
    return None


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """NAME -> value for every module-level `NAME = "literal"`."""
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value.value, str):
                    found[target.id] = node.value.value
    return found


def secret_env_hits(files) -> list[Hit]:
    hits = []
    for path in files:
        if SETTINGS.match(rel(path)):
            continue
        tree = parse(path)
        constants = _module_strings(tree)
        for node in ast.walk(tree):
            key = _key_read(node)
            if isinstance(key, ast.Name):
                value = constants.get(key.id)
            elif isinstance(key, ast.Constant) and isinstance(key.value, str):
                value = key.value
            else:
                continue
            if value and SECRET_SHAPED.search(value):
                hits.append(Hit(rel(path), node.lineno, value))
    return sorted(hits, key=lambda h: (h.path, h.line))


def test_no_secret_env_reads_outside_settings():
    assert_ratchet(secret_env_hits(iter_python_sources()), ALLOWED, rule="secret_env_reads")


def test_catches_secret_reads_outside_settings(tmp_path: Path):
    code = tmp_path / "billing.py"
    code.write_text(
        "import os\nfrom os import environ\n"
        'a = os.environ["STRIPE_SECRET_KEY"]\n'
        'b = os.environ.get("WEBHOOK_TOKEN")\n'
        'c = os.getenv("SMTP_PASSWORD")\n'
        'd = environ.get("API_KEY", "")\n'
        'e = env("JWT_SIGNING_KEY")\n'
        'f = env.str("SECRET_KEY")\n'
        'g = os.environ.get("LOG_LEVEL")\n'  # not credential-shaped: another guard's business
        'PASSWORD_ENV = "ADMIN_PASSWORD"\n'
        "h = os.environ.get(PASSWORD_ENV)\n"
    )
    assert [str(h) for h in secret_env_hits([code])] == [
        "billing.py:3: STRIPE_SECRET_KEY",
        "billing.py:4: WEBHOOK_TOKEN",
        "billing.py:5: SMTP_PASSWORD",
        "billing.py:6: API_KEY",
        "billing.py:7: JWT_SIGNING_KEY",
        "billing.py:8: SECRET_KEY",
        "billing.py:11: ADMIN_PASSWORD",
    ]
