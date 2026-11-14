"""
Monitors talk to operators through the dispatcher only (NOTIFICATIONS_AND_ALERTING.md § 14): in
core/ops/ nothing but dispatcher.py imports notify() or a channel, and neither do the modules of
any job whose owner_module is "ops" nor any module under a `monitors/` directory.
"""

import ast
import importlib.util

from core.registry import registry
from tests.architecture.sources import BACKEND

BANNED = ("core.notifications", "core.mail")


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def offences(paths):
    return [
        f"{p.relative_to(BACKEND)} imports {m}"
        for p in paths
        for m in imports(p)
        if m.startswith(BANNED)
    ]


def test_only_the_dispatcher_imports_notify():
    paths = [p for p in (BACKEND / "core" / "ops").glob("*.py") if p.name != "dispatcher.py"]
    assert paths, "the scan found no ops modules"
    assert offences(paths) == []


def test_ops_jobs_and_monitor_directories_import_neither_notify_nor_a_channel():
    paths = [
        BACKEND / "core" / "ops" / "jobs.py",
        *[p for d in BACKEND.rglob("monitors") if d.is_dir() for p in d.rglob("*.py")],
    ]
    for spec in registry.jobs.specs():
        if spec.owner_module == "ops":
            module = spec.func.rpartition(".")[0]
            origin = importlib.util.find_spec(module).origin
            paths.append(type(BACKEND)(origin))
    assert offences(paths) == []
