"""
The deploy driver (BUILD_ORDER 9.5; OPERATIONS.md § 6). One entrypoint, fixed step order:

    announce -> validate -> verified backup -> (stop if it failed) -> migrate -> migrate --check
             -> swap/restart hooks -> health check -> report

    python3 scripts/deploy.py 1.4.0 --env production --current-version 1.3.2 \\
        --swap-cmd "docker compose -f docker-compose.prod.yml up -d --no-deps backend worker" \\
        --health-url https://app.example.com/api/health/ready/
    python3 scripts/deploy.py 1.4.0 --env staging --dry-run     # print the plan, change nothing

The backup runs BEFORE migrate and a non-zero backup exit ends the deploy: nothing after it runs.
`manage.py backup` verifies its own dump, so "exit 0" means "a verified dump exists". Every command
is an argv list run without a shell; nothing is `|| true`; output is scrubbed of URL passwords and
of the values of secret-named environment variables. The stateful tier is never touched here.

Rollback is re-running with the previous version: migrations are expand-only (OPERATIONS.md § 8).
Restoring the database is the last resort, not the rollback plan.

Standard library only. Exit codes: 0 deployed, 2 configuration, 3 backup failed, 4 migrate failed,
5 swap failed, 6 health check failed, 7 validation failed.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"

EXIT_OK, EXIT_CONFIG, EXIT_BACKUP, EXIT_MIGRATE, EXIT_SWAP, EXIT_HEALTH, EXIT_VALIDATE = (
    0,
    2,
    3,
    4,
    5,
    6,
    7,
)
VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")
URL_USERINFO = re.compile(r"(\w+://[^/\s:@]*):[^@\s/]*@")
SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD")

Run = Callable[[list[str]], int]
Probe = Callable[[str], bool]


def non_production() -> frozenset[str]:
    """core.env.NON_PRODUCTION, the one owner of 'is this production-like' (loaded by path so no
    Django import happens)."""
    spec = importlib.util.spec_from_file_location("_core_env", BACKEND / "core" / "env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NON_PRODUCTION


def scrub(text: str, environ: dict[str, str] | None = None) -> str:
    text = URL_USERINFO.sub(r"\1:***@", text)
    for name, value in (os.environ if environ is None else environ).items():
        if SECRET_NAME.search(name) and len(value) >= 6:
            text = text.replace(value, "***")
    return text


@dataclass
class Config:
    version: str
    env: str
    current_version: str = "unknown"
    production_like: bool = True
    swap_cmds: list[list[str]] = field(default_factory=list)
    health_url: str = ""
    health_tries: int = 60
    health_interval: float = 2.0
    no_backup: bool = False
    dry_run: bool = False
    manage: list[str] = field(default_factory=lambda: ["uv", "run", "python", "manage.py"])
    backup_dir: str = ""

    def validate(self) -> str | None:
        """Why this configuration may not run, or None."""
        if not VERSION.match(self.version):
            return f"version {self.version!r} is not a release version (1.2.3 or 1.2.3-rc.1)"
        if self.no_backup and self.production_like:
            return "--no-backup is refused outside development"
        if self.production_like and not self.swap_cmds:
            return "a production-like deploy needs at least one --swap-cmd"
        if self.production_like and not self.health_url:
            return "a production-like deploy needs --health-url"
        return None


@dataclass
class Step:
    name: str
    argv: list[str] | None  # None: handled by the driver itself (health)
    code: int


def plan(cfg: Config, now: datetime | None = None) -> list[Step]:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    steps: list[Step] = []
    if cfg.production_like:
        deploy_check = [*cfg.manage, "check", "--deploy", "--fail-level", "WARNING"]
        steps.append(Step("validate", deploy_check, EXIT_VALIDATE))
    if not cfg.no_backup:
        label = f"predeploy-{cfg.current_version}-{stamp}".lower()
        backup = [*cfg.manage, "backup", "--label", label]
        if cfg.backup_dir:
            backup += ["--dir", cfg.backup_dir]
        steps.append(Step("backup", backup, EXIT_BACKUP))
    steps.append(Step("migrate", [*cfg.manage, "migrate", "--noinput"], EXIT_MIGRATE))
    steps.append(Step("migrate-check", [*cfg.manage, "migrate", "--check"], EXIT_MIGRATE))
    for i, argv in enumerate(cfg.swap_cmds, 1):
        steps.append(Step(f"swap-{i}", argv, EXIT_SWAP))
    if cfg.health_url:
        steps.append(Step("health", None, EXIT_HEALTH))
    return steps


def deploy(
    cfg: Config,
    run: Run,
    probe: Probe,
    *,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> int:
    """Run the plan; the first failing step ends the deploy with that step's exit code."""
    problem = cfg.validate()
    if problem:
        log(f"deploy refused: {problem}")
        return EXIT_CONFIG
    steps = plan(cfg, now)
    log(f"deploy {cfg.current_version} -> {cfg.version} env={cfg.env} dry_run={cfg.dry_run}")
    if cfg.dry_run:
        for n, step in enumerate(steps, 1):
            shown = scrub(shlex.join(step.argv)) if step.argv else cfg.health_url
            log(f"  {n}. {step.name}: {shown}")
        return EXIT_OK
    for step in steps:
        log(f"step {step.name}")
        if step.argv is None:
            ok = False
            for attempt in range(cfg.health_tries):
                if probe(cfg.health_url):
                    ok = True
                    break
                if attempt + 1 < cfg.health_tries:
                    sleep(cfg.health_interval)
            if not ok:
                log(f"FAILED at health: {cfg.health_url} never answered ready")
                return step.code
            continue
        if run(step.argv) != 0:
            if step.name == "backup":
                log("FAILED at backup: stopping BEFORE migrate; the database was not changed")
            else:
                log(f"FAILED at {step.name}: the deploy stops here")
            return step.code
    log(f"deployed {cfg.version}")
    return EXIT_OK


# --- the real executors -----------------------------------------------------------------------


def run_command(argv: list[str]) -> int:
    """Run without a shell, from backend/, streaming scrubbed output. A missing binary is a
    failure, never a pass."""
    try:
        proc = subprocess.Popen(
            argv,
            cwd=BACKEND,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        print(scrub(f"cannot run {argv[0]}: {exc}"))
        return 127
    assert proc.stdout is not None
    for line in proc.stdout:
        print(scrub(line.rstrip()))
    return proc.wait()


def http_ready(url: str) -> bool:
    """200 from the URL, through curl (the platform's outbound-HTTP rule keeps HTTP clients out of
    code; this is an operator tool run on the deploy host). A missing curl is "not ready"."""
    try:
        done = subprocess.run(
            ["curl", "-fsS", "-o", "/dev/null", "--max-time", "5", url],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return done.returncode == 0


def parse(argv: list[str] | None = None) -> Config:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("version")
    p.add_argument("--env", required=True, help="the environment name (APP_ENV's vocabulary)")
    p.add_argument("--current-version", default="unknown")
    p.add_argument("--swap-cmd", action="append", default=[], help="one restart hook (repeatable)")
    p.add_argument("--health-url", default="")
    p.add_argument("--health-tries", type=int, default=60)
    p.add_argument("--health-interval", type=float, default=2.0)
    p.add_argument("--backup-dir", default="")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    return Config(
        version=a.version,
        env=a.env,
        current_version=a.current_version,
        production_like=a.env.strip().lower() not in non_production(),
        swap_cmds=[shlex.split(c) for c in a.swap_cmd],
        health_url=a.health_url,
        health_tries=a.health_tries,
        health_interval=a.health_interval,
        no_backup=a.no_backup,
        dry_run=a.dry_run,
        backup_dir=a.backup_dir,
    )


def main(argv: list[str] | None = None) -> int:
    return deploy(parse(argv), run_command, http_ready)


if __name__ == "__main__":
    sys.exit(main())
