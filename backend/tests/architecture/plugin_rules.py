"""
The plugin conventions as checkable rules (CORE_ARCHITECTURE_PLAN.md § 3, § 4; BUILD_ORDER 3.2).

Pure functions over what a plugin declares, so the tests can run them against every installed
plugin AND against deliberately broken fixtures, proving each rule can fail. plugin.toml itself is
validated by core.plugins at boot. These rules check what a manifest cannot express: the code.
"""

import ast
import importlib

from core.plugins import Plugin

SKIP_DIRS = {"__pycache__", ".venv", "node_modules", "frontend"}


# --- § 4: a plugin imports no other plugin, and not the product -----------------------------------


def _imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module]
    if _is_dynamic_import(node):
        return [node.args[0].value]
    return []


def _type_checking_nodes(tree: ast.AST) -> set[int]:
    """ids of every node inside an `if TYPE_CHECKING:` body: the one place a plugin may name
    another plugin, and only its contracts module (EXTENSIBILITY § 18)."""
    inside: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            name = test.attr if isinstance(test, ast.Attribute) else getattr(test, "id", None)
            if name == "TYPE_CHECKING":
                for child in node.body:
                    inside.update(id(n) for n in ast.walk(child))
    return inside


def _plugin_sources(plugin: Plugin):
    for path in sorted(plugin.path.rglob("*.py")):
        if SKIP_DIRS & set(path.relative_to(plugin.path).parts):
            continue
        yield path, ast.parse(path.read_text(), filename=str(path))


def boundary_problems(plugin: Plugin, forbidden: set[str]) -> list[str]:
    """Absolute imports from `plugin`'s Python files whose top-level package is in `forbidden`.
    Exempt: `djx_<other>.contracts` under `if TYPE_CHECKING:` (typing only, no runtime coupling)."""
    found = []
    for path, tree in _plugin_sources(plugin):
        typing_only = _type_checking_nodes(tree)
        for node in ast.walk(tree):
            for name in _imported_names(node):
                if name.split(".")[0] not in forbidden:
                    continue
                if id(node) in typing_only and name.split(".")[1:2] == ["contracts"]:
                    continue
                where = f"{plugin.name}/{path.relative_to(plugin.path)}:{node.lineno}"
                found.append(f"{where} imports {name}")
    return found


SDK_ONLY = {"core", "users", "rbac"}


def sdk_problems(plugin: Plugin) -> list[str]:
    """§ 16: a plugin reaches the platform only through `core.sdk`. Any other `core.*`, and the
    users and rbac apps, are internals that a refactor moves without telling the plugin."""
    found = []
    for path, tree in _plugin_sources(plugin):
        if "tests" in path.relative_to(plugin.path).parts:
            continue  # a plugin's tests may use the platform's factories and clients
        for node in ast.walk(tree):
            for name in _imported_names(node):
                parts = name.split(".")
                if parts[0] in SDK_ONLY and parts[:2] != ["core", "sdk"]:
                    where = f"{plugin.name}/{path.relative_to(plugin.path)}:{node.lineno}"
                    found.append(f"{where} imports {name}; import it through core.sdk")
    return found


def _is_dynamic_import(node: ast.AST) -> bool:
    """importlib.import_module("djx_other") / __import__("djx_other") with a literal name."""
    if not isinstance(node, ast.Call) or not node.args:
        return False
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    first = node.args[0]
    return (
        called in {"import_module", "__import__"}
        and isinstance(first, ast.Constant)
        and isinstance(first.value, str)
    )


def shadow_problems(plugin: Plugin, served: set[str]) -> list[str]:
    """A static page at /<frontend> always beats the plugin catch-all: the plugin is unreachable."""
    prefix = plugin.prefixes["frontend"]
    if prefix in served:
        return [
            f"{plugin.name}: the frontend already serves /{prefix} outside plugins, so the "
            "plugin's pages are never reached (scripts/plugins.py page_segments)"
        ]
    return []


def forbidden_for(plugin: Plugin, everyone: list[Plugin]) -> set[str]:
    return {other.package for other in everyone if other.package != plugin.package} | {"project"}


# --- § 3: the explicit label and the four prefixes ---------------------------------------------


def label_problems(plugin: Plugin, app_config_cls: type) -> list[str]:
    """The app-label trap: `label` set ON THE CLASS, equal to the manifest's, `name` = package."""
    problems = []
    where = f"{plugin.name}: {app_config_cls.__module__}.{app_config_cls.__qualname__}"
    if "label" not in vars(app_config_cls):
        problems.append(f"{where} does not set `label` explicitly (CORE_ARCHITECTURE_PLAN § 3)")
    elif app_config_cls.label != plugin.label:
        problems.append(
            f"{where}.label is {app_config_cls.label!r}; plugin.toml says {plugin.label!r}"
        )
    if getattr(app_config_cls, "name", None) != plugin.package:
        problems.append(f"{where}.name must be the package {plugin.package!r}")
    return problems


def model_problems(plugin: Plugin, models) -> list[str]:
    """Every table is named explicitly and starts with the table prefix."""
    prefix = plugin.prefixes["table"]
    problems = []
    for model in models:
        meta = model._meta
        if meta.proxy or not meta.managed:
            continue
        name = f"{plugin.name}: {meta.label}"
        if "db_table" not in meta.original_attrs:
            problems.append(f"{name} has no explicit Meta.db_table (it must start {prefix!r})")
        elif not meta.db_table.startswith(prefix):
            problems.append(f"{name}.db_table {meta.db_table!r} does not start {prefix!r}")
        for field in meta.local_many_to_many:
            through = field.remote_field.through._meta
            if through.auto_created and not through.db_table.startswith(prefix):
                problems.append(
                    f"{name}.{field.name}: the M2M table {through.db_table!r} does not start "
                    f"{prefix!r}; set db_table on the field"
                )
    return problems


def registration_problems(plugin: Plugin, reg) -> list[str]:
    """
    Everything the plugin's own modules registered stays in its lane. Attribution is by the module
    that called register() (each catalog's owner()), not by what the spec claims, so a plugin
    registering under another module's name is caught rather than ignored.
    """
    label, route, frontend = plugin.label, plugin.prefixes["route"], plugin.prefixes["frontend"]

    def mine(catalog, key) -> bool:
        return catalog.owner(key).split(".")[0] == plugin.package

    def keyed(key: str, base: str, sep: str) -> bool:
        # A registry key is the plugin's own, or derived from it: a plugin that took "users" would
        # make core's own registration of it fail at boot later (keys are unique per catalog).
        return key == base or key.startswith(f"{base}{sep}")

    problems = []
    for group in reg.permissions.groups():
        if not mine(reg.permissions, group.code):
            continue
        # The registry already keeps every code inside group.module (A7); the module is the lane.
        if group.module != label:
            problems.append(
                f"{plugin.name}: permission group {group.code!r} declares module "
                f"{group.module!r}; this plugin's permissions are {label}.<feature>.<action>"
            )
        if not keyed(group.code, label, "_"):
            problems.append(
                f"{plugin.name}: permission group code {group.code!r} must be {label!r} or "
                f"start {label}_"
            )
    for check in reg.health.checks():
        if mine(reg.health, check.key) and not keyed(check.key, frontend, "-"):
            problems.append(
                f"{plugin.name}: health check {check.key!r} must be {frontend!r} or "
                f"start {frontend}-"
            )
    for api in reg.api_routes.routes():
        if not mine(reg.api_routes, api.prefix):
            continue
        if api.prefix != route:
            problems.append(f"{plugin.name}: mounted at /api/{api.prefix}/, not /api/{route}/")
        if api.urlconf.split(".")[0] != plugin.package:
            problems.append(f"{plugin.name}: mounts {api.urlconf}, outside {plugin.package}")
            continue
        app_name = getattr(importlib.import_module(api.urlconf), "app_name", None)
        if app_name != label:
            problems.append(
                f"{plugin.name}: {api.urlconf}.app_name is {app_name!r}; url names must be "
                f"{label}:<name>"
            )
    for section in reg.navigation.sections():
        if not mine(reg.navigation, section.key):
            continue
        if not keyed(section.key, frontend, "-"):
            problems.append(
                f"{plugin.name}: nav section key {section.key!r} must be {frontend!r} or "
                f"start {frontend}-"
            )
        if section.module != label:
            problems.append(
                f"{plugin.name}: nav section {section.key!r} declares module {section.module!r}"
            )
        for item in section.items:
            if item.href != f"/{frontend}" and not item.href.startswith(f"/{frontend}/"):
                problems.append(
                    f"{plugin.name}: nav item {section.key}/{item.key} links {item.href!r}, "
                    f"outside /{frontend}/"
                )
    for url_name in reg.public_routes.routes():
        if mine(reg.public_routes, url_name) and not url_name.startswith(f"{label}:"):
            problems.append(f"{plugin.name}: public route {url_name!r} is not {label}:<name>")
    for defn in reg.settings.defs():
        if not mine(reg.settings, defn.key):
            continue
        # The reserved namespaces (platform., security.) are core's (CONFIGURATION.md § 9.1).
        if defn.namespace != label or defn.module != label:
            problems.append(
                f"{plugin.name}: setting {defn.key!r} (module {defn.module!r}) must be "
                f"{label}.<group>.<name> with module {label!r}"
            )
    return problems
