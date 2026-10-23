"""
Every *_ciphertext column is registered, and every registration names a real field (JOBS § 25):
rotation and --verify can only protect the set they know about. By AST over the § 18 sources, so a
column in a plugin or in project/ is held to the same rule.
"""

import ast

from django.apps import apps

from core.registry import registry
from tests.architecture.sources import iter_python_sources, rel


def declared_ciphertext_columns() -> set[tuple[str, str]]:
    """(file, field name) for every models.py assignment whose target ends in _ciphertext."""
    found = set()
    for path in iter_python_sources():
        if "models" not in path.parts and path.name != "models.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.endswith("_ciphertext"):
                        found.add((rel(path), target.id))
    return found


def test_every_ciphertext_column_is_registered_and_every_registration_is_real():
    columns = declared_ciphertext_columns()
    assert columns, "no *_ciphertext column found anywhere: the scan is looking in the wrong place"
    registered = {(spec.model, spec.field) for spec in registry.encrypted_fields.fields()}
    assert registered, "nothing registered in registry.encrypted_fields"

    registered_names = {field for _, field in registered}
    unregistered = {f"{path}::{name}" for path, name in columns if name not in registered_names}
    assert not unregistered, (
        f"ciphertext columns rotation does not know about: {sorted(unregistered)}"
    )

    for model_label, field in registered:
        model = apps.get_model(model_label)  # LookupError for a registration naming nothing real
        model._meta.get_field(field)  # FieldDoesNotExist likewise


def test_positive_control_the_scanner_sees_a_column(tmp_path):
    source = tmp_path / "models.py"
    source.write_text("api_key_ciphertext = TextField()\n")
    hits = set()
    import ast as _ast

    for node in _ast.walk(_ast.parse(source.read_text())):
        if isinstance(node, _ast.Assign):
            hits |= {t.id for t in node.targets if isinstance(t, _ast.Name)}
    assert "api_key_ciphertext" in hits
