"""
scripts/setup.sh, run against a sandbox copy with a stub `docker` and `curl` (OPERATIONS.md § 2,
BUILD_ORDER 4.1). The real script runs on Docker in the DAILY_CHANGES rehearsal; this proves the
properties that must never regress: secrets kept byte for byte, a taken port re-chosen and
persisted, a production env refused, no secret on stdout, and shell that parses.
"""

import importlib.util
import os
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from core.identity import cookie_prefix, product_slug

REPO = Path(__file__).resolve().parents[3]
ENVFILE = REPO / "scripts" / "lib" / "envfile.py"
SECRET_KEYS = {
    ".env": ("POSTGRES_PASSWORD", "REDIS_PASSWORD"),
    "backend/.env": ("SECRET_KEY", "JWT_SIGNING_KEY", "MFA_ENCRYPTION_KEY"),
}

# Answers the calls setup.sh makes; logs every invocation. `compose port` reports nothing (no stack
# running); a volume exists only if DBX_STUB_VOLUMES names it; the users query answers what
# DBX_STUB_HAS_USERS says, behind its marker and followed by a log line, as a real Django may;
# DBX_STUB_SHELL_FAILS and DBX_STUB_UP_FAILS make those calls fail.
STUB_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$DBX_STUB_LOG"
case "$*" in
  "compose version"|"info") exit 0 ;;
  "volume inspect "*)
    case " ${DBX_STUB_VOLUMES:-} " in *" $3 "*) exit 0 ;; *) exit 1 ;; esac ;;
  *" port "*) exit 1 ;;
  *"shell -c"*)
    if [ -n "${DBX_STUB_SHELL_FAILS:-}" ]; then echo "stub: connection refused" >&2; exit 1; fi
    echo "DBX_HAS_USERS=${DBX_STUB_HAS_USERS:-False}"
    echo "a log line after the answer"
    exit 0 ;;
  *"bootstrap_admin"*) echo "Created stub admin"; exit 0 ;;
  *" up "*)
    if [ -n "${DBX_STUB_UP_FAILS:-}" ]; then echo "stub: dependency failed" >&2; exit 1; fi
    exit 0 ;;
  *) exit 0 ;;
esac
"""
STUB_CURL = '#!/usr/bin/env bash\necho "curl $*" >> "$DBX_STUB_LOG"\nprintf 200\n'


def env_value(path: Path, key: str) -> str | None:
    for line in path.read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and name == key:
            return value
    return None


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "My Product"
    for rel in ("scripts", "backend/core"):
        shutil.copytree(REPO / rel, root / rel, ignore=shutil.ignore_patterns("__pycache__"))
    for rel in ("backend/.env.example", "frontend/.env.example", "docker-compose.yml"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, root / rel)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", STUB_DOCKER), ("curl", STUB_CURL)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    # The host's tools, minus docker and curl: a CI runner has a real /usr/bin/docker, and a test
    # that removes the stub must then find nothing, not the runner's daemon.
    # On Linux /bin is /usr/bin and some entries are dangling symlinks, so test by name
    # (lexists), not by whether the link's target resolves.
    tools = tmp_path / "tools"
    tools.mkdir()
    for directory in ("/usr/bin", "/bin"):
        for tool in Path(directory).iterdir():
            if tool.name not in {"docker", "curl"} and not os.path.lexists(tools / tool.name):
                (tools / tool.name).symlink_to(tool)
    return root, bin_dir, tmp_path / "docker.log"


def run(sandbox, *args, **extra_env):
    root, bin_dir, log = sandbox
    env = {
        "PATH": os.pathsep.join(
            [str(bin_dir), str(Path(sys.executable).parent), str(bin_dir.parent / "tools")]
        ),
        "HOME": os.environ.get("HOME", str(root)),
        "CI": "1",
        "DBX_STUB_LOG": str(log),
        "DBX_DISK_FLOOR_GB": "0",
        **extra_env,
    }
    return subprocess.run(
        ["bash", str(root / "scripts" / "setup.sh"), *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def secrets_of(root: Path) -> dict[str, str]:
    return {
        f"{rel}:{key}": env_value(root / rel, key)
        for rel, keys in SECRET_KEYS.items()
        for key in keys
    }


def test_first_run_writes_every_env_file_private_with_real_secrets(sandbox):
    root, _, _ = sandbox
    result = run(sandbox)
    assert result.returncode == 0, result.stderr

    for rel in (".env", "backend/.env", "frontend/.env.local"):
        mode = stat.S_IMODE((root / rel).stat().st_mode)
        assert mode == 0o600, f"{rel} is {oct(mode)}"
    assert env_value(root / ".env", "COMPOSE_PROJECT_NAME") == "my-product-dev"
    assert env_value(root / ".env", "AUTH_COOKIE_PREFIX") == "my_product"
    # The host runserver (--no-docker) reads backend/.env: it must agree with the frontend's.
    assert env_value(root / "backend/.env", "AUTH_COOKIE_PREFIX") == "my_product"
    # The slug comes from the directory (CONFIGURATION.md § 7), and the prefix is derived from it,
    # by the backend's own rule. The name is the owner's to set: setup never writes one.
    slug = env_value(root / "backend/.env", "PRODUCT_SLUG")
    assert slug == "my-product"
    assert cookie_prefix(slug) == env_value(root / "backend/.env", "AUTH_COOKIE_PREFIX")
    assert not env_value(root / "backend/.env", "PRODUCT_NAME")
    assert env_value(root / "frontend/.env.local", "NEXT_PUBLIC_AUTH_COOKIE_PREFIX") == "my_product"
    assert all(secrets_of(root).values()), secrets_of(root)
    assert len(env_value(root / ".env", "POSTGRES_PASSWORD")) == 48  # hex: DATABASE_URL-safe


def test_a_rerun_keeps_every_secret_and_file_byte_for_byte(sandbox):
    root, _, _ = sandbox
    assert run(sandbox).returncode == 0
    before = {rel: (root / rel).read_bytes() for rel in (".env", "backend/.env")}
    result = run(sandbox)
    assert result.returncode == 0, result.stderr
    assert {rel: (root / rel).read_bytes() for rel in before} == before
    assert "generated" not in result.stdout


def test_the_example_placeholder_secret_key_is_replaced_and_a_real_one_kept(sandbox):
    root, _, _ = sandbox
    result = run(sandbox)
    assert "replaced placeholder SECRET_KEY" in result.stdout
    real = env_value(root / "backend/.env", "SECRET_KEY")
    run(sandbox)
    assert env_value(root / "backend/.env", "SECRET_KEY") == real


def test_no_secret_value_reaches_the_output(sandbox):
    root, _, _ = sandbox
    result = run(sandbox, DBX_STUB_HAS_USERS="True")  # no admin made: nothing may be shown
    assert result.returncode == 0, result.stderr
    for value in secrets_of(root).values():
        assert value not in result.stdout and value not in result.stderr


def test_a_taken_persisted_port_is_re_chosen_and_persisted(sandbox):
    root, _, _ = sandbox
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        taken = probe.getsockname()[1]
    (root / ".env").write_text(f"API_PORT={taken}\n")

    with socket.socket() as holder:
        holder.bind(("127.0.0.1", taken))
        holder.listen()
        result = run(sandbox)

    assert result.returncode == 0, result.stderr
    assert f"API_PORT={taken} is taken" in result.stderr
    chosen = int(env_value(root / ".env", "API_PORT"))
    assert chosen != taken and chosen > taken


@pytest.mark.parametrize(
    "line", ["APP_ENV=production", "export APP_ENV=production", 'APP_ENV="staging"']
)
def test_a_production_like_backend_env_is_refused_and_left_alone(sandbox, line):
    root, _, _ = sandbox
    (root / "backend/.env").write_text(f"{line}\nSECRET_KEY=\n")
    before = (root / "backend/.env").read_bytes()
    result = run(sandbox)
    assert result.returncode == 1
    assert "only prepares a development checkout" in result.stderr
    assert (root / "backend/.env").read_bytes() == before
    assert not (root / ".env").exists()  # refused before anything was written


def test_an_existing_backend_env_without_app_env_is_refused_not_classified(sandbox):
    # core.env reads an absent APP_ENV as production-like (fail closed). Writing "development"
    # into the owner's file would be setup deciding that: it says what to add instead.
    root, _, log = sandbox
    (root / "backend/.env").write_text("SECRET_KEY=\nDEBUG=False\n")
    before = (root / "backend/.env").read_bytes()
    result = run(sandbox)
    assert result.returncode == 1
    assert "add APP_ENV=development" in result.stderr and "fix:" in result.stderr
    assert (root / "backend/.env").read_bytes() == before
    assert " up " not in (log.read_text() if log.exists() else "")


def test_a_new_backend_env_from_the_example_is_not_refused(sandbox):
    # The template ships APP_ENV=development: a brand-new file is setup's own to write.
    root, _, _ = sandbox
    assert not (root / "backend/.env").exists()
    result = run(sandbox)
    assert result.returncode == 0, result.stderr
    assert env_value(root / "backend/.env", "APP_ENV") == "development"


def test_migrate_runs_with_run_rm_and_the_admin_only_when_no_user_exists(sandbox):
    _, _, log = sandbox
    run(sandbox, DBX_STUB_HAS_USERS="True")
    calls = log.read_text()
    assert "run --rm -T backend uv run --frozen python manage.py migrate --noinput" in calls
    assert "bootstrap_admin" not in calls

    log.unlink()
    result = run(sandbox, DBX_STUB_HAS_USERS="False")
    assert "bootstrap_admin --email admin@example.com --no-input" in log.read_text()
    assert "-e BOOTSTRAP_ADMIN_PASSWORD" in log.read_text()  # by environment, never argv
    assert "Sign in:" in result.stdout


def test_missing_docker_fails_preflight_with_the_fix(sandbox):
    _, bin_dir, _ = sandbox
    (bin_dir / "docker").unlink()
    result = run(sandbox)
    assert result.returncode == 1
    assert "docker not found" in result.stderr and "fix:" in result.stderr


# --- The database volume, the stack's start, and the users probe ----------------------------------


def test_a_new_postgres_password_against_an_existing_volume_is_refused(sandbox):
    # Postgres reads POSTGRES_PASSWORD only when the volume is first created: a lost .env plus a
    # fresh password is a stack locked out of its own database. Stop before writing anything.
    root, _, log = sandbox
    result = run(sandbox, DBX_STUB_VOLUMES="my-product-dev_pgdata")
    assert result.returncode == 1
    assert "my-product-dev_pgdata already exists" in result.stderr
    assert "restore the .env" in result.stderr and "--reset" in result.stderr
    assert "rename this directory" in result.stderr
    assert not (root / ".env").exists()
    calls = log.read_text()
    assert "volume inspect my-product-dev_pgdata" in calls
    assert " up " not in calls and " build " not in calls


def test_the_refusal_names_compose_project_name_when_env_pins_the_name(sandbox):
    root, _, _ = sandbox
    (root / ".env").write_text("COMPOSE_PROJECT_NAME=my-product-dev\n")
    before = (root / ".env").read_bytes()
    result = run(sandbox, DBX_STUB_VOLUMES="my-product-dev_pgdata")
    assert result.returncode == 1
    assert "give COMPOSE_PROJECT_NAME in .env a new name" in result.stderr
    assert (root / ".env").read_bytes() == before


def test_a_kept_postgres_password_with_its_volume_is_a_normal_rerun(sandbox):
    _, _, log = sandbox
    assert run(sandbox).returncode == 0
    log.unlink()
    result = run(sandbox, DBX_STUB_VOLUMES="my-product-dev_pgdata")
    assert result.returncode == 0, result.stderr
    assert "volume inspect" not in log.read_text()  # a kept password needs no check


def test_the_stack_starts_with_fresh_anonymous_volumes_and_a_bounded_wait(sandbox):
    _, _, log = sandbox
    result = run(sandbox, DBX_HEALTH_TIMEOUT="77")
    assert result.returncode == 0, result.stderr
    ups = [line for line in log.read_text().splitlines() if " up " in line]
    assert ups and all("up -d --wait --wait-timeout 77" in line for line in ups)
    # The up that (re)creates the app services renews node_modules and .next.
    assert ups[-1].endswith("up -d --wait --wait-timeout 77 --renew-anon-volumes")
    assert "curl -s --max-time 5 " in log.read_text()


def test_a_failed_up_shows_the_logs_and_the_fix(sandbox):
    _, _, log = sandbox
    result = run(sandbox, DBX_STUB_UP_FAILS="1", DBX_HEALTH_TIMEOUT="9")
    assert result.returncode == 1
    assert "did not become healthy within 9s" in result.stderr
    assert "fix:" in result.stderr
    assert "logs --tail 30 db redis" in log.read_text()
    assert "migrate" not in log.read_text()  # it stopped there


def test_every_compose_call_names_this_checkout_whatever_the_shell_exports(sandbox):
    _, _, log = sandbox
    result = run(sandbox, COMPOSE_PROJECT_NAME="someone-elses-dev")
    assert result.returncode == 0, result.stderr
    compose_calls = [
        line for line in log.read_text().splitlines() if line.startswith("compose --project")
    ]
    assert compose_calls  # not an empty universe
    assert all(" -p my-product-dev " in line for line in compose_calls), compose_calls


def test_a_failing_users_query_stops_with_the_fix(sandbox):
    _, _, log = sandbox
    result = run(sandbox, DBX_STUB_SHELL_FAILS="1")
    assert result.returncode == 1
    assert "could not query users" in result.stderr and "fix:" in result.stderr
    assert "stub: connection refused" in result.stderr
    assert "bootstrap_admin" not in log.read_text()


def test_help_prints_the_header_and_nothing_after_it(sandbox):
    result = run(sandbox, "--help")
    assert result.returncode == 0
    assert "--admin-email ADDRESS" in result.stdout
    assert "set -euo" not in result.stdout and "#!" not in result.stdout


def test_reset_refuses_without_a_person_at_a_terminal(sandbox):
    _, _, log = sandbox
    run(sandbox)
    log.unlink()
    result = run(sandbox, "--reset")
    assert result.returncode == 1 and "needs a person at a terminal" in result.stderr
    assert "down -v" not in (log.read_text() if log.exists() else "")


@pytest.mark.parametrize(
    ("directory", "slug"),
    [("My Product", "my-product"), ("acme_ERP v2", "acme-erp-v2"), ("--x--", "x")],
)
def test_the_slug_is_normalised_by_the_one_function(directory, slug):
    script = f'. "{REPO}/scripts/lib/project.sh"; project_slug "{directory}"'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == slug


@pytest.mark.parametrize(
    "directory",
    [
        "My Product",
        "acme_ERP v2",
        "--x--",
        "a" * 50,
        "a" * 35 + "-b",  # the cut lands on a dash
        "Café Ünïon",
        "2024 report",
    ],
)
def test_the_shell_and_the_backend_slug_a_name_the_same_way(directory):
    # setup.sh writes the shell's slug as PRODUCT_SLUG and settings re-slugs it with core.identity:
    # if they disagreed, the backend's cookie prefix would drift from the frontend's.
    script = (
        f'. "{REPO}/scripts/lib/project.sh"; '
        'project_slug "$1"; cookie_prefix "$(project_slug "$1")"'
    )
    out = subprocess.run(
        ["bash", "-c", script, "-", directory], capture_output=True, text=True, check=True
    )
    shell_slug, shell_prefix = out.stdout.split()
    assert shell_slug == product_slug(directory)
    assert product_slug(shell_slug) == shell_slug  # settings keeps a slug setup wrote unchanged
    assert shell_prefix == cookie_prefix(shell_slug)


def test_every_script_parses():
    scripts = [REPO / "scripts/setup.sh", *sorted((REPO / "scripts/lib").glob("*.sh"))]
    assert len(scripts) >= 4  # not an empty universe
    for path in scripts:
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"{path.name}: {result.stderr}"


def test_shellcheck_is_clean():
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is not installed here (CI's ubuntu runner has it)")
    result = subprocess.run(
        [shellcheck, "-x", "setup.sh", "lib/log.sh", "lib/project.sh", "lib/ports.sh"],
        cwd=REPO / "scripts",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


# --- scripts/lib/envfile.py: reading, writing, permissions ---------------------------------------


@pytest.fixture(scope="module")
def envfile():
    spec = importlib.util.spec_from_file_location("setup_envfile", ENVFILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def envfile_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ENVFILE), *args], capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("line", "value"),
    [
        ("KEY=plain", "plain"),
        ("export KEY=exported", "exported"),
        ('KEY="double quoted"', "double quoted"),
        ("KEY='single quoted'", "single quoted"),
        ('export KEY="both"', "both"),
        ("KEY=  padded  ", "padded"),
        ("KEY=\"mismatched'", "\"mismatched'"),  # not one matching pair: kept as written
    ],
)
def test_get_reads_export_and_quotes_as_compose_and_environ_do(envfile, tmp_path, line, value):
    path = tmp_path / ".env"
    path.write_text(f"# KEY=a comment, never a value\nOTHER=x\n{line}\n")
    assert envfile.get(path, "KEY") == value


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("KEY=old", "KEY=new"),
        ("export KEY=old", "export KEY=new"),
        ('KEY="old"', 'KEY="new"'),
        ("export KEY='old'", "export KEY='new'"),
    ],
)
def test_put_replaces_the_line_in_place_never_a_duplicate(envfile, tmp_path, line, expected):
    path = tmp_path / ".env"
    path.write_text(f"FIRST=1\n{line}\nLAST=2\n")
    envfile.put(path, "KEY", "new")
    assert path.read_text().splitlines() == ["FIRST=1", expected, "LAST=2"]
    assert envfile.get(path, "KEY") == "new"


def test_set_on_an_exported_key_keeps_one_line(tmp_path):
    path = tmp_path / ".env"
    path.write_text("export API_PORT=8000\n")
    assert envfile_cli("set", str(path), "API_PORT", "8001").returncode == 0
    assert path.read_text() == "export API_PORT=8001\n"


def test_a_quoted_real_secret_is_kept_byte_for_byte(tmp_path):
    path = tmp_path / ".env"
    real = "Zq8" + "abcdefghijklmnopqrstuvwxyz0123456789-_ABCDEFGHIJKL"  # 53 chars, many distinct
    path.write_text(f'export SECRET_KEY="{real}"\n')
    before = path.read_bytes()
    result = envfile_cli("secret", str(path), "SECRET_KEY", "django")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "kept SECRET_KEY"
    assert path.read_bytes() == before


def test_ensure_makes_an_existing_file_private(tmp_path):
    path = tmp_path / ".env"
    path.write_text("KEY=value\n")
    path.chmod(0o644)
    result = envfile_cli("ensure", str(path))
    assert result.returncode == 0, result.stderr
    assert "kept .env" in result.stdout
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text() == "KEY=value\n"


def test_every_write_leaves_the_file_private(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=1\n")
    path.chmod(0o644)
    assert envfile_cli("set", str(path), "B", "2").returncode == 0
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_write_is_atomic_and_leaves_no_temporary_file(envfile, tmp_path):
    path = tmp_path / ".env"
    envfile.put(path, "A", "1")
    envfile.put(path, "B", "2")
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]
    assert path.read_text() == "A=1\nB=2\n"


def test_an_interrupted_write_keeps_the_old_file_and_cleans_up(envfile, tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("A=old\n")
    seen = {}

    def failing_replace(src, dst):
        seen["mode"] = stat.S_IMODE(os.stat(src).st_mode)
        raise OSError("disk full")

    monkeypatch.setattr(envfile.os, "replace", failing_replace)
    with pytest.raises(OSError):
        envfile.put(path, "A", "new")
    assert seen["mode"] == 0o600  # private from its first byte, before it was ever renamed
    assert path.read_text() == "A=old\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]


def test_needs_secret_answers_what_secret_would_do(tmp_path):
    path = tmp_path / ".env"
    assert envfile_cli("needs-secret", str(path), "POSTGRES_PASSWORD", "hex").returncode == 0
    path.write_text("POSTGRES_PASSWORD=changeme\n")
    assert envfile_cli("needs-secret", str(path), "POSTGRES_PASSWORD", "hex").returncode == 0
    assert envfile_cli("secret", str(path), "POSTGRES_PASSWORD", "hex").returncode == 0
    assert envfile_cli("needs-secret", str(path), "POSTGRES_PASSWORD", "hex").returncode == 1


# --- What setup.sh runs on the host: Python 3.9, no Django, no venv ------------------------------


def host_python(tmp_path: Path) -> tuple[str, dict]:
    """
    The oldest python3 setup.sh supports, if uv can find one here (stock macOS has 3.9); otherwise
    the python3 on PATH with this virtualenv removed. Never the venv's: it has Django installed.
    """
    venv_bin = Path(sys.executable).parent.resolve()
    path = os.pathsep.join(
        p
        for p in os.environ.get("PATH", "").split(os.pathsep)
        if p and Path(p).resolve() != venv_bin
    )
    env = {"PATH": path, "HOME": os.environ.get("HOME", str(tmp_path))}
    uv = shutil.which("uv")
    if uv:
        found = subprocess.run(
            [uv, "python", "find", "3.9"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**env, "UV_NO_CONFIG": "1"},
            check=False,
        )
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip(), env
    python3 = shutil.which("python3", path=path)
    if python3 is None:
        pytest.skip("no python3 outside the virtualenv")
    return python3, env


HOST_RUN = """
import runpy, sys
assert sys.prefix == sys.base_prefix, "this is a virtualenv's interpreter"
sys.argv = sys.argv[1:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as exc:
    assert not exc.code, f"exit {exc.code}"
leaked = sorted(m for m in sys.modules if m.split(".")[0] == "django")
assert not leaked, leaked
print("python", sys.version.split()[0])
"""


def test_secret_policy_imports_on_the_host_python(tmp_path):
    python, env = host_python(tmp_path)
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(REPO / 'backend')!r}); "
        "from core.secret_policy import generate; "
        "assert generate('fernet'); "
        "assert not [m for m in sys.modules if m.split('.')[0] == 'django']; "
        "print('python', sys.version.split()[0])"
    )
    result = subprocess.run(
        [python, "-I", "-c", code], capture_output=True, text=True, cwd=tmp_path, env=env
    )
    assert result.returncode == 0, result.stderr


def test_envfile_runs_on_the_host_python_without_django(tmp_path):
    python, env = host_python(tmp_path)
    target = tmp_path / "backend.env"

    def step(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [python, "-I", "-c", HOST_RUN, str(ENVFILE), *args],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=env,
        )

    for args in (
        ("refuse-production", str(target)),
        ("ensure", str(target), "--from", str(REPO / "backend/.env.example")),
        ("refuse-production", str(target)),
        ("secret", str(target), "SECRET_KEY", "django"),
        ("secret", str(target), "MFA_ENCRYPTION_KEY", "fernet"),
        ("set", str(target), "API_PORT", "8123"),
        ("get", str(target), "API_PORT"),
    ):
        result = step(*args)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    assert result.stdout.splitlines()[0] == "8123"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
