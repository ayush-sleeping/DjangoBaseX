"""
Read and fill env files for scripts/setup.sh (OPERATIONS.md § 2 steps 4 and 5).

Standard library only, plus backend/core's stdlib-only secret_policy and env modules, so it runs
before anything is installed, on the host's own python3: 3.9 or newer (stock macOS ships 3.9), so no
`match`, no 3.10+ standard library, and annotations stay strings. It never prints a value except
through `get`, which setup.sh captures into a variable and never echoes.

    envfile.py ensure    FILE [--from TEMPLATE]   create only if absent; chmod 600 either way
    envfile.py get       FILE KEY                 the value, or nothing
    envfile.py fill      FILE KEY VALUE           set only if absent or empty
    envfile.py set       FILE KEY VALUE           set unconditionally (a re-chosen port)
    envfile.py secret    FILE KEY KIND            generate only if absent, empty or a placeholder
    envfile.py needs-secret FILE KEY KIND         exit 0 if `secret` would generate, 1 if not
    envfile.py refuse-production FILE             exit 1 if FILE exists and its APP_ENV is absent or
                                                  production-like

Lines are read the way docker compose and django-environ read them: an optional `export ` prefix,
and one pair of matching surrounding quotes ("..." or '...') around the value. Every write is atomic
(a private temporary file in the same directory, fsync, rename) and leaves the file at mode 600.

Exit codes: 0 done, 1 refused, 2 usage error. Messages name keys, never values.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

from core.env import is_production_like  # noqa: E402 — stdlib-only, after the path is set
from core.secret_policy import GENERATORS, generate, is_placeholder  # noqa: E402

KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
# `[export ]KEY=VALUE`, the shape compose and django-environ accept. Comments never match.
LINE = re.compile(r"^(?P<export>\s*export\s+)?\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$")
PRIVATE = stat.S_IRUSR | stat.S_IWUSR  # 600: secrets live here


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _write_text(path: Path, text: str) -> None:
    """
    Replace `path` atomically: a reader sees the old file or the new one, never half of either,
    and an interrupted run leaves the old file intact. The temporary file is private from its first
    byte.
    """
    temp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE)
    try:
        try:
            os.fchmod(fd, PRIVATE)  # whatever the umask did
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    try:  # make the rename itself durable; best effort, not every platform allows it
        dir_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def _write(path: Path, lines: list[str]) -> None:
    _write_text(path, "\n".join(lines) + "\n")


def _unquote(raw: str) -> tuple[str, str]:
    """The value, and the quote character it was wrapped in ("" if none)."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1], value[0]
    return value, ""


def get(path: Path, key: str) -> str | None:
    for line in _read(path):
        match = LINE.match(line)
        if match and match.group("key") == key:
            return _unquote(match.group("value"))[0]
    return None


def put(path: Path, key: str, value: str) -> None:
    """Set `key`, in place on every line that holds it (keeping `export ` and the quote style)."""
    lines, done = _read(path), False
    for i, line in enumerate(lines):
        match = LINE.match(line)
        if match and match.group("key") == key:
            quote = _unquote(match.group("value"))[1]
            export = "export " if match.group("export") else ""
            lines[i], done = f"{export}{key}={quote}{value}{quote}", True
    if not done:
        lines.append(f"{key}={value}")
    _write(path, lines)


def _make_private(path: Path) -> bool:
    """chmod 600; True if the mode had to change."""
    if stat.S_IMODE(path.stat().st_mode) == PRIVATE:
        return False
    os.chmod(path, PRIVATE)
    return True


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    command, args = argv[0], argv[1:]
    try:
        if command == "ensure":
            path = Path(args[0])
            template = Path(args[2]) if len(args) == 3 and args[1] == "--from" else None
            if path.exists():
                changed = _make_private(path)
                print(f"kept {path.name}" + (" (made private: 600)" if changed else ""))
            else:
                text = template.read_text(encoding="utf-8") if template is not None else ""
                _write_text(path, text)
                print(f"created {path.name}")
            return 0
        if command == "get":
            value = get(Path(args[0]), args[1])
            if value:
                print(value)
            return 0
        if command in {"fill", "set", "secret", "needs-secret"}:
            path, key = Path(args[0]), args[1]
            if not KEY.match(key):
                print(f"not an env key: {key!r}", file=sys.stderr)
                return 2
            current = get(path, key)
            if command == "fill":
                if current:
                    print(f"kept {key}")
                    return 0
                put(path, key, args[2])
                print(f"set {key}")
                return 0
            if command == "set":
                put(path, key, args[2])
                print(f"set {key}")
                return 0
            kind = args[2]
            if kind not in GENERATORS:
                print(f"unknown secret kind {kind!r}", file=sys.stderr)
                return 2
            if command == "needs-secret":
                return 0 if is_placeholder(current, kind) else 1
            if not is_placeholder(current, kind):
                print(f"kept {key}")
                return 0
            put(path, key, generate(kind))
            print(f"generated {key}" if not current else f"replaced placeholder {key}")
            return 0
        if command == "refuse-production":
            path = Path(args[0])
            if not path.exists():
                return 0  # setup.sh creates it from the template, which says development
            app_env = get(path, "APP_ENV")
            if app_env is None:
                # Absent reads as production-like (core.env fails closed). Writing "development"
                # into it would be setup.sh deciding what this file is: the owner decides.
                print(
                    f"{path.name} exists and has no APP_ENV, which reads as production-like. "
                    "setup.sh only prepares a development checkout and will not decide that for "
                    f"you: if this is one, add APP_ENV=development to {path.name}, then re-run.",
                    file=sys.stderr,
                )
                return 1
            if is_production_like(app_env):
                print(
                    f"{path.name} declares APP_ENV={app_env}: setup.sh only prepares a "
                    "development checkout. It never writes a staging or production env file.",
                    file=sys.stderr,
                )
                return 1
            return 0
    except (IndexError, OSError) as exc:
        print(f"envfile.py {command}: {exc}", file=sys.stderr)
        return 2
    print(f"unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
