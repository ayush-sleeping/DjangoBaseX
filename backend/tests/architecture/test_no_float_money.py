"""
No float holds money (DOMAIN_PRIMITIVES.md § 1; BUILD_ORDER 6.5).

The bug it prevents: `amount = models.FloatField()` or `serializers.FloatField()` on anything
named like money. A float cannot hold 0.1 exactly, so every total drifts, and a client float
reaches a balance debit unquantised. Money columns are DecimalField(19, 4) pairs from
core.money.money_fields(); request amounts are StrictMoneyField strings.

How (AST, production code): an assignment whose target name matches MONEY_NAME and whose value is
a call to a name ending in FloatField. The universe is every field assignment with a money-like
name, of any type: if that universe is empty the regex has rotted (or no money exists yet), and
the test says so instead of passing silently.

Blind spots: a FloatField built through a factory function; a money column with a name outside
the regex. Do NOT silence this by adding an exception — fix the code.
"""

import ast
import re
from pathlib import Path

import pytest

from tests.architecture._ratchet import assert_ratchet
from tests.architecture.sources import Hit, iter_python_sources, parse, rel

MONEY_NAME = re.compile(
    r"(^|_)(amount|price|cost|balance|rate|total|fee|tax|discount|charge|credit)(s|_|$)"
)
# path::name -> why it is allowed. Do not add an entry without a reason.
ALLOWED: dict[str, str] = {}


def _field_assignments(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(
            node.value, ast.Call
        ):
            continue
        func = node.value.func
        call = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if not call.endswith("Field"):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and MONEY_NAME.search(target.id):
                yield node.lineno, target.id, call


def scan(files) -> tuple[list[Hit], int]:
    """(float offenders, size of the money-named universe)."""
    hits, universe = [], 0
    for path in files:
        for line, name, call in _field_assignments(parse(path)):
            universe += 1
            if call.endswith("FloatField"):
                hits.append(Hit(rel(path), line, name))
    return sorted(hits, key=lambda h: (h.path, h.line)), universe


def test_no_float_money_in_production_code():
    hits, universe = scan(iter_python_sources())
    if universe == 0:
        pytest.skip(
            "no money-named model or serializer field exists yet; the ratchet arms with the first"
        )
    assert_ratchet(hits, ALLOWED, rule="no_float_money")


def test_catches_a_float_money_field(tmp_path: Path):
    code = tmp_path / "models.py"
    code.write_text(
        "from django.db import models\nfrom rest_framework import serializers\n"
        "class Invoice(models.Model):\n"
        "    total_amount = models.FloatField()\n"
        "    unit_price = models.DecimalField(max_digits=19, decimal_places=4)\n"
        "    width = models.FloatField()\n"  # not money
        "class In(serializers.Serializer):\n"
        "    fee = serializers.FloatField()\n"
        "    rate: serializers.Field = serializers.FloatField()\n"
    )
    hits, universe = scan([code])
    assert [str(h) for h in hits] == [
        "models.py:4: total_amount",
        "models.py:8: fee",
        "models.py:9: rate",
    ]
    assert universe == 4
