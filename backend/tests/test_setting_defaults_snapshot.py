"""
Code defaults are resolved live (owner decision on CONFIGURATION.md pending #2), so changing one
changes behaviour for every installation that never overrode it. This snapshot makes that a
reviewed diff with an UPGRADING.md note, never a silent side effect of a refactor (§ 9.2).
"""

import json
from pathlib import Path

from core.registry import registry

SNAPSHOT = Path(__file__).with_name("setting_defaults.json")


def test_the_code_defaults_match_the_committed_snapshot():
    live = {d.key: d.to_json(d.default) for d in registry.settings.defs()}
    assert live, "no settings are declared: the snapshot is testing nothing"
    committed = json.loads(SNAPSHOT.read_text())
    assert live == committed, (
        "A code default changed (or a setting appeared/retired). If intended: update "
        "tests/setting_defaults.json in the same change and add an UPGRADING.md note."
    )
