"""
The platform never imports the product (ADR-0010, CORE_ARCHITECTURE_PLAN.md § 1).

Platform apps may import only each other, Django and third-party packages. Every other first-party
package under backend/ (project, config, tests, and any app a product adds later) is off limits:
dependencies point inward, registration points outward.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
# The platform layer. A new platform app must be added here — ADR-0010's one convention.
PLATFORM_APPS = ("core", "users", "rbac")
SKIP_DIRS = {"__pycache__", ".venv", "node_modules"}


def is_test_file(path: Path) -> bool:
    # Tests may use the shared harness (tests.factories); the rule governs code that ships.
    return (
        path.name in {"tests.py", "conftest.py"}
        or path.name.startswith("test_")
        or ("tests" in path.parts[:-1])
    )


def first_party_packages(root: Path = BACKEND) -> set[str]:
    return {
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "__init__.py").exists() and p.name not in SKIP_DIRS
    }


def forbidden_imports(app_dir: Path, forbidden: set[str]) -> list[str]:
    found = []
    for path in sorted(app_dir.rglob("*.py")):
        if SKIP_DIRS & set(path.parts) or is_test_file(path.relative_to(app_dir.parent)):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in forbidden:
                    found.append(f"{path.relative_to(app_dir.parent)}:{node.lineno} imports {name}")
    return found


def test_the_platform_never_imports_product_or_composition_code():
    forbidden = first_party_packages() - set(PLATFORM_APPS)
    assert "project" in forbidden and "config" in forbidden  # the scan is not vacuous
    violations = [v for app in PLATFORM_APPS for v in forbidden_imports(BACKEND / app, forbidden)]
    assert not violations, "the platform imports outward:\n  " + "\n  ".join(violations)


def test_every_platform_app_exists():
    missing = [app for app in PLATFORM_APPS if not (BACKEND / app / "apps.py").exists()]
    assert not missing, f"PLATFORM_APPS lists apps that do not exist: {missing}"


def test_the_scanner_catches_a_violation(tmp_path):
    app = tmp_path / "core"
    app.mkdir()
    (app / "__init__.py").write_text("")
    (app / "leak.py").write_text("from project.wiring import register\nimport config.settings\n")
    found = forbidden_imports(app, {"project", "config"})
    assert len(found) == 2 and "project.wiring" in found[0]
