"""The production compose file and release Dockerfiles as policy-as-tests (BUILD_ORDER 9.5;
OPERATIONS.md §§ 5, 15, 16).

Parsed with PyYAML (anchors and merge keys resolved) and a small Dockerfile reader; no Docker is
needed. Each rule is a pure function returning violations and has a positive control: a hand-built
input that breaks it, asserted to be flagged. The universe is asserted non-empty, so a rule that
finds zero services fails instead of passing.

Not checkable yet, recorded in TECH_DEBT: digest-pinned base images (needs registry access), the
edge-proxy-only-publishes rule (no proxy exists; today nothing publishes, which is stricter), and
`docker compose config` resolution (the dev file's test covers that mechanism).
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
COMPOSE = REPO / "docker-compose.prod.yml"
DOCKERFILES = [REPO / "backend" / "Dockerfile.prod", REPO / "frontend" / "Dockerfile.prod"]
SECRET_NAME = re.compile(r"PASSWORD|SECRET|KEY|TOKEN")
FORBIDDEN_COMMANDS = ("--reload", "runserver", "next dev", "npm run dev", "migrate")
REQUIRED = re.compile(r"^\$\{[A-Z0-9_]+:\?[^}]*\}$")


def load(text: str) -> dict:
    return yaml.safe_load(text)


def real() -> dict:
    return load(COMPOSE.read_text())


def services(cfg: dict) -> dict:
    found = cfg.get("services") or {}
    assert found, "no services found: the policy is looking in the wrong place"
    return found


def command_text(svc: dict) -> str:
    cmd = svc.get("command", "")
    return " ".join(cmd) if isinstance(cmd, list) else str(cmd)


def image_violations(cfg: dict) -> list[str]:
    out = []
    for name, svc in services(cfg).items():
        image = str(svc.get("image", ""))
        if "build" in svc:
            out.append(f"{name}: build: is development-only")
        if not re.search(r":\$\{APP_VERSION:\?[^}]*\}$", image):
            out.append(f"{name}: image {image!r} must be <prefix>/<name>:${{APP_VERSION:?}}")
        if image.endswith(":latest") or "latest" in image.split(":")[-1]:
            out.append(f"{name}: :latest")
    return out


def port_violations(cfg: dict) -> list[str]:
    return [f"{n}: publishes ports" for n, s in services(cfg).items() if s.get("ports")]


def mount_and_command_violations(cfg: dict) -> list[str]:
    out = []
    for name, svc in services(cfg).items():
        for vol in svc.get("volumes", []):
            if str(vol).startswith((".", "/", "~")):
                out.append(f"{name}: bind mount {vol}")
        for word in FORBIDDEN_COMMANDS:
            if word in command_text(svc):
                out.append(f"{name}: command contains {word!r}")
    return out


def secret_violations(cfg: dict) -> list[str]:
    out = []
    for name, svc in services(cfg).items():
        env = svc.get("environment") or {}
        for key, value in env.items():
            if SECRET_NAME.search(key) and not REQUIRED.match(str(value)):
                out.append(f"{name}: {key} is not ${{VAR:?}}")
    return out


def hardening_violations(cfg: dict) -> list[str]:
    out = []
    for name, svc in services(cfg).items():
        if "no-new-privileges:true" not in svc.get("security_opt", []):
            out.append(f"{name}: no-new-privileges")
        if svc.get("cap_drop") != ["ALL"]:
            out.append(f"{name}: cap_drop ALL")
        for limit in ("mem_limit", "cpus", "pids_limit"):
            if limit not in svc:
                out.append(f"{name}: {limit}")
        if "healthcheck" not in svc:
            out.append(f"{name}: healthcheck")
        if svc.get("logging", {}).get("driver", "json-file") == "json-file":
            out.append(f"{name}: json-file logging dies with the container")
        if not svc.get("read_only"):
            out.append(f"{name}: read_only root filesystem")
    return out


def readiness_violations(cfg: dict) -> list[str]:
    probe = " ".join(map(str, services(cfg)["backend"].get("healthcheck", {}).get("test", [])))
    return [] if "/api/health/ready/" in probe else ["backend: healthcheck must target readiness"]


def stages(text: str) -> list[list[str]]:
    """Each build stage's instruction lines (continuations joined)."""
    joined = re.sub(r"\\\n\s*", " ", text)
    result: list[list[str]] = []
    for line in joined.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.upper().startswith("FROM "):
            result.append([])
        if result:
            result[-1].append(line)
    return result


def dockerfile_violations(text: str) -> list[str]:
    out = []
    parsed = stages(text)
    if not parsed:
        return ["no FROM found"]
    for stage in parsed:
        base = stage[0].split()[1]
        if base.endswith(":latest") or (":" not in base and "$" not in base):
            out.append(f"base image {base} is unpinned")
    final = parsed[-1]
    users = [line.split()[1] for line in final if line.upper().startswith("USER ")]
    if not users or not re.match(r"^\d+(:\d+)?$", users[-1]) or users[-1].split(":")[0] == "0":
        out.append("final stage must end as a numeric non-root USER")
    if not any(line.upper().startswith("HEALTHCHECK ") for line in final):
        out.append("final stage has no HEALTHCHECK")
    for line in text.splitlines():
        if re.match(r"^\s*(ARG|ENV)\s+\S*(PASSWORD|SECRET|TOKEN|PRIVATE_KEY)", line, re.I):
            out.append(f"secret-shaped ARG/ENV persists in image history: {line.strip()}")
    cmd = " ".join(line for line in final if line.upper().startswith(("CMD ", "ENTRYPOINT ")))
    for word in FORBIDDEN_COMMANDS:
        if word in cmd:
            out.append(f"CMD/ENTRYPOINT contains {word!r}")
    return out


# --- the real files ----------------------------------------------------------------------------


def test_the_production_compose_file_exists_and_has_the_application_tier():
    assert set(services(real())) == {"backend", "worker", "beat", "frontend"}


@pytest.mark.parametrize(
    "rule",
    [
        image_violations,
        port_violations,
        mount_and_command_violations,
        secret_violations,
        hardening_violations,
        readiness_violations,
    ],
)
def test_the_production_compose_file_obeys(rule):
    assert rule(real()) == []


def test_every_secret_in_the_raw_file_has_no_default():
    raw = COMPOSE.read_text()
    assert not re.search(r"(PASSWORD|SECRET|KEY|TOKEN)\w*: *\$\{[^}]*:-", raw)


def test_beat_runs_exactly_once_and_workers_cover_every_queue():
    cfg = services(real())
    assert "beat" in command_text(cfg["beat"]) and "scale" not in cfg["beat"]
    assert "deploy" not in cfg["beat"] or cfg["beat"]["deploy"].get("replicas", 1) == 1
    assert "-Q default,bulk,outbox" in command_text(cfg["worker"])


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.parent.name)
def test_release_dockerfiles_obey(path):
    assert dockerfile_violations(path.read_text()) == []


def test_the_backend_image_never_migrates_and_runs_gunicorn():
    final = stages(DOCKERFILES[0].read_text())[-1]
    cmd = " ".join(line for line in final if line.upper().startswith("CMD "))
    assert "gunicorn" in cmd and "migrate" not in cmd


def test_the_frontend_build_clears_the_fetch_cache_and_requires_the_api_origin():
    text = DOCKERFILES[1].read_text()
    assert "rm -rf .next/cache/fetch-cache" in text and 'test -n "$NEXT_PUBLIC_API_URL"' in text


def test_a_dockerignore_keeps_secrets_out_of_the_build_context():
    text = (REPO / ".dockerignore").read_text()
    for needle in (".env", "*.pem", "node_modules", ".git/", ".venv"):
        assert needle in text


# --- positive controls: each rule can fail -----------------------------------------------------

GOOD = """
services:
  web:
    image: ${IMAGE_PREFIX:?}/web:${APP_VERSION:?}
    security_opt: ["no-new-privileges:true"]
    cap_drop: [ALL]
    read_only: true
    logging: {driver: journald}
    mem_limit: 1m
    cpus: 1
    pids_limit: 1
    healthcheck: {test: ["CMD", "x", "/api/health/ready/"]}
    environment: {DB_PASSWORD: "${DB_PASSWORD:?}"}
"""


def mutate(**changes) -> dict:
    cfg = load(GOOD)
    cfg["services"]["web"].update(changes)
    return cfg


def test_the_good_fixture_is_clean():
    cfg = load(GOOD)
    for rule in (image_violations, port_violations, secret_violations, hardening_violations):
        assert rule(cfg) == []


@pytest.mark.parametrize(
    ("rule", "changes"),
    [
        (image_violations, {"build": "."}),
        (image_violations, {"image": "acme/web:latest"}),
        (image_violations, {"image": "acme/web:1.0.0"}),
        (port_violations, {"ports": ["80:80"]}),
        (mount_and_command_violations, {"volumes": ["./backend:/app"]}),
        (mount_and_command_violations, {"command": "python manage.py runserver"}),
        (mount_and_command_violations, {"command": ["npm", "run", "dev"]}),
        (secret_violations, {"environment": {"API_TOKEN": "${API_TOKEN:-dev}"}}),
        (secret_violations, {"environment": {"SECRET_KEY": "literal"}}),
        (hardening_violations, {"cap_drop": []}),
        (hardening_violations, {"mem_limit": None}),
        (hardening_violations, {"logging": {"driver": "json-file"}}),
        (hardening_violations, {"read_only": False}),
    ],
)
def test_each_compose_rule_catches_its_violation(rule, changes):
    cfg = mutate(**changes)
    cfg["services"]["web"] = {k: v for k, v in cfg["services"]["web"].items() if v is not None}
    assert rule(cfg)


def test_a_missing_healthcheck_is_caught():
    cfg = load(GOOD)
    del cfg["services"]["web"]["healthcheck"]
    assert "web: healthcheck" in hardening_violations(cfg)


def test_an_empty_universe_fails_instead_of_passing():
    with pytest.raises(AssertionError, match="no services"):
        port_violations({"services": {}})


@pytest.mark.parametrize(
    "text",
    [
        "FROM python:latest\nUSER 10001\nHEALTHCHECK CMD x\n",
        "FROM python\nUSER 10001\nHEALTHCHECK CMD x\n",
        "FROM python:3.12\nHEALTHCHECK CMD x\n",
        "FROM python:3.12\nUSER root\nHEALTHCHECK CMD x\n",
        "FROM python:3.12\nUSER 0\nHEALTHCHECK CMD x\n",
        "FROM python:3.12\nUSER 10001\n",
        "FROM python:3.12\nARG SENTRY_TOKEN\nUSER 10001\nHEALTHCHECK CMD x\n",
        "FROM python:3.12\nUSER 10001\nHEALTHCHECK CMD x\nCMD python manage.py runserver\n",
        "",
    ],
)
def test_each_dockerfile_rule_catches_its_violation(text):
    assert dockerfile_violations(text)


def test_a_later_stage_user_is_what_counts():
    text = "FROM a:1 AS b\nUSER 0\nFROM a:1\nUSER 10001:10001\nHEALTHCHECK CMD x\n"
    assert dockerfile_violations(text) == []
