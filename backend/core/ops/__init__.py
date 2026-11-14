"""
Ops alerting (BUILD_ORDER 7.8; NOTIFICATIONS_AND_ALERTING.md Part B, §§ 14-21).

One dispatcher with a database ledger (`alert`), a pure policy over that ledger (`policy.decide`),
incidents announced once and recovered once (`incidents.sync`), quiet hours with one release
summary, a twice-daily digest, and a scheduled monitor that exits 0. Monitors and jobs talk to
operators only through `alert` / `incidents.sync`; only `dispatcher` imports `notify()`.
"""

from .dispatcher import alert
from .kinds import AlertKind, Problem

__all__ = ["AlertKind", "Problem", "alert"]
