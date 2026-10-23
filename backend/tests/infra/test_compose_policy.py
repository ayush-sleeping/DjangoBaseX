"""The development compose file, as policy-as-tests (OPERATIONS.md § 1, § 12, § 15, § 16).

Parse, don't grep: the rules read `docker compose config --format json`, the file Docker actually
runs, resolved with an explicit environment and an empty --env-file, so the repository-root .env
can never make a rule pass. The one exception is the secret-interpolation rule, which is about the
raw text (a resolved config has already substituted the default it would be looking for).

Each rule is a small pure function over the parsed config that returns its violations, and each has
a positive control: a hand-built config that breaks it, asserted to be flagged (BC-45). The controls
need no Docker; the tests against the real file skip, with the reason, where Docker is missing.
"""

import copy
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO / "docker-compose.yml"

SERVICES = {"db", "redis", "backend", "frontend"}
SECRET_NAME = re.compile(r"PASSWORD|SECRET|KEY|TOKEN")
LOOPBACK = "127.0.0.1"
# OPERATIONS.md § 12: the production server settings, in development too.
POSTGRES_SETTINGS = (
    "idle_in_transaction_session_timeout=60s",
    "shared_preload_libraries=pg_stat_statements",
    "log_min_duration_statement=500ms",
    "log_lock_waits=on",
    "deadlock_timeout=1s",
    "password_encryption=scram-sha-256",
)
PG_DATA = "/var/lib/postgresql/data"

# Dummy values, never real ones. The ports and prefix are probes: rule (l) proves they follow.
PROBE_ENV = {
    "POSTGRES_PASSWORD": "policy-pg-dummy",
    "REDIS_PASSWORD": "policy-redis-dummy",
    "COMPOSE_PROJECT_NAME": "policy-dev",
    "WEB_PORT": "3456",
    "API_PORT": "8765",
    "AUTH_COOKIE_PREFIX": "probe",
}


# --- Resolving the file -------------------------------------------------------------------------


def docker_unavailable() -> str | None:
    """Why the real file cannot be resolved here, or None."""
    if shutil.which("docker") is None:
        return "docker is not on PATH"
    try:
        result = subprocess.run(
            ["docker", "compose", "version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"`docker compose version` did not run: {exc}"
    if result.returncode != 0:
        return f"`docker compose version` failed: {result.stderr.strip()}"
    return None


def resolve(
    tmp_dir: Path, *, overrides: dict | None = None, unset: tuple = (), compose_file=COMPOSE_FILE
):
    """Run `docker compose config --format json` with only PATH, HOME and the probe values."""
    empty_env_file = tmp_dir / "empty.env"
    empty_env_file.write_text("")
    env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
    env.update(PROBE_ENV)
    env.update(overrides or {})
    for name in unset:
        env.pop(name, None)
    return subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "--project-directory",
            str(REPO),
            "--env-file",
            str(empty_env_file),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


@pytest.fixture(scope="module")
def docker():
    reason = docker_unavailable()
    if reason:
        pytest.skip(f"compose policy needs Docker Compose to resolve the file: {reason}")


@pytest.fixture(scope="module")
def config(docker, tmp_path_factory) -> dict:
    result = resolve(tmp_path_factory.mktemp("compose"))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# --- Helpers over a parsed config ---------------------------------------------------------------


def services(cfg: dict) -> dict:
    return cfg.get("services") or {}


def argv(value) -> list[str]:
    """A command, entrypoint or healthcheck test as tokens, whichever form it was written in."""
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    return [str(v) for v in value]


def environment(service: dict) -> dict:
    env = service.get("environment") or {}
    if isinstance(env, list):
        return dict(item.split("=", 1) if "=" in item else (item, None) for item in env)
    return env


def url_port(url: str) -> str:
    parts = urlsplit(url)
    return str(parts.port or {"http": 80, "https": 443}.get(parts.scheme, ""))


# --- The rules: each returns its violations, empty when the config complies ---------------------


def service_set_violations(cfg: dict) -> list[str]:
    found = set(services(cfg))
    if not found:
        return ["no services found: the policy is looking in the wrong place"]
    if found != SERVICES:
        return [f"services are {sorted(found)}, expected {sorted(SERVICES)}"]
    return []


def port_violations(cfg: dict) -> list[str]:
    out = []
    for name, svc in services(cfg).items():
        for port in svc.get("ports") or []:
            host_ip = port.get("host_ip") if isinstance(port, dict) else None
            if host_ip != LOOPBACK:
                out.append(f"{name} publishes {port!r} on {host_ip or 'every interface'}")
    return out


# A compose interpolation of a variable, not a `$$` escape (which the container's shell expands).
INTERPOLATION = re.compile(
    r"(?<!\$)\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?P<rest>[^}]*)\}|"
    r"(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"
)


def secret_interpolation_violations(text: str) -> list[str]:
    """Every secret-named variable is `${X:?...}`: no default (`:-`, `-`), never bare or `:+`."""
    out = []
    for match in INTERPOLATION.finditer(text):
        name = match.group("braced") or match.group("bare")
        if not SECRET_NAME.search(name.upper()):
            continue
        if match.group("bare") or not match.group("rest").startswith(":?"):
            out.append(f"{match.group(0)} is not ${{{name}:?...}}")
    return out


def healthcheck_violations(cfg: dict) -> list[str]:
    out = []
    for name, svc in services(cfg).items():
        check = svc.get("healthcheck") or {}
        test = argv(check.get("test"))
        if check.get("disable") or not test or test == ["NONE"]:
            out.append(f"{name} has no healthcheck test")
    return out


def db_probe_violations(cfg: dict) -> list[str]:
    """
    The db probe is pg_isready over TCP. On first start the image's init runs a temporary server on
    the unix socket only: a socket probe passes against it, and `up --wait` returns too early.
    """
    test = argv(((services(cfg).get("db") or {}).get("healthcheck") or {}).get("test"))
    tokens = shlex.split(" ".join(test[1:])) if test[:1] == ["CMD-SHELL"] else test[1:]
    if "pg_isready" not in tokens:
        return ["db healthcheck does not run pg_isready"]
    hosts = [tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t in ("-h", "--host")]
    hosts += [t.split("=", 1)[1] for t in tokens if t.startswith("--host=")]
    if not hosts or any(h.startswith("/") for h in hosts):
        return ["db healthcheck probes the unix socket, not TCP (-h 127.0.0.1)"]
    return []


def app_probe_violations(cfg: dict) -> list[str]:
    """
    The backend's healthcheck targets readiness, never liveness (OBSERVABILITY § 6): live answers
    from memory, so a container whose database is unreachable would stay "healthy" behind it.
    """
    test = argv(((services(cfg).get("backend") or {}).get("healthcheck") or {}).get("test"))
    joined = " ".join(test)
    if "/health/" not in joined:
        return ["backend healthcheck does not call /api/health/ready/"]
    if "/health/ready/" not in joined:
        return ["backend healthcheck targets live (or the alias), not /api/health/ready/"]
    return []


def hardening_violations(cfg: dict) -> list[str]:
    out = []
    for name, svc in services(cfg).items():
        if "no-new-privileges:true" not in (svc.get("security_opt") or []):
            out.append(f"{name} lacks security_opt no-new-privileges:true")
        if "ALL" not in (svc.get("cap_drop") or []):
            out.append(f"{name} lacks cap_drop ALL")
    return out


def logging_violations(cfg: dict) -> list[str]:
    """Every service sets a log driver; a json-file one is capped, or one service fills the disk."""
    out = []
    for name, svc in services(cfg).items():
        logging = svc.get("logging") or {}
        if not logging.get("driver"):
            out.append(f"{name} has no logging driver (the x-logging anchor is not applied)")
        elif logging["driver"] == "json-file" and not (logging.get("options") or {}).get(
            "max-size"
        ):
            out.append(f"{name} logs to an uncapped json-file (no max-size)")
    return out


def dockerfile_user_violations(text: str) -> list[str]:
    """The final stage's last USER is a numeric uid other than 0 (OPERATIONS.md § 15)."""
    stages = re.split(r"(?im)^\s*FROM\s", text)
    if len(stages) < 2:
        return ["no FROM line: not a Dockerfile"]
    users = re.findall(r"(?im)^\s*USER\s+(\S+)\s*$", stages[-1])
    if not users:
        return ["the final stage has no USER: it runs as root"]
    uid = users[-1].split(":", 1)[0]
    if not uid.isdigit():
        return [f"USER {users[-1]} is a name, not a numeric uid"]
    if int(uid) == 0:
        return ["USER is root (uid 0)"]
    return []


def image_tag(image: str) -> str | None:
    """The tag of `registry:port/name:tag@digest`, or None."""
    last = image.split("@", 1)[0].rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else None


def image_violations(cfg: dict) -> list[str]:
    images = {n: s["image"] for n, s in services(cfg).items() if s.get("image")}
    if not images:
        return ["no service names an image: the policy is looking in the wrong place"]
    out = []
    for name, image in images.items():
        tag = image_tag(image)
        if not tag or tag == "latest" or "." not in tag:
            out.append(f"{name} image {image!r} is not pinned to at least major.minor")
    return out


def db_volume_violations(cfg: dict) -> list[str]:
    db = services(cfg).get("db") or {}
    mounts = [
        v for v in db.get("volumes") or [] if isinstance(v, dict) and v.get("target") == PG_DATA
    ]
    if not mounts:
        return [f"db has no mount at {PG_DATA}"]
    declared = set(cfg.get("volumes") or {})
    out = []
    for mount in mounts:
        if mount.get("type") != "volume":
            out.append(f"db data is a {mount.get('type')} mount, not a named volume")
        elif mount.get("source") not in declared:
            out.append(f"db volume {mount.get('source')!r} is not declared under top-level volumes")
    return out


def postgres_settings_violations(cfg: dict) -> list[str]:
    tokens = argv((services(cfg).get("db") or {}).get("command"))
    given = {tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t == "-c"}
    return [f"db command lacks -c {s}" for s in POSTGRES_SETTINGS if s not in given]


def redis_auth_violations(cfg: dict) -> list[str]:
    redis = services(cfg).get("redis") or {}
    out = []
    if "--requirepass" not in " ".join(argv(redis.get("command"))):
        out.append("redis command does not set --requirepass")
    probe = " ".join(argv((redis.get("healthcheck") or {}).get("test")))
    if re.search(r"(^|[\s\"'])(-a|--pass)(\s|=|$)", probe):
        out.append("redis healthcheck passes the password on the command line (-a)")
    return out


def backend_migrate_violations(cfg: dict) -> list[str]:
    backend = services(cfg).get("backend") or {}
    run = argv(backend.get("entrypoint")) + argv(backend.get("command"))
    if re.search(r"\bmigrate\b", " ".join(run)):
        return ["backend runs migrate on container start (OPERATIONS.md § 2 step 8)"]
    return []


def frontend_backend_agreement_violations(cfg: dict) -> list[str]:
    backend = services(cfg).get("backend") or {}
    frontend = services(cfg).get("frontend") or {}
    b_env, f_env = environment(backend), environment(frontend)
    out = []
    if not b_env.get("AUTH_COOKIE_PREFIX"):
        out.append("backend has no AUTH_COOKIE_PREFIX")
    elif b_env.get("AUTH_COOKIE_PREFIX") != f_env.get("NEXT_PUBLIC_AUTH_COOKIE_PREFIX"):
        out.append("backend AUTH_COOKIE_PREFIX != frontend NEXT_PUBLIC_AUTH_COOKIE_PREFIX")

    web_ports = {
        str(p.get("published")) for p in frontend.get("ports") or [] if p.get("target") == 3000
    }
    if len(web_ports) != 1:
        return [*out, f"frontend publishes port 3000 {len(web_ports)} times, expected once"]
    web_port = web_ports.pop()
    for key in ("CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS", "FRONTEND_BASE_URL"):
        if key not in b_env and key != "CORS_ALLOWED_ORIGINS":
            continue
        origins = [o for o in (b_env.get(key) or "").split(",") if o.strip()]
        if not origins or any(url_port(o.strip()) != web_port for o in origins):
            out.append(f"backend {key} does not point at the frontend's port {web_port}")

    api_ports = {
        str(p.get("published")) for p in backend.get("ports") or [] if p.get("target") == 8000
    }
    public_api = f_env.get("NEXT_PUBLIC_API_URL")
    if public_api and {url_port(public_api)} != api_ports:
        out.append("frontend NEXT_PUBLIC_API_URL does not point at the backend's published port")
    return out


# --- The real file ------------------------------------------------------------------------------


def test_a_exactly_the_four_dev_services_exist(config):
    assert service_set_violations(config) == []


def test_b_every_published_port_binds_loopback(config):
    assert any(svc.get("ports") for svc in services(config).values()), "no published ports at all"
    assert port_violations(config) == []


# The secrets, and the cookie prefix: no identity default (CONFIGURATION.md § 7). A shared fallback
# prefix is the cross-checkout sign-out § 7 exists to prevent, and setup.sh always writes one.
@pytest.mark.parametrize("required", ["POSTGRES_PASSWORD", "REDIS_PASSWORD", "AUTH_COOKIE_PREFIX"])
@pytest.mark.parametrize("how", ["unset", "empty"])
def test_c_compose_refuses_to_resolve_without_a_required_value(docker, tmp_path, required, how):
    if how == "unset":
        result = resolve(tmp_path, unset=(required,))
    else:
        result = resolve(tmp_path, overrides={required: ""})
    assert result.returncode != 0, f"compose resolved with {required} {how}"
    assert required in result.stderr


def test_d_secrets_have_no_default_in_the_raw_file():
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    assert "${POSTGRES_PASSWORD:?" in text and "${REDIS_PASSWORD:?" in text  # not an empty universe
    assert secret_interpolation_violations(text) == []


def test_e_every_service_has_a_healthcheck(config):
    assert healthcheck_violations(config) == []


def test_e2_the_db_probe_uses_tcp_not_the_socket(config):
    assert db_probe_violations(config) == []


def test_e3_the_backend_probe_targets_ready_not_live(config):
    assert app_probe_violations(config) == []


def test_f_every_service_drops_privileges(config):
    assert hardening_violations(config) == []


def test_f2_every_service_has_a_capped_log_driver(config):
    assert logging_violations(config) == []


def test_f3_every_app_image_runs_as_a_numeric_non_root_uid(config):
    dockerfiles = {
        name: Path(svc["build"]["context"]) / svc["build"].get("dockerfile", "Dockerfile")
        for name, svc in services(config).items()
        if svc.get("build")
    }
    assert set(dockerfiles) == {"backend", "frontend"}  # not an empty universe
    for name, path in dockerfiles.items():
        assert dockerfile_user_violations(path.read_text(encoding="utf-8")) == [], name


def test_g_every_image_is_pinned(config):
    assert {n for n, s in services(config).items() if s.get("image")} >= {"db", "redis"}
    assert image_violations(config) == []


def test_h_db_data_is_a_declared_named_volume(config):
    assert db_volume_violations(config) == []


def test_i_db_carries_the_production_server_settings(config):
    assert postgres_settings_violations(config) == []


def test_j_redis_requires_a_password_and_the_probe_hides_it(config):
    assert redis_auth_violations(config) == []


def test_k_backend_never_migrates_on_start(config):
    assert backend_migrate_violations(config) == []


def test_l_frontend_and_backend_agree_and_follow_the_env(config):
    assert frontend_backend_agreement_violations(config) == []
    backend = environment(services(config)["backend"])
    frontend = environment(services(config)["frontend"])
    # They follow the environment, rather than agreeing on a hard-coded value.
    assert backend["AUTH_COOKIE_PREFIX"] == PROBE_ENV["AUTH_COOKIE_PREFIX"]
    assert frontend["NEXT_PUBLIC_AUTH_COOKIE_PREFIX"] == PROBE_ENV["AUTH_COOKIE_PREFIX"]
    assert url_port(backend["CORS_ALLOWED_ORIGINS"]) == PROBE_ENV["WEB_PORT"]
    assert url_port(frontend["NEXT_PUBLIC_API_URL"]) == PROBE_ENV["API_PORT"]


# --- Positive controls: a config that breaks each rule is flagged (BC-45) -----------------------


def compliant() -> dict:
    """A hand-built config satisfying every rule; each control below breaks exactly one."""
    hardening = {
        "security_opt": ["no-new-privileges:true"],
        "cap_drop": ["ALL"],
        "logging": {"driver": "json-file", "options": {"max-size": "10m"}},
    }

    def health(*test):
        return {"healthcheck": {"test": list(test)}}

    return {
        "services": {
            "db": {
                **hardening,
                **health("CMD-SHELL", "pg_isready -h 127.0.0.1 -U app -d app"),
                "image": "postgres:16.15-alpine",
                "command": ["postgres", *[x for s in POSTGRES_SETTINGS for x in ("-c", s)]],
                "ports": [{"host_ip": LOOPBACK, "target": 5432, "published": "5432"}],
                "volumes": [{"type": "volume", "source": "pgdata", "target": PG_DATA}],
            },
            "redis": {
                **hardening,
                **health("CMD-SHELL", 'REDISCLI_AUTH="$$REDIS_PASSWORD" redis-cli ping'),
                "image": "redis:7.4.11-alpine",
                "command": ["sh", "-c", 'exec redis-server --requirepass "$$REDIS_PASSWORD"'],
            },
            "backend": {
                **hardening,
                **health(
                    "CMD", "python", "-c", "urlopen('http://127.0.0.1:8000/api/health/ready/')"
                ),
                "command": ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"],
                "ports": [{"host_ip": LOOPBACK, "target": 8000, "published": "8765"}],
                "environment": {
                    "AUTH_COOKIE_PREFIX": "probe",
                    "CORS_ALLOWED_ORIGINS": "http://localhost:3456",
                    "CSRF_TRUSTED_ORIGINS": "http://localhost:3456",
                    "FRONTEND_BASE_URL": "http://localhost:3456",
                },
            },
            "frontend": {
                **hardening,
                **health("CMD", "node", "-e", "probe"),
                "command": ["npm", "run", "dev"],
                "ports": [{"host_ip": LOOPBACK, "target": 3000, "published": "3456"}],
                "environment": {
                    "NEXT_PUBLIC_AUTH_COOKIE_PREFIX": "probe",
                    "NEXT_PUBLIC_API_URL": "http://localhost:8765",
                },
            },
        },
        "volumes": {"pgdata": {}},
    }


RULES = [
    service_set_violations,
    port_violations,
    healthcheck_violations,
    db_probe_violations,
    app_probe_violations,
    hardening_violations,
    logging_violations,
    image_violations,
    db_volume_violations,
    postgres_settings_violations,
    redis_auth_violations,
    backend_migrate_violations,
    frontend_backend_agreement_violations,
]


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.__name__)
def test_the_compliant_control_passes_every_rule(rule):
    # A rule that flags a correct config is as useless as one that flags nothing.
    assert rule(compliant()) == []


def broken(mutate) -> dict:
    cfg = copy.deepcopy(compliant())
    mutate(cfg["services"], cfg)
    return cfg


def _drop(d, key):
    d.pop(key)


VIOLATIONS = {
    "a: no services": (service_set_violations, lambda s, c: s.clear()),
    "a: a service missing": (service_set_violations, lambda s, c: _drop(s, "redis")),
    "a: an extra service": (service_set_violations, lambda s, c: s.update(worker={})),
    "b: 0.0.0.0": (port_violations, lambda s, c: s["db"]["ports"][0].update(host_ip="0.0.0.0")),
    "b: empty host_ip": (
        port_violations,
        lambda s, c: s["frontend"]["ports"][0].update(host_ip=""),
    ),
    "b: no host_ip": (port_violations, lambda s, c: s["backend"]["ports"][0].pop("host_ip")),
    "b: published redis": (
        port_violations,
        lambda s, c: s["redis"].update(ports=[{"target": 6379, "published": "6379"}]),
    ),
    "e: no healthcheck": (healthcheck_violations, lambda s, c: _drop(s["backend"], "healthcheck")),
    "e: empty test": (healthcheck_violations, lambda s, c: s["db"]["healthcheck"].update(test=[])),
    "e: NONE": (
        healthcheck_violations,
        lambda s, c: s["redis"]["healthcheck"].update(test=["NONE"]),
    ),
    "e: disabled": (
        healthcheck_violations,
        lambda s, c: s["frontend"]["healthcheck"].update(disable=True),
    ),
    "e2: socket probe": (
        db_probe_violations,
        lambda s, c: s["db"]["healthcheck"].update(test=["CMD-SHELL", "pg_isready -U app -d app"]),
    ),
    "e2: socket directory as host": (
        db_probe_violations,
        lambda s, c: s["db"]["healthcheck"].update(
            test=["CMD", "pg_isready", "-h", "/var/run/postgresql", "-U", "app"]
        ),
    ),
    "e2: not pg_isready": (
        db_probe_violations,
        lambda s, c: s["db"]["healthcheck"].update(test=["CMD-SHELL", "true"]),
    ),
    "e3: live instead of ready": (
        app_probe_violations,
        lambda s, c: s["backend"]["healthcheck"].update(
            test=["CMD-SHELL", "curl -fs http://127.0.0.1:8000/api/health/live/"]
        ),
    ),
    "e3: not the health endpoint": (
        app_probe_violations,
        lambda s, c: s["backend"]["healthcheck"].update(test=["CMD-SHELL", "true"]),
    ),
    "f: no security_opt": (hardening_violations, lambda s, c: _drop(s["frontend"], "security_opt")),
    "f: no cap_drop": (hardening_violations, lambda s, c: _drop(s["db"], "cap_drop")),
    "f: partial cap_drop": (
        hardening_violations,
        lambda s, c: s["redis"].update(cap_drop=["NET_RAW"]),
    ),
    "f2: no logging": (logging_violations, lambda s, c: _drop(s["db"], "logging")),
    "f2: uncapped json-file": (
        logging_violations,
        lambda s, c: s["backend"].update(logging={"driver": "json-file"}),
    ),
    "g: latest": (image_violations, lambda s, c: s["db"].update(image="postgres:latest")),
    "g: no tag": (image_violations, lambda s, c: s["redis"].update(image="redis")),
    "g: major only": (image_violations, lambda s, c: s["db"].update(image="postgres:16")),
    "g: registry port, no tag": (
        image_violations,
        lambda s, c: s["db"].update(image="registry.local:5000/postgres"),
    ),
    "g: no images at all": (
        image_violations,
        lambda s, c: [svc.pop("image", None) for svc in s.values()],
    ),
    "h: bind-mounted db": (
        db_volume_violations,
        lambda s, c: s["db"]["volumes"][0].update(type="bind", source="./pgdata"),
    ),
    "h: undeclared volume": (db_volume_violations, lambda s, c: c.update(volumes={})),
    "h: no data mount": (db_volume_violations, lambda s, c: s["db"].update(volumes=[])),
    "i: a setting missing": (
        postgres_settings_violations,
        lambda s, c: s["db"].update(command=["postgres", "-c", "log_lock_waits=on"]),
    ),
    "i: no command": (postgres_settings_violations, lambda s, c: _drop(s["db"], "command")),
    "j: no requirepass": (
        redis_auth_violations,
        lambda s, c: s["redis"].update(command=["redis-server", "--save", ""]),
    ),
    "j: -a in the probe": (
        redis_auth_violations,
        lambda s, c: s["redis"]["healthcheck"].update(
            test=["CMD", "redis-cli", "-a", "$$REDIS_PASSWORD", "ping"]
        ),
    ),
    "j: -a inside a shell probe": (
        redis_auth_violations,
        lambda s, c: s["redis"]["healthcheck"].update(
            test=["CMD-SHELL", 'redis-cli -a "$$REDIS_PASSWORD" ping | grep -q PONG']
        ),
    ),
    "k: migrate in the command": (
        backend_migrate_violations,
        lambda s, c: s["backend"].update(
            command=["sh", "-c", "python manage.py migrate && python manage.py runserver"]
        ),
    ),
    "k: migrate in a string command": (
        backend_migrate_violations,
        lambda s, c: s["backend"].update(command="python manage.py migrate --noinput"),
    ),
    "k: migrate in the entrypoint": (
        backend_migrate_violations,
        lambda s, c: s["backend"].update(entrypoint=["python", "manage.py", "migrate"]),
    ),
    "l: cookie prefixes differ": (
        frontend_backend_agreement_violations,
        lambda s, c: s["frontend"]["environment"].update(NEXT_PUBLIC_AUTH_COOKIE_PREFIX="acme"),
    ),
    "l: frontend prefix missing": (
        frontend_backend_agreement_violations,
        lambda s, c: _drop(s["frontend"]["environment"], "NEXT_PUBLIC_AUTH_COOKIE_PREFIX"),
    ),
    "l: backend prefix missing": (
        frontend_backend_agreement_violations,
        lambda s, c: _drop(s["backend"]["environment"], "AUTH_COOKIE_PREFIX"),
    ),
    "l: CORS on the wrong port": (
        frontend_backend_agreement_violations,
        lambda s, c: s["backend"]["environment"].update(
            CORS_ALLOWED_ORIGINS="http://localhost:3000"
        ),
    ),
    "l: CORS missing": (
        frontend_backend_agreement_violations,
        lambda s, c: _drop(s["backend"]["environment"], "CORS_ALLOWED_ORIGINS"),
    ),
    "l: CSRF on the wrong port": (
        frontend_backend_agreement_violations,
        lambda s, c: s["backend"]["environment"].update(
            CSRF_TRUSTED_ORIGINS="http://localhost:3000"
        ),
    ),
    "l: frontend published elsewhere": (
        frontend_backend_agreement_violations,
        lambda s, c: s["frontend"]["ports"][0].update(published="3000"),
    ),
    "l: API URL on the wrong port": (
        frontend_backend_agreement_violations,
        lambda s, c: s["frontend"]["environment"].update(
            NEXT_PUBLIC_API_URL="http://localhost:8000"
        ),
    ),
}


@pytest.mark.parametrize("case", VIOLATIONS, ids=str)
def test_positive_control_each_violation_is_flagged(case):
    rule, mutate = VIOLATIONS[case]
    assert rule(broken(mutate)) != []


@pytest.mark.parametrize(
    "dockerfile",
    [
        "FROM python:3.12-slim\nRUN true\n",  # no USER: root
        "FROM python:3.12-slim\nUSER app\n",  # a name
        "FROM python:3.12-slim\nUSER 0:0\n",  # root, numerically
        "FROM python:3.12-slim\nUSER 1000\nUSER root\n",  # the last one wins
        "FROM node:22 AS deps\nUSER 1000\nFROM node:22-slim\nRUN true\n",  # not the final stage
    ],
)
def test_positive_control_f3_a_root_or_named_user_is_flagged(dockerfile):
    assert dockerfile_user_violations(dockerfile) != []


def test_control_f3_a_numeric_non_root_user_passes():
    assert (
        dockerfile_user_violations("FROM node:22 AS deps\nFROM node:22-slim\nUSER 1000:1000\n")
        == []
    )


@pytest.mark.parametrize(
    "text",
    [
        "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}",
        "url: postgres://app:${DB_PASSWORD:-x}@db/app",
        "DJANGO_SECRET_KEY: ${DJANGO_SECRET_KEY-unset}",
        "API_TOKEN: ${API_TOKEN}",
        "JWT_SIGNING_KEY: $JWT_SIGNING_KEY",
        "MFA_KEY: ${mfa_key:-lowercase}",
        "REDIS_PASSWORD: ${REDIS_PASSWORD:+set}",
    ],
)
def test_positive_control_d_a_secret_default_is_flagged(text):
    assert secret_interpolation_violations(text) != []


@pytest.mark.parametrize(
    "text",
    [
        "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?run setup}",
        # `$$` is the container's shell, not compose interpolation.
        'command: redis-server --requirepass "$$REDIS_PASSWORD"',
        "AUTH_COOKIE_PREFIX: ${AUTH_COOKIE_PREFIX:-acme}",  # not a secret
        "WEB_PORT: ${WEB_PORT:-3000}",
    ],
)
def test_control_d_compliant_text_passes(text):
    assert secret_interpolation_violations(text) == []
