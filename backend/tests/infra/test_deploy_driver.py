"""scripts/deploy.py (BUILD_ORDER 9.5; OPERATIONS.md § 6). Fakes only: no real deploy happens."""

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "deploy.py"
NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def drv():
    spec = importlib.util.spec_from_file_location("deploy_driver", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def cfg(drv, **kw):
    base = {
        "version": "1.4.0",
        "env": "production",
        "current_version": "1.3.2",
        "swap_cmds": [["restart-web"]],
        "health_url": "https://app.example.test/api/health/ready/",
        "health_interval": 0,
    }
    return drv.Config(**{**base, **kw})


class Fake:
    """Records every argv; `fail` maps a subcommand word to its exit status."""

    def __init__(self, fail=None):
        self.calls: list[list[str]] = []
        self.fail = fail or {}

    def __call__(self, argv):
        self.calls.append(argv)
        for word, status in self.fail.items():
            if word in argv:
                return status
        return 0

    def ran(self, word):
        return any(word in c for c in self.calls)


def go(drv, c, fake, probe=lambda url: True):
    out: list[str] = []
    code = drv.deploy(c, fake, probe, log=out.append, sleep=lambda s: None, now=NOW)
    return code, out


def test_a_deploy_whose_backup_fails_stops_before_migrating(drv):
    fake = Fake(fail={"backup": 3})
    code, out = go(drv, cfg(drv), fake)
    assert code == drv.EXIT_BACKUP
    assert fake.ran("backup")
    assert not fake.ran("migrate")  # the load-bearing assertion
    assert not fake.ran("restart-web")
    assert any("BEFORE migrate" in line for line in out)


def test_a_clean_deploy_runs_every_step_in_the_fixed_order(drv):
    fake = Fake()
    code, _ = go(drv, cfg(drv), fake)
    assert code == 0
    words = [c[c.index("manage.py") + 1] if "manage.py" in c else c[0] for c in fake.calls]
    assert words == ["check", "backup", "migrate", "migrate", "restart-web"]
    assert fake.calls[1][-2:] == ["--label", "predeploy-1.3.2-20261114t090000z"]


def test_a_failed_migrate_stops_before_the_swap(drv):
    fake = Fake(fail={"--noinput": 1})
    code, _ = go(drv, cfg(drv), fake)
    assert code == drv.EXIT_MIGRATE
    assert not fake.ran("restart-web")


def test_a_failed_health_check_fails_the_deploy(drv):
    code, out = go(drv, cfg(drv, health_tries=3), Fake(), probe=lambda url: False)
    assert code == drv.EXIT_HEALTH
    assert not any(line.startswith("deployed") for line in out)


def test_health_retries_until_ready(drv):
    answers = iter([False, False, True])
    code, _ = go(drv, cfg(drv, health_tries=5), Fake(), probe=lambda url: next(answers))
    assert code == 0


def test_no_backup_is_refused_in_production_and_runs_nothing(drv):
    fake = Fake()
    code, _ = go(drv, cfg(drv, no_backup=True), fake)
    assert code == drv.EXIT_CONFIG
    assert fake.calls == []


def test_no_backup_is_allowed_in_development(drv):
    fake = Fake()
    code, _ = go(drv, cfg(drv, env="development", production_like=False, no_backup=True), fake)
    assert code == 0
    assert not fake.ran("backup")


@pytest.mark.parametrize(
    "changes",
    [{"version": "latest"}, {"swap_cmds": []}, {"health_url": ""}],
)
def test_unresolvable_configuration_is_refused(drv, changes):
    fake = Fake()
    code, _ = go(drv, cfg(drv, **changes), fake)
    assert code == drv.EXIT_CONFIG
    assert fake.calls == []


def test_dry_run_prints_the_plan_and_changes_nothing(drv):
    fake = Fake()
    code, out = go(drv, cfg(drv, dry_run=True), fake)
    assert code == 0 and fake.calls == []
    order = [line.split(":")[0].split(". ")[1] for line in out if line.startswith("  ")]
    assert order == ["validate", "backup", "migrate", "migrate-check", "swap-1", "health"]


def test_output_is_scrubbed_of_urls_and_secret_env_values(drv):
    text = "connect postgres://app:hunter22@db:5432/app with tok-0123456789"
    clean = drv.scrub(text, {"SOME_API_TOKEN": "tok-0123456789"})
    assert "hunter22" not in clean and "tok-0123456789" not in clean


def test_a_missing_binary_is_a_failure_not_a_pass(drv):
    assert drv.run_command(["definitely-not-a-real-binary-9.5"]) != 0


def test_environment_vocabulary_comes_from_core_env(drv):
    assert drv.non_production() >= {"development", "test"}
    assert "production" not in drv.non_production()
