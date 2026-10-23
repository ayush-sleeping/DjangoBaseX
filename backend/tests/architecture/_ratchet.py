"""
The two-way ratchet (ENGINEERING_PRACTICES.md § 2).

(a) nothing outside the allow-list offends; (b) every allow-list entry still offends. Fixing an
offender without deleting its entry fails, so an allow-list can only shrink. Entries are keyed by
path plus the offending value (sources.Hit.key), and each carries a reason in the test that owns it.
"""

from collections.abc import Iterable, Mapping

from tests.architecture.sources import Hit


def assert_ratchet(hits: Iterable[Hit], allowed: Mapping[str, str], *, rule: str) -> None:
    hits = list(hits)
    blank = sorted(key for key, reason in allowed.items() if len(reason.strip()) < 15)
    assert not blank, f"[{rule}] allow-list entries without a real reason: {blank}"
    new = sorted(str(h) for h in hits if h.key not in allowed)
    fixed = sorted(set(allowed) - {h.key for h in hits})
    assert not new, (
        f"[{rule}] new offenders — fix the code; do NOT silence this by adding an exception:\n  "
        + "\n  ".join(new)
    )
    assert not fixed, f"[{rule}] no longer offend — delete them from the allow-list: {fixed}"
