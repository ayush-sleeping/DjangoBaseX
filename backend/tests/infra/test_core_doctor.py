"""
scripts/core_doctor.py and core.manifest.json (BUILD_ORDER 4.2; ENGINEERING_PRACTICES § 52).

Every behaviour runs against a throwaway git repository in tmp_path holding a copy of the script,
never the real tree. The one exception reads the REAL committed manifest, to pin its header to the
core list ADR-0010 and § 52 define.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "core_doctor.py"
FAKE_CORE = "acme/core"

CORE_TREES = [
    "backend/core/",
    "backend/users/",
    "backend/rbac/",
    "backend/tests/",
    "frontend/src/core/",
    "frontend/src/app/(core)/",
    "frontend/src/app/(plugins)/",
    "scripts/",
    ".claude/hooks/",
]
CORE_FILES = [
    "backend/conftest.py",
    "backend/config/settings_test.py",
    "docker-compose.yml",
]

FIXTURE_FILES = {
    "VERSION": "9.8.7\n",
    ".gitignore": "__pycache__/\n*.log\n",
    "backend/core/models.py": "CORE = True\n",
    "backend/core/services.py": "def serve():\n    return 1\n",
    "backend/users/views.py": "USERS = 1\n",
    "backend/rbac/policy.py": "POLICY = 1\n",
    "frontend/src/core/lib/api.ts": "export const api = 1;\n",
    "frontend/src/app/(core)/login/page.tsx": "export default function Page() {}\n",
    "backend/conftest.py": "# root harness\n",
    "docker-compose.yml": "services: {}\n",
    # Product composition points: never core.
    "backend/config/settings.py": "DEBUG = False\n",
    "backend/config/urls.py": "urlpatterns = []\n",
    "backend/project/apps.py": "PROJECT = 1\n",
    "frontend/src/project/home.tsx": "export const home = 1;\n",
    "documentation/README.md": "# docs\n",
}


def git_env() -> dict[str, str]:
    """No GIT_* leaking in from the caller, and no global or system git config."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    env.pop("CORE_REPOSITORY", None)
    return env


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, env=git_env(), capture_output=True, text=True, check=True
    )
    return result.stdout


def doctor(repo: Path, *args: str, core: str | None = FAKE_CORE, cwd: Path | None = None):
    env = git_env()
    env["GIT_CEILING_DIRECTORIES"] = str(repo.parent)
    if core is not None:
        env["CORE_REPOSITORY"] = core
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "core_doctor.py"), *args],
        cwd=cwd or repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def make_repo(root: Path, origin: str = f"git@github.com:{FAKE_CORE}.git") -> Path:
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "remote", "add", "origin", origin)
    for rel, text in FIXTURE_FILES.items():
        write(root, rel, text)
    (root / "scripts").mkdir()
    shutil.copy2(SCRIPT, root / "scripts" / "core_doctor.py")
    return root


def commit_all(repo: Path) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "fixture")


@pytest.fixture
def repo(tmp_path):
    """A core checkout with a freshly written manifest, all committed."""
    root = make_repo(tmp_path / "core")
    result = doctor(root, "--write")
    assert result.returncode == 0, result.stderr
    commit_all(root)
    return root


def assert_no_traceback(result) -> None:
    assert "Traceback" not in result.stdout + result.stderr


# --- § 52's test -------------------------------------------------------------------------------


def test_a_clean_copy_exits_0(repo):
    result = doctor(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[0] == "core 9.8.7"
    assert "clean" in result.stdout


def test_a_modified_core_file_and_a_new_one_are_both_named_with_exit_1(repo):
    write(repo, "backend/core/services.py", "def serve():\n    return 2\n")
    write(repo, "backend/core/private_fork.py", "FORK = 1\n")

    result = doctor(repo)

    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert lines[0] == "core 9.8.7"
    assert "MODIFIED  backend/core/services.py" in lines
    assert "ADDED     backend/core/private_fork.py" in lines
    # Every drift report ends with the three ways forward.
    assert "project/" in result.stdout
    assert "seam upstream" in result.stdout
    assert "`core-change`" in result.stdout
    assert_no_traceback(result)


# --- drift classes -----------------------------------------------------------------------------


def test_a_deleted_core_file_is_missing(repo):
    (repo / "backend/rbac/policy.py").unlink()
    result = doctor(repo)
    assert result.returncode == 1
    assert "MISSING   backend/rbac/policy.py" in result.stdout.splitlines()


def test_an_untracked_file_under_a_core_tree_is_added(repo):
    # git diff cannot see this file; that blindness is why the doctor enumerates untracked too.
    write(repo, "frontend/src/app/(core)/secret/page.tsx", "export default 1;\n")
    assert git(repo, "diff", "--name-only", "HEAD") == ""
    result = doctor(repo)
    assert result.returncode == 1
    assert "ADDED     frontend/src/app/(core)/secret/page.tsx" in result.stdout.splitlines()


def test_a_listed_single_file_is_core(repo):
    write(repo, "docker-compose.yml", "services:\n  web: {}\n")
    result = doctor(repo)
    assert result.returncode == 1
    assert "MODIFIED  docker-compose.yml" in result.stdout.splitlines()


def test_a_listed_single_file_that_appears_later_is_added(repo):
    write(repo, "backend/config/settings_test.py", "FAST = True\n")
    result = doctor(repo)
    assert result.returncode == 1
    assert "ADDED     backend/config/settings_test.py" in result.stdout.splitlines()


def test_a_line_ending_change_is_a_modification(repo):
    (repo / "backend/core/models.py").write_bytes(b"CORE = True\r\n")
    result = doctor(repo)
    assert result.returncode == 1
    assert "MODIFIED  backend/core/models.py" in result.stdout.splitlines()


def test_changes_outside_core_are_clean(repo):
    write(repo, "backend/project/apps.py", "PROJECT = 2\n")
    write(repo, "backend/project/billing.py", "BILLING = 1\n")
    write(repo, "backend/config/settings.py", "DEBUG = True\n")
    write(repo, "backend/config/urls.py", "urlpatterns = [1]\n")
    write(repo, "backend/plugins/billing/apps.py", "X = 1\n")
    write(repo, "frontend/src/project/new.tsx", "export const x = 1;\n")
    write(repo, "frontend/src/app/(project)/page.tsx", "export default 1;\n")
    write(repo, "documentation/README.md", "# changed\n")
    result = doctor(repo)
    assert result.returncode == 0, result.stdout


def test_ignored_files_and_os_droppings_are_not_added(repo):
    write(repo, "backend/core/__pycache__/models.cpython-312.pyc", "bytecode")
    write(repo, "scripts/__pycache__/core_doctor.cpython-312.pyc", "bytecode")
    write(repo, "backend/core/.DS_Store", "finder")
    write(repo, "backend/core/debug.log", "ignored by .gitignore")
    result = doctor(repo)
    assert result.returncode == 0, result.stdout


def test_runs_from_a_subdirectory(repo):
    result = doctor(repo, cwd=repo / "backend" / "core")
    assert result.returncode == 0, result.stdout + result.stderr


# --- JSON --------------------------------------------------------------------------------------


def test_json_when_clean(repo):
    result = doctor(repo, "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "version": "9.8.7",
        "clean": True,
        "modified": [],
        "missing": [],
        "added": [],
    }


def test_json_on_drift(repo):
    write(repo, "backend/users/views.py", "USERS = 2\n")
    (repo / "backend/rbac/policy.py").unlink()
    write(repo, "backend/tests/test_new.py", "def test(): pass\n")
    result = doctor(repo, "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "version": "9.8.7",
        "clean": False,
        "modified": ["backend/users/views.py"],
        "missing": ["backend/rbac/policy.py"],
        "added": ["backend/tests/test_new.py"],
    }


# --- setup errors ------------------------------------------------------------------------------


@pytest.mark.parametrize("args", [(), ("--json",), ("--verify",), ("--list-core", "x")])
def test_no_manifest_is_a_setup_error(repo, args):
    (repo / "core.manifest.json").unlink()
    result = doctor(repo, *args)
    assert result.returncode == 2
    assert "core.manifest.json is missing" in result.stderr
    assert_no_traceback(result)


def test_a_corrupt_manifest_is_a_setup_error(repo):
    write(repo, "core.manifest.json", "{not json")
    result = doctor(repo)
    assert result.returncode == 2
    assert_no_traceback(result)


def test_outside_a_git_checkout_is_a_setup_error(tmp_path):
    plain = tmp_path / "plain"
    (plain / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, plain / "scripts" / "core_doctor.py")
    result = doctor(plain)
    assert result.returncode == 2
    assert "not a git checkout" in result.stderr
    assert_no_traceback(result)


def test_conflicting_modes_are_a_usage_error(repo):
    result = doctor(repo, "--write", "--verify")
    assert result.returncode == 2
    assert_no_traceback(result)


# --- --write -----------------------------------------------------------------------------------


def test_write_records_the_core_list_and_every_core_file(repo):
    manifest = json.loads((repo / "core.manifest.json").read_text())
    assert set(manifest) == {"version", "core_repository", "trees", "files", "sha256"}
    assert manifest["version"] == "9.8.7"
    assert manifest["core_repository"] == FAKE_CORE
    assert manifest["trees"] == CORE_TREES
    assert manifest["files"] == CORE_FILES
    assert sorted(manifest["sha256"]) == [
        "backend/conftest.py",
        "backend/core/models.py",
        "backend/core/services.py",
        "backend/rbac/policy.py",
        "backend/users/views.py",
        "docker-compose.yml",
        "frontend/src/app/(core)/login/page.tsx",
        "frontend/src/core/lib/api.ts",
        "scripts/core_doctor.py",
    ]
    assert "core.manifest.json" not in manifest["sha256"]
    assert all(len(sha) == 64 for sha in manifest["sha256"].values())


@pytest.mark.parametrize(
    "origin",
    [
        "git@github.com:someone/fork.git",
        "https://github.com/someone/fork",
        f"https://github.com/{FAKE_CORE}-product.git",
        "https://gitlab.com/acme/core.git",
    ],
)
def test_write_refuses_outside_the_core_repository(repo, origin):
    git(repo, "remote", "set-url", "origin", origin)
    write(repo, "backend/core/models.py", "CORE = 'patched'\n")
    before = (repo / "core.manifest.json").read_bytes()

    result = doctor(repo, "--write")

    assert result.returncode == 2
    assert "refusing" in result.stderr
    assert "drift as correct" in result.stderr
    assert "UPGRADING.md" in result.stderr
    assert (repo / "core.manifest.json").read_bytes() == before
    assert_no_traceback(result)


def test_write_refuses_without_an_origin(repo):
    git(repo, "remote", "remove", "origin")
    result = doctor(repo, "--write")
    assert result.returncode == 2
    assert "no origin remote" in result.stderr


def test_write_refuses_by_default_when_origin_is_not_the_real_core(repo):
    # With no CORE_REPOSITORY override, only the real core repository's name is accepted.
    result = doctor(repo, "--write", core=None)
    assert result.returncode == 2
    assert "ayush-sleeping/DjangoBaseX" in result.stderr


def test_write_never_echoes_the_origin_url(repo):
    git(repo, "remote", "set-url", "origin", "https://user:s3cr3t-token@example.com/acme/core.git")
    result = doctor(repo, "--write")
    assert result.returncode == 2
    assert "s3cr3t-token" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "origin",
    [
        f"git@github.com:{FAKE_CORE}.git",
        f"https://github.com/{FAKE_CORE}",
        f"https://github.com/{FAKE_CORE}.git",
        "https://github.com/ACME/Core.git",
    ],
)
def test_write_accepts_the_core_repository(tmp_path, origin):
    root = make_repo(tmp_path / "core", origin=origin)
    result = doctor(root, "--write")
    assert result.returncode == 0, result.stderr
    assert (root / "core.manifest.json").is_file()


def test_write_is_deterministic(repo):
    path = repo / "core.manifest.json"
    first = path.read_bytes()
    assert doctor(repo, "--write").returncode == 0
    assert path.read_bytes() == first
    assert first.endswith(b"}\n")
    assert b"\r" not in first
    # Sorted keys, two-space indent: byte for byte what json.dumps produces.
    assert first == (json.dumps(json.loads(first), sort_keys=True, indent=2) + "\n").encode()


def test_write_then_check_is_clean_after_a_core_change(repo):
    write(repo, "backend/core/services.py", "def serve():\n    return 3\n")
    assert doctor(repo).returncode == 1
    assert doctor(repo, "--write").returncode == 0
    assert doctor(repo).returncode == 0


# --- --verify ----------------------------------------------------------------------------------


def test_verify_passes_on_a_current_manifest(repo):
    result = doctor(repo, "--verify")
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda r: write(r, "backend/core/models.py", "CORE = False\n"), "MODIFIED"),
        (lambda r: write(r, "backend/rbac/new.py", "NEW = 1\n"), "ADDED"),
        (lambda r: (r / "backend/users/views.py").unlink(), "MISSING"),
        (lambda r: write(r, "VERSION", "9.9.0\n"), "HEADER    version"),
    ],
    ids=["modified", "added", "missing", "version"],
)
def test_verify_catches_a_stale_manifest(repo, change, expected):
    before = (repo / "core.manifest.json").read_bytes()
    change(repo)
    result = doctor(repo, "--verify")
    assert result.returncode == 1
    assert expected in result.stdout
    assert "stale" in result.stdout
    assert (repo / "core.manifest.json").read_bytes() == before


def test_verify_does_not_check_the_origin(repo):
    git(repo, "remote", "set-url", "origin", "git@github.com:someone/fork.git")
    assert doctor(repo, "--verify").returncode == 0


def test_verify_catches_a_hand_edited_header(repo):
    path = repo / "core.manifest.json"
    manifest = json.loads(path.read_text())
    manifest["trees"].remove("backend/rbac/")
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    result = doctor(repo, "--verify")
    assert result.returncode == 1
    assert "HEADER    trees" in result.stdout


# --- --list-core -------------------------------------------------------------------------------


def test_list_core_classifies_paths(repo):
    paths = {
        "backend/core/models.py": True,
        "backend/core/deleted_in_this_pr.py": True,
        "backend/users/views.py": True,
        "backend/rbac/policy.py": True,
        "backend/tests/infra/test_x.py": True,
        "frontend/src/core/lib/api.ts": True,
        "frontend/src/app/(core)/login/page.tsx": True,
        "frontend/src/app/(plugins)/[...slug]/page.tsx": True,
        "scripts/setup.sh": True,
        ".claude/hooks/agent_guard.py": True,
        "backend/conftest.py": True,
        "backend/config/settings_test.py": True,
        "docker-compose.yml": True,
        "./backend/core/services.py": True,
        "backend/config/settings.py": False,
        "backend/config/urls.py": False,
        "backend/project/apps.py": False,
        "backend/plugins/billing/apps.py": False,
        "frontend/src/project/home.tsx": False,
        "frontend/src/app/(project)/page.tsx": False,
        "frontend/src/plugins/registry.generated.ts": False,
        "AGENTS.md": False,
        "documentation/INDEX.md": False,
        "examples/plugins/notes/apps.py": False,
        ".github/workflows/core-guard.yml": False,
        ".claude/settings.json": False,
        "core.manifest.json": False,
        "backend/core/__pycache__/x.pyc": False,
        "backend/coreish/x.py": False,
        "docker-compose.override.yml": False,
    }
    result = doctor(repo, "--list-core", *paths)
    assert result.returncode == 0, result.stderr
    expected = [path.removeprefix("./") for path, core in paths.items() if core]
    assert result.stdout.splitlines() == expected


def test_list_core_with_no_paths_prints_nothing(repo):
    result = doctor(repo, "--list-core")
    assert result.returncode == 0
    assert result.stdout == ""


# --- the real manifest -------------------------------------------------------------------------


def test_the_committed_manifest_header_is_the_core_list():
    manifest = json.loads((REPO / "core.manifest.json").read_text())
    assert manifest["trees"] == CORE_TREES
    assert manifest["files"] == CORE_FILES
    assert manifest["core_repository"] == "ayush-sleeping/DjangoBaseX"
    assert manifest["version"] == (REPO / "VERSION").read_text().strip()
    assert "core.manifest.json" not in manifest["sha256"]
    assert "scripts/core_doctor.py" in manifest["sha256"]
