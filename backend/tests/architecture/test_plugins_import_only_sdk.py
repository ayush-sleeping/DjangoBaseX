"""
A plugin reaches the platform only through `core.sdk` (EXTENSIBILITY § 16, BUILD_ORDER 9.1).

`from core.navigation import ...` from a plugin works today and breaks silently the day core
refactors it. The rule is checked on every installed plugin, on the scaffold `scripts/plugins.py
new` generates, and against broken fixtures so the rule is proven able to fail. The one sanctioned
cross-plugin import, `djx_<other>.contracts` under TYPE_CHECKING, is proven allowed (§ 18).
"""

import pytest

from tests.architecture import plugin_rules as rules
from tests.architecture.test_plugin_conventions import (  # noqa: F401
    installed_plugins,
    scaffold,
    write,
)


@pytest.mark.parametrize("plugin", installed_plugins(), ids=lambda p: p.name)
def test_installed_plugin_imports_core_only_through_the_sdk(plugin):
    problems = rules.sdk_problems(plugin)
    assert not problems, "\n".join(problems)


def test_the_scaffold_imports_core_only_through_the_sdk(scaffold):  # noqa: F811
    assert rules.sdk_problems(scaffold) == []


@pytest.mark.parametrize(
    "source",
    [
        "import core.navigation\n",
        "from core.registry import registry\n",
        "from core import registry\n",
        "from users.models import User\n",
        "from rbac import services\n",
        "import importlib\nimportlib.import_module('core.audit')\n",
    ],
)
def test_the_sdk_rule_flags_every_way_around_the_facade(scaffold, source):  # noqa: F811
    path = write(scaffold, "leak.py", source)
    try:
        problems = rules.sdk_problems(scaffold)
    finally:
        path.unlink()
    assert len(problems) == 1 and "leak.py" in problems[0], problems


def test_the_sdk_and_relative_imports_are_allowed(scaffold):  # noqa: F811
    path = write(scaffold, "fine.py", "from core.sdk import registry\nfrom . import wiring\n")
    try:
        assert rules.sdk_problems(scaffold) == []
    finally:
        path.unlink()


def test_another_plugins_contracts_are_allowed_under_type_checking_only(scaffold):  # noqa: F811
    guarded = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    from djx_other.contracts import Totals\n"
    )
    path = write(scaffold, "typed.py", guarded)
    try:
        assert rules.boundary_problems(scaffold, {"djx_other"}) == []
    finally:
        path.unlink()
    for source in (
        "from djx_other.contracts import Totals\n",  # at run time: a real dependency
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from djx_other.models import X\n",
    ):
        path = write(scaffold, "typed.py", source)
        try:
            assert len(rules.boundary_problems(scaffold, {"djx_other"})) == 1, source
        finally:
            path.unlink()
