"""
No model decrypts on attribute access (JOBS § 25): a property or __getattr__ that calls decrypt()
makes every repr(), log line and debugger session a disclosure, and "who read this secret?"
unanswerable. Reading a secret is an explicit service call, always.
"""

import ast

from tests.architecture.sources import iter_python_sources, rel


def decrypting_accessors(tree: ast.AST) -> list[str]:
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_property = any(
            (isinstance(d, ast.Name) and d.id in {"property", "cached_property"})
            or (isinstance(d, ast.Attribute) and d.attr == "cached_property")
            for d in node.decorator_list
        )
        if not (
            is_property or node.name in {"__getattr__", "__getattribute__", "__repr__", "__str__"}
        ):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call):
                name = getattr(call.func, "id", getattr(call.func, "attr", ""))
                if name in {"decrypt", "decrypt_secret"}:
                    offenders.append(node.name)
    return offenders


def test_no_model_decrypts_on_attribute_access():
    offenders = []
    for path in iter_python_sources():
        if "models" not in path.parts and path.name != "models.py":
            continue
        for name in decrypting_accessors(ast.parse(path.read_text(), filename=str(path))):
            offenders.append(f"{rel(path)}::{name}")
    assert offenders == [], f"decrypt on attribute access: {offenders}"


def test_positive_control_a_decrypting_property_is_caught():
    source = """
class Credential:
    @property
    def secret(self):
        return decrypt(self.secret_ciphertext, purpose="x")

    def __repr__(self):
        return decrypt_secret(self.token)
"""
    assert decrypting_accessors(ast.parse(source)) == ["secret", "__repr__"]
