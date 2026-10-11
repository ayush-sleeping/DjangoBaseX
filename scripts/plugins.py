"""
Scaffold, link and list plugins (BUILD_ORDER 3.3; CORE_ARCHITECTURE_PLAN § 1, § 3, § 5).

Run from backend/ so the project's environment is active:

    cd backend && uv run python ../scripts/plugins.py new billing
    cd backend && uv run python ../scripts/plugins.py link billing
    cd backend && uv run python ../scripts/plugins.py list
    cd backend && uv run python ../scripts/plugins.py registry   # after removing a plugin

Standard library only. It reuses the platform's own validation (core.plugins, core.registry: both
stdlib-only) and never calls django.setup(): a scaffold must not need a database or settings.

Exit codes: 0 on success, 1 on any user error (a message on stderr, never a traceback).
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
TEMPLATE_DIR = Path(__file__).resolve().parent / "plugin_template"
DEFAULT_PLUGINS_DIR = BACKEND / "plugins"
DEFAULT_FRONTEND_DIR = REPO / "frontend" / "src" / "plugins"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.plugins import (  # noqa: E402 — backend/ must be on sys.path first
    RESERVED_LABELS,
    Plugin,
    PluginError,
    discover,
)
from core.registry import RESERVED_PREFIXES  # noqa: E402

TEMPLATE_SUFFIX = ".tmpl"
PACKAGE_SEGMENT = "__package__"
# Editor and OS droppings that may appear in the template tree; anything else must be a .tmpl.
IGNORED_TEMPLATE_FILES = frozenset({".DS_Store", "Thumbs.db"})
IGNORED_TEMPLATE_DIRS = frozenset({"__pycache__"})
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
# Tables are "<name>_<model>" and PostgreSQL truncates identifiers at 63 characters; 30 leaves the
# model half room, and keeps every generated line inside the 100-column limit.
MAX_NAME_LENGTH = 30
PLACEHOLDER = re.compile(r"\{\{\s*[^{}]*?\s*\}\}")
# The frontend's view of the linked plugins (BUILD_ORDER 3.5), read by the one catch-all route.
REGISTRY_FILE = "registry.generated.ts"
FRONTEND_ENTRIES = ("index.ts", "index.tsx")


class ScriptError(Exception):
    """A user error: printed to stderr, exit code 1."""


# --- new ----------------------------------------------------------------------------------------


def template_values(name: str) -> dict[str, str]:
    return {
        "name": name,
        "label": name,
        "package": f"djx_{name}",
        "route": name.replace("_", "-"),
        "class_name": "".join(part.capitalize() for part in name.split("_")) + "Config",
        "title": name.replace("_", " ").title(),
    }


def validate_name(name: str) -> None:
    if not NAME_PATTERN.match(name):
        raise ScriptError(
            f"invalid plugin name {name!r}: lowercase letters, digits and _, starting with a letter"
        )
    if len(name) > MAX_NAME_LENGTH:
        raise ScriptError(
            f"plugin name {name!r} is {len(name)} characters; the limit is {MAX_NAME_LENGTH} "
            "(table names are <name>_<model>, and PostgreSQL cuts identifiers at 63)"
        )
    if name in RESERVED_LABELS:
        raise ScriptError(f"plugin name {name!r} is reserved by the platform")
    route = name.replace("_", "-")
    if route in RESERVED_PREFIXES:
        raise ScriptError(f"plugin name {name!r} would mount at /api/{route}/, which core reserves")


def page_segments(frontend_dir: Path) -> set[str]:
    """
    First URL segments the frontend already serves outside plugins: every top-level directory of
    src/app/ and of its route groups, except (plugins) itself and dynamic [segments]. A static route
    beats the plugin catch-all, so a plugin mounted at one of these would never be reached.
    """
    app_dir = frontend_dir.parent / "app"
    segments: set[str] = set()
    if not app_dir.is_dir():
        return segments
    for entry in app_dir.iterdir():
        if not entry.is_dir() or entry.name.startswith(("[", "_", ".")):
            continue
        if entry.name.startswith("(") and entry.name.endswith(")"):
            if entry.name == "(plugins)":
                continue
            segments |= {
                child.name
                for child in entry.iterdir()
                if child.is_dir() and not child.name.startswith(("[", "_", ".", "("))
            }
        else:
            segments.add(entry.name)
    return segments


def refuse_shadowed(prefix: str, frontend_dir: Path) -> None:
    if prefix in page_segments(frontend_dir):
        raise ScriptError(
            f"the frontend already serves /{prefix} outside plugins, and a static route always "
            "wins over the plugin catch-all: the plugin's pages would never be reached. Rename it."
        )


def render(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def render_tree(template_dir: Path, destination: Path, values: dict[str, str]) -> list[Path]:
    """
    Generic: every *.tmpl under template_dir becomes a file under destination with the suffix
    dropped and placeholders filled, in its contents AND its path. A directory segment named
    __package__ becomes the package name. Adding a template file needs no change here.
    """
    if not template_dir.is_dir():
        raise ScriptError(f"template directory not found: {template_dir}")
    written = []
    for source in sorted(template_dir.rglob("*")):
        relative = source.relative_to(template_dir)
        if any(part in IGNORED_TEMPLATE_DIRS for part in relative.parts):
            continue
        if source.is_dir():
            continue
        if source.name in IGNORED_TEMPLATE_FILES:
            continue
        if not source.name.endswith(TEMPLATE_SUFFIX):
            raise ScriptError(f"template file without the {TEMPLATE_SUFFIX} suffix: {relative}")
        parts = [
            values["package"] if part == PACKAGE_SEGMENT else render(part, values)
            for part in relative.parts
        ]
        parts[-1] = parts[-1].removesuffix(TEMPLATE_SUFFIX)
        target = destination.joinpath(*parts)
        content = render(source.read_text(encoding="utf-8"), values)
        rendered_path = target.relative_to(destination).as_posix()
        for label, text in (("path", rendered_path), ("file", content)):
            leftover = PLACEHOLDER.search(text)
            if leftover:
                raise ScriptError(
                    f"unrendered placeholder {leftover.group(0)} in the {label} of template "
                    f"{relative} (known: {', '.join(sorted(values))})"
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(target)
    return written


def cmd_new(
    name: str,
    plugins_dir: Path,
    template_dir: Path = TEMPLATE_DIR,
    frontend_dir: Path = DEFAULT_FRONTEND_DIR,
) -> str:
    validate_name(name)
    refuse_shadowed(name.replace("_", "-"), frontend_dir)
    plugins_dir = plugins_dir.resolve()
    destination = plugins_dir / name
    if destination.exists() or destination.is_symlink():
        raise ScriptError(f"{destination} already exists; refusing to overwrite it")
    values = template_values(name)

    # Render into a scratch directory, then move into place, so a template error never leaves
    # a half-written plugin behind.
    plugins_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=plugins_dir.parent))
    try:
        render_tree(template_dir, scratch / name, values)
        # The platform's own discovery must accept the new plugin on its own: if not, the
        # template is wrong, and nothing has been written to plugins_dir yet.
        try:
            discover(scratch)
        except PluginError as exc:
            raise ScriptError(f"the template produced a plugin discovery refuses: {exc}") from None
        shutil.move(str(scratch / name), str(destination))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    # Then alongside every plugin already there (a label two directories declare, say). If the
    # set no longer passes, remove the new plugin rather than leave a broken boot behind.
    try:
        [plugin] = [p for p in discover(plugins_dir) if p.path == destination.resolve()]
    except PluginError as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ScriptError(
            f"discovery refuses the plugin set with {name} added, so it was removed again: {exc}"
        ) from None

    return "\n".join(
        [
            f"Created {destination} ({plugin.app}, version {plugin.version}).",
            "",
            "Next steps:",
            f"  1. Make it its own repository: cd {destination} && git init && git add -A && "
            f'git commit -m "feat: scaffold {name}"',
            "     (then add it to the product as a git submodule at that path).",
            f"  2. Link the frontend half: uv run python ../scripts/plugins.py link {name}",
            f"  3. Create and apply its tables: uv run python manage.py makemigrations {name} && "
            "uv run python manage.py migrate",
        ]
    )


# --- link ---------------------------------------------------------------------------------------


def _find(name: str, plugins_dir: Path) -> Plugin:
    for plugin in discover(plugins_dir):
        if plugin.name == name:
            return plugin
    raise ScriptError(f"no plugin named {name!r} under {plugins_dir}")


def link_status(plugin: Plugin, frontend_dir: Path) -> str:
    source = plugin.path / "frontend"
    target = frontend_dir / plugin.prefixes["frontend"]
    if not source.is_dir():
        return "no frontend/"
    if target.is_symlink():
        if target.resolve() == source.resolve():
            return "linked"
        return f"WRONG LINK → {os.readlink(target)}"
    if target.exists():
        return f"BLOCKED: {target} is not a symlink"
    return "not linked"


def cmd_link(name: str, plugins_dir: Path, frontend_dir: Path) -> str:
    validate_name(name)
    plugin = _find(name, plugins_dir)
    refuse_shadowed(plugin.prefixes["frontend"], frontend_dir)
    source = plugin.path / "frontend"
    if not source.is_dir():
        raise ScriptError(f"{plugin.name} has no frontend/ directory at {source}")

    frontend_dir.mkdir(parents=True, exist_ok=True)
    frontend_dir = frontend_dir.resolve()
    target = frontend_dir / plugin.prefixes["frontend"]
    # Relative, from the directory the link lives in, so the link survives the repository being
    # cloned somewhere else. Both ends resolved: macOS /var is itself a symlink to /private/var.
    relative = os.path.relpath(source.resolve(), frontend_dir)

    if target.is_symlink():
        if target.resolve() == source.resolve():
            registry = cmd_registry(plugins_dir, frontend_dir)
            return f"Already linked: {target} → {os.readlink(target)}\n{registry}"
        raise ScriptError(
            f"{target} is a link to {os.readlink(target)}, not to {relative}; remove it first"
        )
    if target.exists():
        raise ScriptError(f"{target} already exists and is not a link; refusing to replace it")
    os.symlink(relative, target, target_is_directory=True)
    return f"Linked {target} → {relative}\n{cmd_registry(plugins_dir, frontend_dir)}"


# --- registry -----------------------------------------------------------------------------------


def render_registry(entries: list[tuple[str, str]]) -> str:
    """The TypeScript for src/plugins/registry.generated.ts. entries: (frontend prefix, label).
    Imports are named plugin_<label>, so a plugin called `delete` cannot produce invalid TS."""
    lines = [
        "// Generated by `scripts/plugins.py link` — do not edit by hand (BUILD_ORDER 3.5).",
        "// One import per linked plugin, keyed by its frontend prefix. Empty in the boilerplate.",
        'import type { PluginFrontend } from "@/core/lib/plugin-pages";',
        "",
    ]
    for prefix, label in entries:
        lines.append(f'import plugin_{label} from "./{prefix}";')
    if entries:
        lines.append("")
        lines.append("export const plugins: Readonly<Record<string, PluginFrontend>> = {")
        lines.extend(f'  "{prefix}": plugin_{label},' for prefix, label in entries)
        lines.append("};")
    else:
        lines.append("export const plugins: Readonly<Record<string, PluginFrontend>> = {};")
    return "\n".join(lines) + "\n"


def linked_frontends(plugins_dir: Path, frontend_dir: Path) -> list[tuple[str, str]]:
    """(prefix, label) for every plugin that is linked AND ships frontend/index.ts(x)."""
    return [
        (plugin.prefixes["frontend"], plugin.label)
        for plugin in sorted(discover(plugins_dir), key=lambda p: p.prefixes["frontend"])
        if link_status(plugin, frontend_dir) == "linked"
        and any((plugin.path / "frontend" / entry).is_file() for entry in FRONTEND_ENTRIES)
    ]


def cmd_registry(plugins_dir: Path, frontend_dir: Path) -> str:
    frontend_dir.mkdir(parents=True, exist_ok=True)
    entries = linked_frontends(plugins_dir, frontend_dir)
    for prefix, _label in entries:
        refuse_shadowed(prefix, frontend_dir)
    target = frontend_dir / REGISTRY_FILE
    content = render_registry(entries)
    if target.is_file() and target.read_text(encoding="utf-8") == content:
        return f"{target} is up to date ({len(entries)} plugin(s))"
    target.write_text(content, encoding="utf-8")
    return f"Wrote {target} ({len(entries)} plugin(s))"


# --- list ---------------------------------------------------------------------------------------


def cmd_list(plugins_dir: Path, frontend_dir: Path) -> str:
    plugins = discover(plugins_dir)
    if not plugins:
        return "no plugins"
    rows = [
        (p.name, p.version, p.app, f"frontend: {link_status(p, frontend_dir)}") for p in plugins
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    return "\n".join(
        f"{n:<{widths[0]}}  {v:<{widths[1]}}  {a:<{widths[2]}}  {s}" for n, v, a, s in rows
    )


# --- CLI ----------------------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # a usage error is a user error: exit 1, like every other one
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="plugins.py", description=__doc__.split("\n\n")[0].strip())
    parser.add_argument(
        "--plugins-dir",
        type=Path,
        default=DEFAULT_PLUGINS_DIR,
        help=f"where plugins live (default: {DEFAULT_PLUGINS_DIR.relative_to(REPO)})",
    )
    parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=DEFAULT_FRONTEND_DIR,
        help="where frontend halves are linked "
        f"(default: {DEFAULT_FRONTEND_DIR.relative_to(REPO)})",
    )
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    new = commands.add_parser("new", help="scaffold a plugin from scripts/plugin_template/")
    new.add_argument("name")
    link = commands.add_parser("link", help="symlink a plugin's frontend/ into the frontend")
    link.add_argument("name")
    commands.add_parser("list", help="every discovered plugin and its frontend link")
    commands.add_parser("registry", help=f"regenerate the frontend's {REGISTRY_FILE}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "new":
            output = cmd_new(args.name, args.plugins_dir, frontend_dir=args.frontend_dir)
        elif args.command == "link":
            output = cmd_link(args.name, args.plugins_dir, args.frontend_dir)
        elif args.command == "registry":
            output = cmd_registry(args.plugins_dir, args.frontend_dir)
        else:
            output = cmd_list(args.plugins_dir, args.frontend_dir)
    except (ScriptError, PluginError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc.strerror or exc}: {exc.filename or ''}".rstrip(": "), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
