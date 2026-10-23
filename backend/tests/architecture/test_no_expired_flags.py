"""
A flag past its expiry fails CI (CONFIGURATION.md § 11): flags are temporary, and the expiry is
where a reviewer asks why one still exists. Removing a flag deletes the declaration and the dead
branch in one PR; extending it edits `expires_on` in review.
"""

from datetime import date, timedelta

from core.registry import FlagDef, Registry, registry


def expired(defs, today=None):
    today = today or date.today()
    return [
        f"{d.key} (owner {d.owner}, expired {d.expires_on})" for d in defs if d.expires_on < today
    ]


def test_no_registered_flag_is_past_its_expiry():
    assert expired(registry.flags.defs()) == [], (
        "Expired flags: delete the declaration and the dead branch, or extend expires_on in review."
    )


def test_positive_control_a_stale_flag_is_caught():
    reg = Registry()
    reg.flags.register(
        FlagDef(
            key="users.stale_probe",
            owner="core-team",
            expires_on=date.today() - timedelta(days=1),
            description="Dated yesterday on purpose.",
        )
    )
    assert expired(reg.flags.defs()) != []
