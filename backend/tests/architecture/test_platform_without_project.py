"""
BUILD_ORDER 1.6 done-when: deleting project/ leaves a working platform, and a test asserts it.

The backend is copied without project/ into a temporary directory and booted there with the test
settings: system checks pass and the platform's routes still resolve. The copy runs in a separate
interpreter, so the already-loaded Django in this process proves nothing about it.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
IGNORE = shutil.ignore_patterns(
    "project", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", "db.sqlite3", ".env*"
)
PROBE = """
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
assert "project" not in settings.INSTALLED_APPS, settings.INSTALLED_APPS
call_command("check", fail_level="ERROR")
for name in ("core:health", "users:login", "users:users", "rbac:roles"):
    reverse(name)
print("PLATFORM-OK")
"""


def run_probe(root: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings_test", "PYTHONPATH": str(root)}
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_platform_boots_and_routes_without_project(tmp_path):
    copy = tmp_path / "backend"
    shutil.copytree(BACKEND, copy, ignore=IGNORE)
    assert not (copy / "project").exists()

    result = run_probe(copy)
    assert result.returncode == 0 and "PLATFORM-OK" in result.stdout, result.stderr[-2000:]


def test_the_probe_can_fail(tmp_path):
    # Positive control: a copy whose platform imports project must NOT boot without it.
    copy = tmp_path / "backend"
    shutil.copytree(BACKEND, copy, ignore=IGNORE)
    views = copy / "core" / "views.py"
    views.write_text("import project.wiring  # planted\n" + views.read_text())

    result = run_probe(copy)
    assert result.returncode != 0
    assert "No module named 'project'" in result.stderr
