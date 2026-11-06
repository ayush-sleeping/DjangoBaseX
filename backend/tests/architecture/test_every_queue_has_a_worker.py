"""
Every queue the job registry declares has a worker consuming it (JOBS_AND_INTEGRATIONS.md § 5;
BUILD_ORDER 7.1). A task routed to a queue nobody consumes is enqueued and never executed, and
nothing raises: the failed-jobs list stays empty, which reads as healthy.

It parses every topology file the repository ships and FAILS, never skips, when none is found: a
guard that skips inside a backend-only checkout protects nothing.
"""

import shlex
from pathlib import Path

import pytest
import yaml

from config.celery import app
from core.jobs.topology import declared_queues
from core.registry import registry

REPO = Path(__file__).resolve().parents[3]
# Every deployment topology the repository ships. Add a Procfile or manifest here when one appears.
TOPOLOGY_FILES = (REPO / "docker-compose.yml",)


def _argv(command) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    return [str(part) for part in command or []]


def worker_queues(argv: list[str]) -> set[str] | None:
    """The -Q/--queues set of a `celery ... worker` command, or None if it is not one. A worker with
    no -Q consumes only the default queue."""
    if "celery" not in " ".join(argv) or "worker" not in argv:
        return None
    for i, token in enumerate(argv):
        if token in ("-Q", "--queues") and i + 1 < len(argv):
            return set(argv[i + 1].split(","))
        if token.startswith("--queues="):
            return set(token.split("=", 1)[1].split(","))
        if token.startswith("-Q") and len(token) > 2:
            return set(token[2:].split(","))
    return {"default"}


def consumed_queues(paths=TOPOLOGY_FILES) -> set[str]:
    found = [path for path in paths if path.exists()]
    if not found:
        pytest.fail(f"no topology file found ({', '.join(str(p) for p in paths)})")
    consumed: set[str] = set()
    for path in found:
        services = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("services") or {}
        for svc in services.values():
            queues = worker_queues(_argv(svc.get("command")))
            if queues is not None:
                consumed |= queues
    return consumed


def test_the_registry_is_not_empty():
    # A registry that failed to load must not read as "no jobs, all fine".
    assert registry.jobs.specs()


def test_every_declared_queue_has_a_worker():
    consumed = consumed_queues()
    assert consumed, "no `celery worker` command in any topology file"
    missing = declared_queues() - consumed
    assert not missing, f"queues with no worker in {TOPOLOGY_FILES[0].name}: {sorted(missing)}"


def test_every_task_routes_to_its_specs_queue():
    """The router's actual answer, not our routing table: a module-path or glob route that
    silently misses a custom-named task shows up here."""
    app.finalize(auto=True)  # what enqueue() and every worker do before the first publish
    for spec in registry.jobs.specs():
        route = app.amqp.router.route({}, spec.name)
        assert route["queue"].name == spec.queue, spec.name


def test_the_check_fails_when_a_queue_has_no_worker(tmp_path):
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n  worker:\n    command: celery -A config worker -Q default\n", encoding="utf-8"
    )
    assert "bulk" in declared_queues()
    assert declared_queues() - consumed_queues((compose,)) == {"bulk"}


def test_no_topology_file_fails_rather_than_skips(tmp_path):
    with pytest.raises(pytest.fail.Exception):
        consumed_queues((tmp_path / "missing.yml",))


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("celery -A config worker -Q default,bulk -n x@%h", {"default", "bulk"}),
        (["celery", "-A", "config", "worker", "--queues=a,b"], {"a", "b"}),
        ("celery -A config worker", {"default"}),
        ("celery -A config beat", None),
        ("uv run python manage.py runserver", None),
    ],
)
def test_worker_queue_parsing(command, expected):
    assert worker_queues(_argv(command)) == expected
