"""Plugin discovery (BUILD_ORDER 3.1; EXTENSIBILITY § 12, § 13, § 17; TECH_DEBT DB-18).

Every plugin tree is built in tmp_path. The fixture restores sys.path and sys.modules, so no test
leaks an importable djx_* package into another.
"""

import importlib
import logging
import sys
import textwrap
from pathlib import Path

import pytest

from core.plugins import (
    RESERVED_LABELS,
    Plugin,
    PluginError,
    add_to_path,
    discover,
    expected_prefixes,
    importable,
    installed_apps,
)


@pytest.fixture(autouse=True)
def _isolated_imports():
    path_before = list(sys.path)
    modules_before = set(sys.modules)
    yield
    sys.path[:] = path_before
    for name in set(sys.modules) - modules_before:
        if name.startswith("djx_"):
            del sys.modules[name]
    importlib.invalidate_caches()


def manifest(plugin="billing", **overrides) -> str:
    """A valid plugin.toml for `plugin`; overrides replace keys, None removes one."""
    fields = {
        "name": plugin,
        "label": plugin,
        "package": f"djx_{plugin}",
        "version": "1.4.0",
    }
    fields.update({k: v for k, v in overrides.items() if k != "prefixes"})
    lines = ["[plugin]"]
    for key, value in fields.items():
        if value is None:
            continue
        lines.append(f"{key} = {value!r}" if not isinstance(value, str) else f'{key} = "{value}"')
    prefixes = overrides.get("prefixes", expected_prefixes(plugin))
    if prefixes is not None:
        lines.append("[plugin.prefixes]")
        lines += [f'{kind} = "{value}"' for kind, value in prefixes.items()]
    return "\n".join(lines) + "\n"


def make_plugin(root: Path, directory: str, toml: str, *, package: str | None = None, init=""):
    """plugins/<directory>/plugin.toml, plus the package when `package` is given."""
    plugin_root = root / directory
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.toml").write_text(toml)
    if package:
        pkg = plugin_root / package
        pkg.mkdir()
        (pkg / "__init__.py").write_text(textwrap.dedent(init))
        (pkg / "apps.py").write_text(
            "from django.apps import AppConfig\n\n\n"
            f"class Config(AppConfig):\n    name = '{package}'\n    label = '{package[4:]}'\n"
        )
    return plugin_root


# --- The happy path -----------------------------------------------------------------------------


def test_a_valid_plugin_is_discovered_and_installed(tmp_path):
    make_plugin(
        tmp_path,
        "billing",
        manifest(app="djx_billing.apps.Config"),
        package="djx_billing",
    )
    [plugin] = discover(tmp_path)
    assert plugin == Plugin(
        name="billing",
        path=(tmp_path / "billing").resolve(),
        app="djx_billing.apps.Config",
        label="billing",
        version="1.4.0",
        prefixes={
            "table": "billing_",
            "permission": "billing",
            "route": "billing",
            "frontend": "billing",
        },
    )
    assert installed_apps(tmp_path) == ["djx_billing.apps.Config"]
    assert importlib.import_module("djx_billing.apps").Config.label == "billing"


def test_app_defaults_to_the_package(tmp_path):
    make_plugin(tmp_path, "crm", manifest("crm"), package="djx_crm")
    assert installed_apps(tmp_path) == ["djx_crm"]


def test_a_missing_plugins_dir_is_empty_not_an_error(tmp_path):
    assert discover(tmp_path / "nope") == []
    assert installed_apps(tmp_path / "nope") == []


def test_a_directory_without_a_manifest_is_ignored(tmp_path):
    (tmp_path / "half-cloned").mkdir()
    (tmp_path / "half-cloned" / "README.md").write_text("no manifest")
    assert discover(tmp_path) == []


def test_underscored_labels_get_hyphenated_url_prefixes(tmp_path):
    make_plugin(tmp_path, "credit_notes", manifest("credit_notes"))
    [plugin] = discover(tmp_path)
    assert plugin.prefixes == {
        "table": "credit_notes_",
        "permission": "credit_notes",
        "route": "credit-notes",
        "frontend": "credit-notes",
    }


# --- Order and sys.path -------------------------------------------------------------------------


def test_discovery_order_is_deterministic(tmp_path):
    for name in ("zeta", "alpha", "mid"):
        make_plugin(tmp_path, f"dir_{name}", manifest(name))
    make_plugin(tmp_path, "dir_late", manifest("late", order=500))
    make_plugin(tmp_path, "dir_first", manifest("first", order=1))
    names = [p.name for p in discover(tmp_path)]
    assert names == ["first", "alpha", "mid", "zeta", "late"]
    assert [p.name for p in discover(tmp_path)] == names


def test_add_to_path_is_idempotent_and_appends(tmp_path):
    make_plugin(tmp_path, "billing", manifest(), package="djx_billing")
    plugins = discover(tmp_path)
    first_entry = sys.path[0]
    add_to_path(plugins)
    add_to_path(plugins)
    entry = str((tmp_path / "billing").resolve())
    assert sys.path.count(entry) == 1
    assert sys.path[-1] == entry and sys.path[0] == first_entry  # nothing is shadowed
    installed_apps(tmp_path)
    assert sys.path.count(entry) == 1


# --- DB-18: absent vs broken --------------------------------------------------------------------


def test_a_plugin_whose_package_is_missing_is_skipped_with_a_warning(tmp_path, caplog):
    # The manifest is there (the submodule's plugin.toml), the package is not.
    make_plugin(tmp_path, "billing", manifest())
    make_plugin(tmp_path, "crm", manifest("crm"), package="djx_crm")
    with caplog.at_level(logging.WARNING, logger="core.plugins"):
        assert installed_apps(tmp_path) == ["djx_crm"]
    [record] = [r for r in caplog.records if r.name == "core.plugins"]
    assert "djx_billing not found" in record.getMessage()


def test_a_typo_inside_a_present_plugin_raises(tmp_path):
    make_plugin(
        tmp_path,
        "billing",
        manifest(),
        package="djx_billing",
        init="import djx_billing_helpers_typo  # a dependency that does not exist\n",
    )
    with pytest.raises(ModuleNotFoundError) as exc:
        installed_apps(tmp_path)
    assert exc.value.name == "djx_billing_helpers_typo"


def test_a_missing_submodule_of_the_plugin_itself_is_broken_not_absent(tmp_path):
    make_plugin(
        tmp_path,
        "billing",
        manifest(),
        package="djx_billing",
        init="from . import servics  # typo for services\n",
    )
    with pytest.raises(ImportError):
        installed_apps(tmp_path)


def test_any_other_error_inside_a_present_plugin_raises(tmp_path):
    make_plugin(tmp_path, "billing", manifest(), package="djx_billing", init="1 / 0\n")
    with pytest.raises(ZeroDivisionError):
        installed_apps(tmp_path)


def test_importable_directly(tmp_path):
    make_plugin(tmp_path, "crm", manifest("crm"), package="djx_crm")
    [plugin] = discover(tmp_path)
    add_to_path([plugin])
    assert importable(plugin) is True


# --- Schema errors: each names the file and the field -------------------------------------------


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"name": None}, "plugin.name"),
        ({"label": None}, "plugin.label"),
        ({"package": None}, "plugin.package"),
        ({"version": None}, "plugin.version"),
        ({"prefixes": None}, "plugin.prefixes"),
        ({"name": "Billing", "label": "Billing"}, "plugin.name"),
        ({"label": "invoices"}, "plugin.label"),
        ({"package": "billing"}, "plugin.package"),
        ({"package": "djx_other"}, "plugin.package"),
        ({"app": "other.apps.Config"}, "plugin.app"),
        ({"app": "djx_billingx.apps"}, "plugin.app"),
        ({"version": "latest"}, "plugin.version"),
        ({"version": ""}, "plugin.version"),
        ({"order": "first"}, "plugin.order"),
        ({"sdk_taget": "1.3"}, "plugin.sdk_taget"),  # a misspelt key is not silently ignored
        (
            {"prefixes": {"table": "billing_", "permission": "billing", "route": "billing"}},
            "plugin.prefixes.frontend",
        ),
        (
            {"prefixes": {"permission": "billing", "route": "billing", "frontend": "billing"}},
            "plugin.prefixes.table",
        ),
        (
            {"prefixes": {**expected_prefixes("billing"), "table": "bill_"}},
            "plugin.prefixes.table",
        ),
        (
            {"prefixes": {**expected_prefixes("billing"), "route": "payments"}},
            "plugin.prefixes.route",
        ),
        (
            {"prefixes": {**expected_prefixes("billing"), "cache": "billing"}},
            "plugin.prefixes.cache",
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_each_schema_error_names_the_file_and_field(tmp_path, overrides, field):
    make_plugin(tmp_path, "billing", manifest(**overrides))
    with pytest.raises(PluginError) as exc:
        discover(tmp_path)
    message = str(exc.value)
    assert str(tmp_path / "billing" / "plugin.toml") in message
    assert f": {field}:" in message


def test_an_implicit_label_says_so(tmp_path):
    make_plugin(tmp_path, "billing", manifest(label=None))
    with pytest.raises(PluginError, match="the label is never implicit"):
        discover(tmp_path)


def test_malformed_toml_names_the_file(tmp_path):
    make_plugin(tmp_path, "billing", "[plugin\nname = ")
    with pytest.raises(PluginError, match=r"billing/plugin\.toml: cannot be read as TOML"):
        discover(tmp_path)


def test_a_manifest_without_a_plugin_table_is_refused(tmp_path):
    make_plugin(tmp_path, "billing", 'title = "billing"\n')
    with pytest.raises(PluginError, match="title: unknown top-level key"):
        discover(tmp_path)


def test_optional_documented_keys_are_accepted(tmp_path):
    toml = manifest()
    toml = toml.replace(
        'version = "1.4.0"',
        'version = "1.4.0"\nsdk_target = "1.3"\ndescription = "Invoices."\n'
        'requires = ["crm>=1.0"]\nprovides = ["billing.totals.v1"]\nconsumes = []\n'
        'docs_url = "README.md"\nfrontend = { root = "frontend" }',
    )
    make_plugin(tmp_path, "billing", toml)
    assert [p.name for p in discover(tmp_path)] == ["billing"]


# --- Collisions and reserved names --------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(RESERVED_LABELS))
def test_a_reserved_platform_label_is_refused(tmp_path, label):
    make_plugin(tmp_path, label, manifest(label))
    with pytest.raises(PluginError, match=rf"plugin\.label: '{label}' is reserved"):
        discover(tmp_path)


@pytest.mark.parametrize("label", ["health", "schema", "docs", "me", "meta", "extensions"])
def test_a_label_whose_route_core_already_serves_is_refused(tmp_path, label):
    make_plugin(tmp_path, label, manifest(label))
    with pytest.raises(PluginError, match=rf"plugin\.prefixes\.route: /api/{label}/ is reserved"):
        discover(tmp_path)


def test_two_plugins_with_one_label_collide(tmp_path):
    make_plugin(tmp_path, "billing", manifest())
    make_plugin(tmp_path, "billing-fork", manifest())
    with pytest.raises(PluginError) as exc:
        discover(tmp_path)
    message = str(exc.value)
    assert "billing-fork/plugin.toml: plugin.label: 'billing' is already declared by" in message
    assert str(tmp_path / "billing" / "plugin.toml") in message


def test_overlapping_table_prefixes_collide(tmp_path):
    # "bill_" would claim "bill_ing_invoices" as well as its own tables.
    make_plugin(tmp_path, "bill", manifest("bill"))
    make_plugin(tmp_path, "bill_ing", manifest("bill_ing"))
    with pytest.raises(
        PluginError, match=r"plugin\.prefixes\.table: 'bill_ing_' collides with 'bill_'"
    ):
        discover(tmp_path)


def test_distinct_plugins_do_not_collide(tmp_path):
    for name in ("billing", "crm", "credit_notes", "bills"):
        make_plugin(tmp_path, name, manifest(name))
    assert len(discover(tmp_path)) == 4


def test_a_broken_manifest_fails_discovery_before_any_plugin_code_runs(tmp_path):
    # Discovery reads declarations only: a plugin whose code would explode is never imported if
    # another manifest is invalid, and validation never imports anything.
    make_plugin(tmp_path, "aaa", manifest("aaa"), package="djx_aaa", init="raise SystemExit(9)\n")
    make_plugin(tmp_path, "zzz", manifest("zzz", version="nope"))
    with pytest.raises(PluginError, match="plugin.version"):
        installed_apps(tmp_path)
    assert "djx_aaa" not in sys.modules
