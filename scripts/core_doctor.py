"""
Name every core file this checkout has changed (BUILD_ORDER 4.2; ENGINEERING_PRACTICES § 52).

Run from anywhere inside the repository:

    python3 scripts/core_doctor.py               # check: drift against core.manifest.json
    python3 scripts/core_doctor.py --json        # the same, as JSON for CI
    python3 scripts/core_doctor.py --verify      # is the manifest current? (core-guard, core repo)
    python3 scripts/core_doctor.py --write       # regenerate the manifest: the core repository ONLY
    python3 scripts/core_doctor.py --list-core PATH...   # which of these paths are core?

"Core" is a list, not a directory prefix (ADR-0010): the trees and single files below, written into
the manifest's header. A file is enumerated with `git ls-files -co --exclude-standard`, so an
UNTRACKED file under a core tree is drift too; a guard built on `git diff` is blind to it (§ 52).

Standard library only, so it runs before any environment exists.

Exit codes: 0 clean (or success), 1 drift (or a stale manifest under --verify), 2 a usage or setup
error: no manifest, not a git checkout, or --write outside the core repository. Expected errors are
a message on stderr, never a traceback.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MANIFEST = "core.manifest.json"
VERSION_FILE = "VERSION"
# The repository whose checkout may regenerate the manifest. CORE_REPOSITORY overrides it (tests).
CORE_REPOSITORY = "ayush-sleeping/DjangoBaseX"

# The core, as a list (ADR-0010). Deliberately absent: the composition points products edit
# (config/settings.py and urls.py, project/, plugins/, the frontend's (project) group, AGENTS.md,
# documentation/, examples/ and .github/).
CORE_TREES = (
    "backend/core/",
    "backend/users/",
    "backend/rbac/",
    "backend/tests/",
    "frontend/src/core/",
    "frontend/src/app/(core)/",
    "frontend/src/app/(plugins)/",
    "scripts/",
    ".claude/hooks/",
)
CORE_FILES = (
    "backend/conftest.py",
    "backend/config/settings_test.py",
    "docker-compose.yml",
)
IGNORED_DIRS = frozenset({"__pycache__"})
IGNORED_FILES = frozenset({".DS_Store"})

# git@github.com:OWNER/REPO.git, https://github.com/OWNER/REPO and https://github.com/OWNER/REPO.git
GITHUB_URL = re.compile(
    r"^(?:git@github\.com:|https://(?:[^@/]+@)?github\.com/)"
    r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

WAYS_FORWARD = """\
Ways forward, for each file above:
  1. Move the change into project/ (backend/project/, frontend/src/project/) or a plugin.
  2. Request a seam upstream in {repository}, so every product gets it and yours stays mergeable.
  3. If this is a deliberate core change, label the pull request `core-change`.
Never regenerate {manifest} in a product: it records the drift as correct (UPGRADING.md)."""


class SetupError(Exception):
    """A usage or setup error: printed to stderr, exit code 2."""


def git(root: Path | None, *args: str) -> str:
    command = ["git", "--literal-pathspecs"]
    if root is not None:
        command += ["-C", str(root)]
    try:
        result = subprocess.run(
            [*command, *args],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="surrogateescape",
        )
    except FileNotFoundError:
        raise SetupError("git is not installed or not on PATH.") from None
    if result.returncode != 0:
        raise SetupError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def find_root() -> Path:
    try:
        top = git(None, "rev-parse", "--show-toplevel").strip()
    except SetupError:
        raise SetupError(
            "not a git checkout: run core_doctor from inside the repository."
        ) from None
    return Path(top)


def read_version(root: Path) -> str:
    path = root / VERSION_FILE
    if not path.is_file():
        raise SetupError(f"{VERSION_FILE} is missing at the repository root.")
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        raise SetupError(f"{VERSION_FILE} is empty.")
    return version


def ignored(path: str) -> bool:
    parts = path.split("/")
    return parts[-1] in IGNORED_FILES or any(part in IGNORED_DIRS for part in parts[:-1])


def is_core(path: str, trees, files) -> bool:
    if path == MANIFEST or ignored(path):
        return False
    return path in files or any(path.startswith(tree) for tree in trees)


def enumerate_core(root: Path, trees, files) -> list[str]:
    """Every core file on disk: tracked, plus untracked files git does not ignore."""
    output = git(root, "ls-files", "-z", "-co", "--exclude-standard", "--", *trees, *files)
    found = {
        path
        for path in output.split("\0")
        if path and is_core(path, trees, files) and (root / path).is_file()
    }
    return sorted(found)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:  # bytes: a line-ending change is a real change
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def core_repository() -> str:
    return os.environ.get("CORE_REPOSITORY") or CORE_REPOSITORY


def build_manifest(root: Path) -> bytes:
    trees, files = list(CORE_TREES), list(CORE_FILES)
    manifest = {
        "version": read_version(root),
        "core_repository": core_repository(),
        "trees": trees,
        "files": files,
        "sha256": {path: sha256(root / path) for path in enumerate_core(root, trees, files)},
    }
    return (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")


def load_manifest(root: Path) -> dict:
    path = root / MANIFEST
    if not path.is_file():
        raise SetupError(
            f"{MANIFEST} is missing. It comes from the core repository; restore it from there."
        )
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SetupError(f"{MANIFEST} is not valid JSON: {exc}") from None
    if not isinstance(manifest, dict):
        raise SetupError(f"{MANIFEST} must hold a JSON object.")
    for key, kind in (("trees", list), ("files", list), ("sha256", dict)):
        if not isinstance(manifest.get(key), kind):
            raise SetupError(f"{MANIFEST} has no valid {key!r} entry.")
    for path in [*manifest["trees"], *manifest["files"], *manifest["sha256"]]:
        if not isinstance(path, str) or path.startswith("/") or ".." in path.split("/"):
            raise SetupError(f"{MANIFEST} lists a path outside the repository: {path!r}")
    return manifest


def drift(root: Path, manifest: dict) -> dict[str, list[str]]:
    recorded = manifest["sha256"]
    on_disk = set(enumerate_core(root, manifest["trees"], manifest["files"]))
    modified, missing = [], []
    for path in sorted(recorded):
        if not (root / path).is_file():
            missing.append(path)
        elif sha256(root / path) != recorded[path]:
            modified.append(path)
    added = sorted(on_disk - set(recorded))
    return {"modified": modified, "missing": missing, "added": added}


def print_drift(found: dict[str, list[str]]) -> None:
    for label in ("modified", "missing", "added"):
        for path in found[label]:
            print(f"{label.upper():<9} {path}")


def check(root: Path, as_json: bool) -> int:
    version = read_version(root)
    manifest = load_manifest(root)
    found = drift(root, manifest)
    clean = not any(found.values())
    if as_json:
        print(json.dumps({"version": version, "clean": clean, **found}, indent=2))
        return 0 if clean else 1
    print(f"core {version}")
    if clean:
        print(f"clean: {len(manifest['sha256'])} core files match {MANIFEST}")
        return 0
    print_drift(found)
    total = sum(len(paths) for paths in found.values())
    print(f"\n{total} core file(s) drifted from {MANIFEST}.")
    repository = manifest.get("core_repository") or CORE_REPOSITORY
    print(WAYS_FORWARD.format(repository=repository, manifest=MANIFEST))
    return 1


def origin_repository(root: Path) -> str:
    """OWNER/REPO named by the origin remote; a SetupError says why there is none."""
    try:
        url = git(root, "remote", "get-url", "origin").strip()
    except SetupError:
        raise SetupError("this checkout has no origin remote") from None
    match = GITHUB_URL.match(url)
    if match is None:
        # Never echo the URL itself: an https remote can carry a token.
        raise SetupError("origin is not a GitHub repository URL")
    return match.group("repo")


def write(root: Path) -> int:
    expected = core_repository()
    try:
        origin = origin_repository(root)
        seen = f"origin is {origin}"
    except SetupError as exc:
        origin, seen = None, str(exc)
    # GitHub repository names are case-insensitive.
    if origin is None or origin.casefold() != expected.casefold():
        raise SetupError(
            f"refusing to regenerate {MANIFEST}: {seen}, not the core repository {expected}.\n"
            "Regenerating in a product records its drift as correct, which makes the doctor\n"
            "report clean while the fork is still there (UPGRADING.md, 'If you edited core')."
        )
    content = build_manifest(root)
    (root / MANIFEST).write_bytes(content)
    count = len(json.loads(content)["sha256"])
    print(f"core {read_version(root)}: wrote {MANIFEST} ({count} files)")
    return 0


def verify(root: Path) -> int:
    version = read_version(root)
    manifest = load_manifest(root)
    expected = build_manifest(root)
    print(f"core {version}")
    if (root / MANIFEST).read_bytes() == expected:
        print(f"{MANIFEST} is current.")
        return 0
    current = json.loads(expected)
    for key in ("version", "core_repository", "trees", "files"):
        if manifest.get(key) != current[key]:
            print(f"HEADER    {key}: manifest has {manifest.get(key)!r}, now {current[key]!r}")
    print_drift(drift(root, {**manifest, "trees": current["trees"], "files": current["files"]}))
    print(
        f"\n{MANIFEST} is stale. Regenerate it in the core repository, in the same pull request:\n"
        "    python3 scripts/core_doctor.py --write"
    )
    return 1


def list_core(root: Path, paths: list[str]) -> int:
    manifest = load_manifest(root)
    for path in paths:
        relative = path.removeprefix("./")
        if is_core(relative, manifest["trees"], manifest["files"]):
            print(relative)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="core_doctor.py", description="Name every core file this checkout has changed."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="report drift as JSON")
    mode.add_argument("--write", action="store_true", help="regenerate the manifest (core only)")
    mode.add_argument("--verify", action="store_true", help="exit 1 if the manifest is stale")
    mode.add_argument(
        "--list-core", nargs="*", metavar="FILE", help="print which repo-relative paths are core"
    )
    args = parser.parse_args(argv)
    try:
        root = find_root()
        if args.write:
            return write(root)
        if args.verify:
            return verify(root)
        if args.list_core is not None:
            return list_core(root, args.list_core)
        return check(root, as_json=args.json)
    except (SetupError, OSError) as exc:
        print(f"core_doctor: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
