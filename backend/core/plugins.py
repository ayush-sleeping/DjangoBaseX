"""
Plugin discovery (BUILD_ORDER 3.1; CORE_ARCHITECTURE_PLAN § 1, § 3; EXTENSIBILITY § 12, § 13, § 17).

config/settings.py calls `INSTALLED_APPS += installed_apps(BASE_DIR / "plugins")`, before
django.setup(). So this module is standard library only (plus core.registry, which is too), and it
reads DECLARATIONS: each plugin's plugin.toml, parsed with tomllib and validated in full before any
plugin code runs. Adding a plugin edits no settings list.

The manifest (EXTENSIBILITY § 17), minimal schema:

    [plugin]
    name    = "billing"                       # required; == label
    label   = "billing"                       # required, explicit (the app-label trap, § 3)
    package = "djx_billing"                   # required; "djx_" + name
    version = "1.4.0"                         # required
    app     = "djx_billing.apps.BillingConfig"  # optional; defaults to package
    order   = 100                             # optional; a tie-break only, nothing may depend on it
    # optional and not yet acted on: description, sdk_target, requires, provides, consumes,
    # docs_url, [plugin.frontend]

    [plugin.prefixes]                         # required, all four, each derived from the label
    table      = "billing_"
    permission = "billing"
    route      = "billing"
    frontend   = "billing"

Absent vs broken (TECH_DEBT DB-18, EXTENSIBILITY § 13): a plugin whose own package cannot be found
is ABSENT (a submodule never initialised) and is skipped with a warning. Anything else that fails
to import, including a ModuleNotFoundError for a different module imported inside the plugin, is
BROKEN and propagates, so the deploy gate fails instead of the plugin silently vanishing.
"""

import importlib
import logging
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.registry import RESERVED_PREFIXES

logger = logging.getLogger("core.plugins")

MANIFEST = "plugin.toml"
DEFAULT_ORDER = 100

# Django app labels the platform already uses: a plugin taking one would collide in migrations,
# admin URLs and permission codes.
RESERVED_LABELS = frozenset(
    {"core", "users", "rbac", "project", "config", "admin", "auth", "contenttypes", "sessions"}
)
PREFIX_KINDS = ("table", "permission", "route", "frontend")

_LABEL = re.compile(r"^[a-z][a-z0-9_]*$")
_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_VERSION = re.compile(r"^\d+(\.\d+)*([-+.][0-9A-Za-z.-]+)?$")

_REQUIRED = ("name", "label", "package", "version", "prefixes")
_OPTIONAL = (
    "app",
    "order",
    "description",
    "sdk_target",
    "requires",
    "provides",
    "consumes",
    "docs_url",
    "frontend",
)


@dataclass(frozen=True)
class Plugin:
    name: str
    path: Path  # the plugin root: the directory holding plugin.toml and the package
    app: str  # what goes in INSTALLED_APPS: the dotted AppConfig, or the package
    label: str
    version: str
    prefixes: dict[str, str]  # table / permission / route / frontend

    @property
    def package(self) -> str:
        """The top-level package: what must be importable from `path`."""
        return self.app.split(".", 1)[0]


class PluginError(Exception):
    """A plugin manifest the platform refuses. Names the file and the field."""


# --- Discovery ----------------------------------------------------------------------------------


def discover(plugins_dir: Path) -> list[Plugin]:
    """Every plugins_dir/*/plugin.toml, validated, sorted by (order, name). [] without the dir."""
    plugins_dir = Path(plugins_dir)
    if not plugins_dir.is_dir():
        return []
    found: list[tuple[int, Plugin, Path]] = []
    for manifest in sorted(plugins_dir.glob(f"*/{MANIFEST}")):
        order, plugin = _load(manifest)
        found.append((order, plugin, manifest))
    found.sort(key=lambda entry: (entry[0], entry[1].name))
    _check_collisions(found)
    return [plugin for _, plugin, _ in found]


def _load(manifest: Path) -> tuple[int, Plugin]:
    def fail(field: str, problem: str) -> PluginError:
        return PluginError(f"{manifest}: {field}: {problem}")

    try:
        document = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PluginError(f"{manifest}: cannot be read as TOML: {exc}") from None

    unknown_tables = sorted(set(document) - {"plugin"})
    if unknown_tables:
        raise fail(unknown_tables[0], "unknown top-level key; everything lives under [plugin]")
    meta = document.get("plugin")
    if not isinstance(meta, dict):
        raise fail("[plugin]", "missing")

    for key in _REQUIRED:
        if key not in meta:
            hint = " (the label is never implicit: set it explicitly)" if key == "label" else ""
            raise fail(f"plugin.{key}", f"required and missing{hint}")
    unknown = sorted(set(meta) - set(_REQUIRED) - set(_OPTIONAL))
    if unknown:
        # A misspelt key (sdk_taget) must not be silently ignored (EXTENSIBILITY § 17).
        raise fail(f"plugin.{unknown[0]}", "unknown key")

    name = _string(meta, "name", fail)
    if not _LABEL.match(name):
        raise fail("plugin.name", "lowercase letters, digits and _, starting with a letter")
    label = _string(meta, "label", fail)
    if label != name:
        raise fail("plugin.label", f"must equal plugin.name ({name!r}): one name, one label")
    if label in RESERVED_LABELS:
        raise fail("plugin.label", f"{label!r} is reserved by the platform")

    package = _string(meta, "package", fail)
    if package != f"djx_{name}":
        raise fail("plugin.package", f"must be 'djx_{name}' (one package per plugin, § 1)")
    app = _string(meta, "app", fail) if "app" in meta else package
    if not _DOTTED.match(app) or (app != package and not app.startswith(f"{package}.")):
        raise fail("plugin.app", f"must be {package!r} or a dotted path inside it")

    version = _string(meta, "version", fail)
    if not _VERSION.match(version):
        raise fail("plugin.version", "not a version (e.g. 1.4.0)")

    order = meta.get("order", DEFAULT_ORDER)
    if not isinstance(order, int) or isinstance(order, bool):
        raise fail("plugin.order", "must be an integer")

    prefixes = _prefixes(meta["prefixes"], label, fail)
    return order, Plugin(
        name=name,
        path=manifest.parent.resolve(),
        app=app,
        label=label,
        version=version,
        prefixes=prefixes,
    )


def _string(meta: dict[str, Any], key: str, fail) -> str:
    value = meta[key]
    if not isinstance(value, str) or not value.strip():
        raise fail(f"plugin.{key}", "must be a non-empty string")
    return value.strip()


def expected_prefixes(label: str) -> dict[str, str]:
    """The four prefixes a label implies (CORE_ARCHITECTURE_PLAN § 3). Declared, then checked."""
    url = label.replace("_", "-")
    return {"table": f"{label}_", "permission": label, "route": url, "frontend": url}


def _prefixes(declared: Any, label: str, fail) -> dict[str, str]:
    if not isinstance(declared, dict):
        raise fail("plugin.prefixes", "must be a table with table, permission, route, frontend")
    for kind in PREFIX_KINDS:
        if kind not in declared:
            raise fail(f"plugin.prefixes.{kind}", "required and missing")
    unknown = sorted(set(declared) - set(PREFIX_KINDS))
    if unknown:
        raise fail(f"plugin.prefixes.{unknown[0]}", "unknown prefix kind")
    expected = expected_prefixes(label)
    prefixes = {}
    for kind in PREFIX_KINDS:
        value = declared[kind]
        if value != expected[kind]:
            raise fail(
                f"plugin.prefixes.{kind}",
                f"must be {expected[kind]!r}: every prefix derives from the label (§ 3)",
            )
        prefixes[kind] = value
    if prefixes["route"] in RESERVED_PREFIXES:
        raise fail("plugin.prefixes.route", f"/api/{prefixes['route']}/ is reserved for core")
    return prefixes


def _check_collisions(found: list[tuple[int, Plugin, Path]]) -> None:
    seen_labels: dict[str, Path] = {}
    seen_prefixes: dict[tuple[str, str], Path] = {}
    for _, plugin, manifest in found:
        if plugin.label in seen_labels:
            raise PluginError(
                f"{manifest}: plugin.label: {plugin.label!r} is already declared by "
                f"{seen_labels[plugin.label]}"
            )
        seen_labels[plugin.label] = manifest
        for kind, value in plugin.prefixes.items():
            for (other_kind, other_value), other_manifest in seen_prefixes.items():
                if other_kind != kind:
                    continue
                # Tables share one namespace: "bill_" would also claim "bill_ing_invoices".
                overlaps = (
                    value.startswith(other_value) or other_value.startswith(value)
                    if kind == "table"
                    else value == other_value
                )
                if overlaps:
                    raise PluginError(
                        f"{manifest}: plugin.prefixes.{kind}: {value!r} collides with "
                        f"{other_value!r} declared by {other_manifest}"
                    )
            seen_prefixes[(kind, value)] = manifest


# --- Loading ------------------------------------------------------------------------------------


def add_to_path(plugins: list[Plugin]) -> None:
    """Make each plugin's package importable. Idempotent; appended, so nothing is shadowed."""
    for plugin in plugins:
        entry = str(plugin.path)
        if entry not in sys.path:
            sys.path.append(entry)


def importable(plugin: Plugin) -> bool:
    """
    DB-18, exactly. Import the plugin's package:
      - ModuleNotFoundError naming the plugin's OWN top-level package → absent: warn, False;
      - anything else, including ModuleNotFoundError for any other module → broken: propagates.
    """
    try:
        importlib.import_module(plugin.package)
    except ModuleNotFoundError as exc:
        if exc.name == plugin.package:
            logger.warning(
                "plugin %s: package %s not found under %s; skipped. Is the submodule initialised?",
                plugin.name,
                plugin.package,
                plugin.path,
                extra={"plugin": plugin.name},
            )
            return False
        raise
    return True


def installed_apps(plugins_dir: Path) -> list[str]:
    """The INSTALLED_APPS entries for every present plugin, in discovery order."""
    plugins = discover(plugins_dir)
    add_to_path(plugins)
    return [plugin.app for plugin in plugins if importable(plugin)]
