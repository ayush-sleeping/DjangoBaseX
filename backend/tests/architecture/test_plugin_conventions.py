"""
Every plugin keeps the conventions (BUILD_ORDER 3.2; CORE_ARCHITECTURE_PLAN.md § 3, § 4, § 6).

Two halves. The first applies each rule in tests/architecture/plugin_rules.py to every INSTALLED
plugin. A boilerplate checkout has none, so the second half proves each rule can fail: the
scaffold from scripts/plugins.py passes them all, and a deliberately broken copy fails each one.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings
from django.db import models
from django.test.utils import isolate_apps

from core.plugins import add_to_path, discover
from core.registry import Registry, registry
from tests.architecture import plugin_rules as rules

REPO = Path(settings.BASE_DIR).parent
SCRIPT = REPO / "scripts" / "plugins.py"


def served_page_segments() -> set[str]:
    """scripts/plugins.py's page_segments() over the real frontend: one definition, two callers."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("plugins_script_for_conventions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    dont_write, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write
    return module.page_segments(module.DEFAULT_FRONTEND_DIR)


def installed_plugins():
    found = discover(Path(settings.BASE_DIR) / "plugins")
    present = [p for p in found if apps.is_installed(p.package)]
    # A boilerplate checkout has no plugins. Say so, rather than "empty parameter set".
    none = pytest.param(None, marks=pytest.mark.skip(reason="no plugin installed"), id="none")
    return present or [none]


# --- Every installed plugin ---------------------------------------------------------------------


@pytest.mark.parametrize("plugin", installed_plugins(), ids=lambda p: p.name)
def test_installed_plugin_imports_no_other_plugin_and_not_project(plugin):
    everyone = discover(Path(settings.BASE_DIR) / "plugins")
    problems = rules.boundary_problems(plugin, rules.forbidden_for(plugin, everyone))
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("plugin", installed_plugins(), ids=lambda p: p.name)
def test_installed_plugin_sets_its_label_names_its_tables_and_stays_in_its_lane(plugin):
    config = apps.get_app_config(plugin.label)
    problems = (
        rules.label_problems(plugin, type(config))
        + rules.model_problems(plugin, config.get_models())
        + rules.registration_problems(plugin, registry)
        + rules.shadow_problems(plugin, served_page_segments())
    )
    assert not problems, "\n".join(problems)


# --- The rules themselves, against the scaffold and broken copies --------------------------------


@pytest.fixture(scope="module")
def scaffold(tmp_path_factory):
    """`scripts/plugins.py new conv_probe`, discovered and importable."""
    plugins_dir = tmp_path_factory.mktemp("plugins")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--plugins-dir", str(plugins_dir), "new", "conv_probe"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    [plugin] = discover(plugins_dir)
    add_to_path([plugin])
    yield plugin
    sys.path.remove(str(plugin.path))
    for module in [m for m in sys.modules if m.split(".")[0] == plugin.package]:
        del sys.modules[module]


def write(plugin, relative: str, source: str) -> Path:
    path = plugin.path / plugin.package / relative
    path.write_text(source)
    return path


def test_the_scaffold_passes_the_boundary_rule(scaffold):
    assert rules.boundary_problems(scaffold, {"djx_other", "project"}) == []


@pytest.mark.parametrize(
    "source",
    [
        "import djx_other\n",
        "from djx_other.services import total\n",
        "from project import wiring\n",
        "import importlib\nimportlib.import_module('djx_other.models')\n",
    ],
)
def test_the_boundary_rule_flags_every_import_form(scaffold, source):
    path = write(scaffold, "leak.py", source)
    try:
        problems = rules.boundary_problems(scaffold, {"djx_other", "project"})
    finally:
        path.unlink()
    assert len(problems) == 1 and "leak.py" in problems[0], problems


def test_relative_imports_and_core_are_allowed(scaffold):
    path = write(scaffold, "fine.py", "from . import wiring\nfrom core.registry import registry\n")
    try:
        assert rules.boundary_problems(scaffold, {"djx_other", "project"}) == []
    finally:
        path.unlink()


def test_the_scaffold_sets_its_label_explicitly(scaffold):
    from djx_conv_probe.apps import ConvProbeConfig

    assert rules.label_problems(scaffold, ConvProbeConfig) == []


def test_the_label_rule_flags_an_inherited_or_wrong_label(scaffold):
    from django.apps import AppConfig

    class Derived(AppConfig):  # label left to Django: the app-label trap
        name = "djx_conv_probe"

    class Wrong(AppConfig):
        name = "djx_conv_probe"
        label = "other"

    assert "explicitly" in rules.label_problems(scaffold, Derived)[0]
    assert "plugin.toml says" in rules.label_problems(scaffold, Wrong)[0]


# Not "core": isolating it re-runs CoreConfig.ready(), and the one-way registry refuses that.
@isolate_apps("django.contrib.contenttypes")
def test_the_table_rule_flags_implicit_foreign_and_m2m_tables(scaffold):
    class Good(models.Model):  # noqa: DJ008 — a fixture, never shown
        class Meta:
            app_label = "contenttypes"
            db_table = "conv_probe_good"

    class Implicit(models.Model):  # noqa: DJ008 — a fixture, never shown
        class Meta:
            app_label = "contenttypes"

    class Foreign(models.Model):  # noqa: DJ008 — a fixture, never shown
        class Meta:
            app_label = "contenttypes"
            db_table = "billing_foreign"

    class Linked(models.Model):  # noqa: DJ008 — a fixture, never shown
        tags = models.ManyToManyField(Good, db_table="billing_tags")  # escapes the prefix

        class Meta:
            app_label = "contenttypes"
            db_table = "conv_probe_linked"

    assert rules.model_problems(scaffold, [Good]) == []
    problems = rules.model_problems(scaffold, [Implicit, Foreign, Linked])
    assert len(problems) == 3, problems
    assert "no explicit Meta.db_table" in problems[0]
    assert "billing_foreign" in problems[1]
    assert "M2M table" in problems[2]


def register_from_plugin(plugin, source: str) -> Registry:
    """Run `source`'s register(reg) from a module INSIDE the plugin, so the catalogs attribute it
    to the plugin the way they attribute a real wiring.py."""
    import importlib

    write(plugin, "probe_wiring.py", source)
    sys.modules.pop("djx_conv_probe.probe_wiring", None)
    try:
        reg = Registry()
        importlib.import_module("djx_conv_probe.probe_wiring").register(reg)
        return reg
    finally:
        (plugin.path / plugin.package / "probe_wiring.py").unlink()
        sys.modules.pop("djx_conv_probe.probe_wiring", None)


SETTING_DEF = """
from core.settings_registry import Int, SettingDef


def setting(key, module):
    return SettingDef(
        key=key, type=Int(min=1, max=9), default=5, label="A probe", description="d",
        group="Probes", module=module, changed_by_event="e", used_by=("Tests",),
    )
"""

SCAFFOLD_WIRING = (
    SETTING_DEF
    + """
from .wiring import GROUP, SECTION


def register(reg):
    reg.settings.register(setting("conv_probe.probe.limit", "conv_probe"))
    reg.permissions.register(GROUP)
    reg.api_routes.register(prefix="conv-probe", urlconf="djx_conv_probe.urls")
    reg.navigation.register(SECTION)
    reg.public_routes.register("conv_probe:home", "A probe route, public for this test only.")
"""
)

OUT_OF_LANE_WIRING = (
    SETTING_DEF
    + """
from core.registry import HealthCheck, NavItem, NavSection, PermissionGroupSpec, PermissionSpec


def register(reg):
    reg.settings.register(setting("security.probe.limit", "conv_probe"))
    # Impersonation: a group declared under another module's name, with that module's codes.
    reg.permissions.register(PermissionGroupSpec(
        code="users_extra", label="Extra", module="users",
        permissions=(PermissionSpec("users.extra.view", "View"),),
    ))
    reg.health.register(HealthCheck("database", "A key core will want", check=lambda: True))
    reg.api_routes.register(prefix="probe", urlconf="djx_conv_probe.urls")
    reg.navigation.register(NavSection(
        key="users", label="Probe", module="billing",
        items=(NavItem("x", "X", "/billing/x"),),
    ))
    reg.public_routes.register("users:extra", "Opened in another app's namespace.")
"""
)


def test_the_scaffold_registers_inside_its_prefixes(scaffold):
    reg = register_from_plugin(scaffold, SCAFFOLD_WIRING)
    assert reg.permissions.owner("conv_probe").startswith("djx_conv_probe.")  # attribution works
    assert rules.registration_problems(scaffold, reg) == []


def test_the_registration_rule_flags_each_way_out_of_the_lane(scaffold):
    reg = register_from_plugin(scaffold, OUT_OF_LANE_WIRING)
    problems = "\n".join(rules.registration_problems(scaffold, reg))
    assert "group 'users_extra' declares module 'users'" in problems
    assert "mounted at /api/probe/" in problems
    assert "nav section 'users' declares module 'billing'" in problems
    assert "nav section key 'users' must be 'conv-probe'" in problems
    assert "permission group code 'users_extra' must be 'conv_probe'" in problems
    assert "health check 'database' must be 'conv-probe'" in problems
    assert "links '/billing/x', outside /conv-probe/" in problems
    assert "public route 'users:extra'" in problems
    assert "setting 'security.probe.limit'" in problems  # reserved namespaces are core's


def test_the_shadow_rule_flags_a_prefix_the_frontend_already_serves(scaffold):
    assert rules.shadow_problems(scaffold, {"login", "users"}) == []
    assert "already serves /conv-probe" in rules.shadow_problems(scaffold, {"conv-probe"})[0]


def test_the_real_frontend_serves_its_core_pages_statically():
    assert {"login", "users", "settings", "account"} <= served_page_segments()


def test_registrations_by_other_modules_are_not_attributed_to_the_plugin(scaffold):
    reg = Registry()  # registered from this test module, not from the plugin
    reg.api_routes.register(prefix="probe", urlconf="djx_conv_probe.urls")
    assert rules.registration_problems(scaffold, reg) == []


def test_the_registration_rule_flags_a_urlconf_without_the_label_namespace(scaffold):
    write(scaffold, "urls_bad.py", 'app_name = "probe"\nurlpatterns = []\n')
    try:
        reg = register_from_plugin(
            scaffold,
            "def register(reg):\n"
            "    reg.api_routes.register(prefix='conv-probe', urlconf='djx_conv_probe.urls_bad')\n",
        )
        problems = rules.registration_problems(scaffold, reg)
    finally:
        (scaffold.path / scaffold.package / "urls_bad.py").unlink()
        sys.modules.pop("djx_conv_probe.urls_bad", None)
    assert any("app_name is 'probe'" in p for p in problems), problems
