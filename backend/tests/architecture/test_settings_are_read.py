"""
A setting nothing reads is a defect (CONFIGURATION.md § 9.11): a control that saves and does
nothing teaches admins the screen is decorative. Three rules, by AST walk over backend/:

1. Every literal key passed to get_setting / resolve_setting / set_value / reset is registered —
   an unregistered read is a typo that must not wait for runtime.
2. Keys are literals at every read: a dynamic first argument defeats this whole file (§ 9.1).
3. Every registered key is read outside the settings machinery itself — directly by key, or
   through its policy class via resolve(Policy).
"""

import ast
from pathlib import Path

from core.registry import registry

BACKEND = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"__pycache__", ".venv", "node_modules", "plugins"}
# The machinery: reads here (the service, its API, the CLI) do not count as "someone uses it".
MACHINERY = {
    "core/settings_registry.py",
    "core/settings_service.py",
    "core/serializers.py",
    "core/api/settings.py",
    "core/management/commands/set_setting.py",
    "core/management/commands/sync_settings.py",
}
READERS = {"get_setting", "resolve_setting", "set_value", "reset"}


def is_test_file(rel: Path) -> bool:
    return rel.name.startswith("test_") or "tests" in rel.parts or rel.name == "conftest.py"


def scan():
    """(literal keys read, policy class names resolved, dynamic-key offences) outside machinery."""
    keys, policies, dynamic = set(), set(), []
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND)
        if SKIP_DIRS & set(rel.parts) or is_test_file(rel) or str(rel) in MACHINERY:
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(rel))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            first = node.args[0]
            if name in READERS:
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    keys.add(first.value)
                else:
                    dynamic.append(f"{rel}:{node.lineno} {name}(<non-literal key>)")
            elif name == "resolve" and isinstance(first, ast.Name):
                policies.add(first.id)
    return keys, policies, dynamic


def test_every_key_read_is_registered_and_every_registered_key_is_read():
    keys, policies, dynamic = scan()
    assert dynamic == [], "dynamic setting keys defeat this scan (§ 9.1):\n" + "\n".join(dynamic)

    registered = {d.key for d in registry.settings.defs()}
    assert registered, "no settings declared: the scan is testing nothing"
    unregistered = keys - registered
    assert not unregistered, f"reads of unregistered keys (typos?): {sorted(unregistered)}"

    read = set(keys)
    for policy, field_keys in registry.settings.policies().items():
        if policy.__name__ in policies:
            read |= set(field_keys.values())
    unread = registered - read
    assert not unread, (
        f"registered settings nothing reads (§ 9.11 — withdraw them or wire the reader): "
        f"{sorted(unread)}"
    )


def test_the_scan_sees_a_reader():
    # Positive control: the scan walks real code, so the reauth policy's resolve() must be found.
    _, policies, _ = scan()
    assert "ReauthPolicy" in policies
