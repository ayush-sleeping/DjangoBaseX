"""scripts/plugins.py: new, link and list (BUILD_ORDER 3.3). Everything happens under tmp_path."""

import ast
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core.plugins import add_to_path, discover, expected_prefixes, importable

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SCRIPT = REPO / "scripts" / "plugins.py"
TEMPLATE = REPO / "scripts" / "plugin_template"
LONGEST = "abcdefghij_klmnopqrst_uvwxyz_0"  # exactly 30 characters, the limit


def _load_script():
    spec = importlib.util.spec_from_file_location("plugins_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Loading by path would write scripts/__pycache__/ into the repository; scripts are not a
    # package and have no reason to carry one.
    before, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


script = _load_script()


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


@pytest.fixture
def dirs(tmp_path):
    return tmp_path / "plugins", tmp_path / "frontend" / "src" / "plugins"


def run(capsys, dirs, *args) -> tuple[int, str, str]:
    plugins_dir, frontend_dir = dirs
    code = script.main(
        ["--plugins-dir", str(plugins_dir), "--frontend-dir", str(frontend_dir), *args]
    )
    out, err = capsys.readouterr()
    return code, out, err


# --- new ----------------------------------------------------------------------------------------

EXPECTED_TREE = {
    ".gitignore",
    "README.md",
    "plugin.toml",
    "frontend/README.md",
    "frontend/index.ts",
    "frontend/home-page.tsx",
    "djx_credit_notes/__init__.py",
    "djx_credit_notes/apps.py",
    "djx_credit_notes/migrations/__init__.py",
    "djx_credit_notes/models.py",
    "djx_credit_notes/services.py",
    "djx_credit_notes/urls.py",
    "djx_credit_notes/views.py",
    "djx_credit_notes/wiring.py",
}


def files_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_new_renders_the_whole_tree_with_nothing_left_unrendered(capsys, dirs):
    code, out, _ = run(capsys, dirs, "new", "credit_notes")
    assert code == 0
    root = dirs[0] / "credit_notes"
    assert files_under(root) == EXPECTED_TREE
    for path in root.rglob("*"):
        assert "{{" not in str(path) and "__package__" not in str(path)
        if path.is_file():
            text = path.read_text()
            assert "{{" not in text and "}}" not in text, path
    assert "git init" in out and "link credit_notes" in out and "migrate" in out


def test_the_values_substituted(capsys, dirs):
    run(capsys, dirs, "new", "credit_notes")
    root = dirs[0] / "credit_notes"
    apps = (root / "djx_credit_notes" / "apps.py").read_text()
    assert "class CreditNotesConfig(AppConfig):" in apps
    assert 'verbose_name = "Credit Notes"' in apps
    wiring = (root / "djx_credit_notes" / "wiring.py").read_text()
    assert 'prefix="credit-notes"' in wiring and 'urlconf="djx_credit_notes.urls"' in wiring
    assert 'path="/credit-notes"' in wiring and 'code="credit_notes.home.view"' in wiring
    views = (root / "djx_credit_notes" / "views.py").read_text()
    assert 'required_permissions = ["credit_notes.home.view"]' in views


def test_the_label_is_explicit_in_apps_py(capsys, dirs):
    run(capsys, dirs, "new", "credit_notes")
    tree = ast.parse((dirs[0] / "credit_notes" / "djx_credit_notes" / "apps.py").read_text())
    [config] = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    assigned = {
        target.id: node.value.value
        for node in config.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(node.value, ast.Constant)
    }
    assert assigned["label"] == "credit_notes"
    assert assigned["name"] == "djx_credit_notes"
    assert assigned["default_auto_field"] == "django.db.models.BigAutoField"


def test_discovery_accepts_the_result_and_it_is_importable(capsys, dirs):
    run(capsys, dirs, "new", "credit_notes")
    [plugin] = discover(dirs[0])
    assert plugin.app == "djx_credit_notes.apps.CreditNotesConfig"
    assert plugin.version == "0.1.0"
    assert plugin.prefixes == expected_prefixes("credit_notes")
    add_to_path([plugin])
    assert importable(plugin) is True


@pytest.mark.parametrize("name", ["a", "credit_notes", LONGEST])
def test_every_generated_python_file_parses_and_passes_ruff(capsys, dirs, name):
    assert run(capsys, dirs, "new", name)[0] == 0
    root = dirs[0] / name
    python_files = sorted(root.rglob("*.py"))
    assert len(python_files) == 8
    for path in python_files:
        ast.parse(path.read_text(), filename=str(path))
    # The repository's own ruff configuration, as the backend gate applies it.
    for command in (["check"], ["format", "--check"]):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", *command, "--config", "pyproject.toml", str(root)],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "name, message",
    [
        ("Billing", "invalid plugin name 'Billing'"),
        ("2fa", "invalid plugin name '2fa'"),
        ("credit-notes", "invalid plugin name 'credit-notes'"),
        ("", "invalid plugin name ''"),
        (LONGEST + "x", "is 31 characters; the limit is 30"),
        ("users", "plugin name 'users' is reserved by the platform"),
        ("contenttypes", "plugin name 'contenttypes' is reserved by the platform"),
        ("health", "would mount at /api/health/, which core reserves"),
        ("me", "would mount at /api/me/, which core reserves"),
    ],
)
def test_new_refuses_bad_names(capsys, dirs, name, message):
    code, out, err = run(capsys, dirs, "new", name)
    assert code == 1
    assert message in err and "Traceback" not in err
    assert not (dirs[0] / name).exists() if name else True


def test_new_refuses_an_existing_directory(capsys, dirs):
    (dirs[0] / "billing").mkdir(parents=True)
    (dirs[0] / "billing" / "keep.txt").write_text("mine")
    code, _, err = run(capsys, dirs, "new", "billing")
    assert code == 1
    assert "already exists; refusing to overwrite it" in err
    assert (dirs[0] / "billing" / "keep.txt").read_text() == "mine"


def test_a_plugin_that_collides_with_an_existing_one_is_removed_again(capsys, dirs):
    # Another directory already declares the label "billing".
    run(capsys, dirs, "new", "billing")
    (dirs[0] / "billing").rename(dirs[0] / "billing-fork")
    code, _, err = run(capsys, dirs, "new", "billing")
    assert code == 1
    assert "discovery refuses the plugin set with billing added" in err
    assert "'billing' is already declared by" in err
    assert not (dirs[0] / "billing").exists()
    assert (dirs[0] / "billing-fork" / "plugin.toml").exists()


# --- The renderer is generic --------------------------------------------------------------------


@pytest.fixture
def template(tmp_path):
    copy = tmp_path / "template"
    shutil.copytree(TEMPLATE, copy)
    return copy


def test_new_template_files_render_without_touching_the_script(tmp_path, template):
    (template / "frontend" / "{{route}}").mkdir()
    (template / "frontend" / "{{route}}" / "page.tsx.tmpl").write_text(
        "export default function Page() {\n  return <h1>{{title}}</h1>; // {{package}}\n}\n"
    )
    (template / "frontend" / ".DS_Store").write_text("finder junk is ignored")
    script.cmd_new("credit_notes", tmp_path / "plugins", template_dir=template)
    page = tmp_path / "plugins" / "credit_notes" / "frontend" / "credit-notes" / "page.tsx"
    assert page.read_text() == (
        "export default function Page() {\n  return <h1>Credit Notes</h1>; // djx_credit_notes\n}\n"
    )
    assert not (tmp_path / "plugins" / "credit_notes" / "frontend" / ".DS_Store").exists()


def test_an_unknown_placeholder_is_an_error_and_writes_nothing(tmp_path, template):
    (template / "extra.md.tmpl").write_text("Owner: {{owner}}\n")
    with pytest.raises(script.ScriptError, match=r"unrendered placeholder \{\{owner\}\}"):
        script.cmd_new("credit_notes", tmp_path / "plugins", template_dir=template)
    assert not (tmp_path / "plugins" / "credit_notes").exists()
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []  # no scratch left


def test_an_unknown_placeholder_in_a_path_is_an_error(tmp_path, template):
    (template / "{{nope}}.md.tmpl").write_text("x\n")
    with pytest.raises(script.ScriptError, match=r"\{\{nope\}\} in the path"):
        script.cmd_new("credit_notes", tmp_path / "plugins", template_dir=template)


def test_a_template_file_without_the_suffix_is_an_error(tmp_path, template):
    (template / "stray.py").write_text("x = 1\n")
    with pytest.raises(script.ScriptError, match="without the .tmpl suffix: stray.py"):
        script.cmd_new("credit_notes", tmp_path / "plugins", template_dir=template)


def test_a_template_that_discovery_refuses_writes_nothing(tmp_path, template):
    toml = template / "plugin.toml.tmpl"
    toml.write_text(toml.read_text().replace('version = "0.1.0"', 'version = "latest"'))
    with pytest.raises(
        script.ScriptError, match="the template produced a plugin discovery refuses"
    ):
        script.cmd_new("credit_notes", tmp_path / "plugins", template_dir=template)
    assert not (tmp_path / "plugins" / "credit_notes").exists()


def test_the_shipped_template_is_all_tmpl_files():
    files = [p for p in TEMPLATE.rglob("*") if p.is_file() and p.name != ".DS_Store"]
    assert files and all(p.name.endswith(".tmpl") for p in files)


# --- link ---------------------------------------------------------------------------------------


def test_link_creates_a_relative_symlink_that_resolves(capsys, dirs):
    run(capsys, dirs, "new", "credit_notes")
    code, out, _ = run(capsys, dirs, "link", "credit_notes")
    assert code == 0 and "Linked" in out
    link = dirs[1] / "credit-notes"  # the route form of the name
    assert link.is_symlink()
    assert not os.path.isabs(os.readlink(link))
    assert link.resolve() == (dirs[0] / "credit_notes" / "frontend").resolve()
    assert (link / "README.md").exists()


def test_link_a_second_time_is_a_no_op(capsys, dirs):
    run(capsys, dirs, "new", "credit_notes")
    run(capsys, dirs, "link", "credit_notes")
    before = os.readlink(dirs[1] / "credit-notes")
    code, out, _ = run(capsys, dirs, "link", "credit_notes")
    assert code == 0 and "Already linked" in out
    assert os.readlink(dirs[1] / "credit-notes") == before


def test_link_refuses_a_real_directory(capsys, dirs):
    run(capsys, dirs, "new", "credit_notes")
    (dirs[1] / "credit-notes").mkdir(parents=True)
    code, _, err = run(capsys, dirs, "link", "credit_notes")
    assert code == 1 and "already exists and is not a link" in err


def test_link_refuses_a_link_that_points_elsewhere(capsys, dirs, tmp_path):
    run(capsys, dirs, "new", "credit_notes")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    dirs[1].mkdir(parents=True)
    os.symlink(elsewhere, dirs[1] / "credit-notes")
    code, _, err = run(capsys, dirs, "link", "credit_notes")
    assert code == 1 and "is a link to" in err and "remove it first" in err
    assert (dirs[1] / "credit-notes").resolve() == elsewhere.resolve()


def test_link_refuses_a_missing_plugin_or_frontend(capsys, dirs):
    code, _, err = run(capsys, dirs, "link", "credit_notes")
    assert code == 1 and "no plugin named 'credit_notes'" in err
    run(capsys, dirs, "new", "credit_notes")
    shutil.rmtree(dirs[0] / "credit_notes" / "frontend")
    code, _, err = run(capsys, dirs, "link", "credit_notes")
    assert code == 1 and "has no frontend/ directory" in err


# --- list ---------------------------------------------------------------------------------------


def test_list_with_no_plugins(capsys, dirs):
    assert run(capsys, dirs, "list")[:2] == (0, "no plugins\n")


def test_list_reports_every_plugin_and_its_link(capsys, dirs, tmp_path):
    for name in ("billing", "crm", "credit_notes", "zeta"):
        run(capsys, dirs, "new", name)
    run(capsys, dirs, "link", "billing")
    os.symlink(tmp_path, dirs[1] / "crm")  # a wrong link
    (dirs[1] / "credit-notes").mkdir()  # something that is not a link
    shutil.rmtree(dirs[0] / "zeta" / "frontend")
    code, out, _ = run(capsys, dirs, "list")
    assert code == 0
    lines = out.splitlines()
    assert [line.split()[0] for line in lines] == ["billing", "credit_notes", "crm", "zeta"]
    by_name = {line.split()[0]: line for line in lines}
    assert "0.1.0" in by_name["billing"] and "djx_billing.apps.BillingConfig" in by_name["billing"]
    assert by_name["billing"].endswith("frontend: linked")
    assert "frontend: WRONG LINK" in by_name["crm"]
    assert "frontend: BLOCKED" in by_name["credit_notes"]
    assert by_name["zeta"].endswith("frontend: no frontend/")


def test_list_with_a_bad_manifest_exits_1(capsys, dirs):
    run(capsys, dirs, "new", "billing")
    toml = dirs[0] / "billing" / "plugin.toml"
    toml.write_text(toml.read_text().replace('label = "billing"\n', ""))
    code, out, err = run(capsys, dirs, "list")
    assert code == 1 and out == ""
    assert "plugin.label: required and missing" in err


# --- The real CLI ---------------------------------------------------------------------------------


def cli(tmp_path, *args):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--plugins-dir",
            str(tmp_path / "plugins"),
            "--frontend-dir",
            str(tmp_path / "fe"),
            *args,
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_command_line_round_trip(tmp_path):
    assert cli(tmp_path, "new", "billing").returncode == 0
    assert cli(tmp_path, "link", "billing").returncode == 0
    listed = cli(tmp_path, "list")
    assert listed.returncode == 0 and "frontend: linked" in listed.stdout


@pytest.mark.parametrize(
    "args", [["new", "Bad Name"], ["link", "nothing"], [], ["frobnicate"], ["new"]]
)
def test_user_errors_exit_1_without_a_traceback(tmp_path, args):
    result = cli(tmp_path, *args)
    assert result.returncode == 1
    assert result.stderr.strip()
    assert "Traceback" not in result.stderr


def test_the_script_never_imports_or_sets_up_django():
    # By AST, not substring: the docstring is allowed to say so.
    tree = ast.parse(SCRIPT.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "setup", "the script calls something.setup()"
    assert "django" not in imported
    assert imported - set(sys.stdlib_module_names) == {"core"}


# --- registry (BUILD_ORDER 3.5) -------------------------------------------------------------------


def registry_text(dirs) -> str:
    return (dirs[1] / "registry.generated.ts").read_text()


def test_link_writes_the_frontend_registry_with_every_linked_plugin(capsys, dirs):
    for name in ("credit_notes", "alpha"):
        run(capsys, dirs, "new", name)
    run(capsys, dirs, "link", "credit_notes")
    code, out, _ = run(capsys, dirs, "link", "alpha")
    assert code == 0 and "Wrote" in out
    text = registry_text(dirs)
    assert 'import plugin_alpha from "./alpha";' in text
    assert 'import plugin_credit_notes from "./credit-notes";' in text
    assert text.index('"alpha": plugin_alpha') < text.index('"credit-notes": plugin_credit_notes')


def test_an_unlinked_plugin_or_one_without_index_is_left_out(capsys, dirs):
    run(capsys, dirs, "new", "alpha")
    run(capsys, dirs, "new", "beta")
    run(capsys, dirs, "link", "alpha")
    (dirs[0] / "alpha" / "frontend" / "index.ts").unlink()
    code, out, _ = run(capsys, dirs, "registry")
    assert code == 0 and "0 plugin(s)" in out
    assert registry_text(dirs) == script.render_registry([])


def test_registry_is_idempotent(capsys, dirs):
    run(capsys, dirs, "new", "alpha")
    run(capsys, dirs, "link", "alpha")
    code, out, _ = run(capsys, dirs, "registry")
    assert code == 0 and "up to date" in out


def test_a_reserved_word_name_still_makes_valid_identifiers():
    text = script.render_registry([("delete", "delete")])
    assert 'import plugin_delete from "./delete";' in text and '"delete": plugin_delete,' in text


def test_the_registry_in_the_tree_matches_the_plugins_linked_in_the_tree():
    # Empty in the boilerplate; one entry per linked plugin in a product. Either way, never stale.
    linked = script.linked_frontends(script.DEFAULT_PLUGINS_DIR, script.DEFAULT_FRONTEND_DIR)
    committed = script.DEFAULT_FRONTEND_DIR / script.REGISTRY_FILE
    assert committed.read_text() == script.render_registry(linked), (
        "frontend/src/plugins/registry.generated.ts is stale: run `plugins.py registry`"
    )


# --- a plugin may not mount where the frontend already serves a page (review finding) ------------


@pytest.fixture
def app_with_pages(dirs):
    app = dirs[1].parent / "app"
    for page in (
        "(core)/login",
        "(core)/settings/roles",
        "(project)/reports",
        "(plugins)/[plugin]",
    ):
        (app / page).mkdir(parents=True)
    (app / "[locale]").mkdir()
    return app


def test_page_segments_reads_route_groups_and_skips_dynamic_and_plugin_routes(dirs, app_with_pages):
    assert script.page_segments(dirs[1]) == {"login", "settings", "reports"}


@pytest.mark.parametrize("name", ["login", "settings", "reports"])
def test_new_refuses_a_name_the_frontend_already_serves(capsys, dirs, app_with_pages, name):
    code, _, err = run(capsys, dirs, "new", name)
    assert code == 1 and f"already serves /{name}" in err
    assert not (dirs[0] / name).exists()


def test_link_and_registry_refuse_a_plugin_a_new_core_page_now_shadows(capsys, dirs):
    run(capsys, dirs, "new", "reports")
    run(capsys, dirs, "link", "reports")
    (dirs[1].parent / "app" / "(core)" / "reports").mkdir(parents=True)  # a core update adds it
    code, _, err = run(capsys, dirs, "registry")
    assert code == 1 and "already serves /reports" in err
    code, _, err = run(capsys, dirs, "link", "reports")
    assert code == 1 and "already serves /reports" in err


def test_the_real_frontend_reserves_its_core_pages():
    segments = script.page_segments(script.DEFAULT_FRONTEND_DIR)
    assert {"login", "users", "settings", "account"} <= segments
