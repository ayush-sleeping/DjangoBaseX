"""
The one scope every anti-hard-coding scan walks (CONFIGURATION.md § 18, BUILD_ORDER 5.6).

Production code only: the platform apps, `project/`, installed plugins, `config/`, and the
repository's `scripts/`. Tests, migrations and fixtures are excluded by PATH, never by comment, so a
scan can be neither tripped nor silenced from inside the scanned file.

Parsing only: nothing here imports application code.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent

PYTHON_ROOTS = (
    BACKEND / "core",
    BACKEND / "users",
    BACKEND / "rbac",
    BACKEND / "project",
    BACKEND / "plugins",
    BACKEND / "config",
    REPO / "scripts",
)
FRONTEND_ROOT = REPO / "frontend" / "src"

SKIPPED_DIRS = frozenset(
    {"tests", "migrations", "fixtures", "__pycache__", "node_modules", "plugin_template"}
)


def is_test_file(path: Path) -> bool:
    return path.name in {"tests.py", "conftest.py"} or path.name.startswith("test_")


def _walk(root: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
    if not root.exists():
        return
    for path in sorted(p for suffix in suffixes for p in root.rglob(f"*{suffix}")):
        parts = path.relative_to(root).parts[:-1]
        if any(part in SKIPPED_DIRS or part.startswith(".") for part in parts):
            continue
        if not is_test_file(path) and path.is_file():
            yield path


def iter_python_sources(roots=PYTHON_ROOTS) -> Iterator[Path]:
    for root in roots:
        yield from _walk(root, (".py",))


def iter_frontend_sources(root: Path = FRONTEND_ROOT) -> Iterator[Path]:
    for path in _walk(root, (".ts", ".tsx")):
        if not path.name.endswith((".test.ts", ".test.tsx", ".generated.ts")):
            yield path


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:  # a positive control's tmp file
        return path.name


@dataclass(frozen=True)
class Hit:
    """One offence. `key` is what an allow-list entry names: path + the offending value, never a
    line number (lines churn) and never a whole file (that excuses the next offender too)."""

    path: str
    line: int
    value: str

    @property
    def key(self) -> str:
        return f"{self.path}::{self.value}"

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.value}"


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def docstring_nodes(tree: ast.AST) -> set[int]:
    """ids of the string constants that are docstrings, which are prose, not values."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def string_constants(tree: ast.AST) -> Iterator[ast.Constant]:
    """Every str constant that is a value: docstrings excluded, f-string parts included."""
    prose = docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose:
            yield node
