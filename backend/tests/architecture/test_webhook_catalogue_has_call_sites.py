"""
The webhook catalogue is small and real (JOBS_AND_INTEGRATIONS.md § 16): every event flagged
external=True has at least one `emit("<name>"` call in production code outside the webhooks
machinery. An event nothing emits is a promise the product does not keep.

This test FAILS, it never skips, when the scanned file set or the catalogue is empty: the
equivalent test once scanned a directory a refactor had removed, and passed silently for ever.
"""

import ast
from pathlib import Path

from core.registry import registry
from tests.architecture.sources import iter_python_sources, parse, rel


def is_webhooks_machinery(path: Path) -> bool:
    return "webhooks" in path.parts or path.stem == "webhooks"


def emitted_names(tree: ast.AST) -> set[str]:
    """Literal first arguments of every `emit(...)` / `x.emit(...)` call."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        first = node.args[0]
        if name == "emit" and isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
    return found


def scan() -> tuple[int, dict[str, list[str]]]:
    scanned, sites = 0, {}
    for path in iter_python_sources():
        if is_webhooks_machinery(path):
            continue
        scanned += 1
        for name in emitted_names(parse(path)):
            sites.setdefault(name, []).append(rel(path))
    return scanned, sites


def test_every_catalogue_event_has_an_emit_call_site():
    scanned, sites = scan()
    assert scanned, "scanned no source files: the scan is looking in the wrong place"
    catalogue = [event.name for event in registry.events.external()]
    assert catalogue, "the webhook catalogue is empty: nothing registered an external event"
    missing = sorted(set(catalogue) - sites.keys())
    assert missing == [], (
        f"catalogue events nothing emits (add the emit() call or drop external=True): {missing}"
    )


def test_every_emit_call_names_a_registered_event():
    _, sites = scan()
    unknown = sorted(name for name in sites if name not in registry.events)
    assert unknown == [], f"emit() of events nobody registered: {unknown}"


def test_the_scan_sees_each_call_form():
    source = 'emit("a.b.c", x)\nwebhooks.emit("d.e.f", y)\nemit(name, z)\nother("g.h.i")\n'
    assert emitted_names(ast.parse(source)) == {"a.b.c", "d.e.f"}


def test_the_machinery_is_excluded():
    assert is_webhooks_machinery(Path("core/webhooks/emission.py"))
    assert not is_webhooks_machinery(Path("users/services/users.py"))
