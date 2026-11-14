"""The alert vocabulary (§ 15). The instant allow-list is CODE: a new kind that may interrupt
someone is a reviewed change with an argument for why. Thresholds are settings (settings.py)."""

from dataclasses import dataclass
from enum import StrEnum


class AlertKind(StrEnum):
    REGRESSION = "regression"  # a resolved error group has recurred
    INFRA_OUTAGE = "infra_outage"  # database, cache or broker unreachable
    MISCONFIGURATION = "misconfiguration"  # a route with no destination, a failing self-test
    DEPLOY_BREAKAGE = "deploy_breakage"  # a post-deploy check still failing after the grace
    FIRST_SIGHTING = "first_sighting"  # an error group seen for the first time
    DEGRADED = "degraded"  # everything else: held for the digest


INSTANT_KINDS = (
    AlertKind.REGRESSION,
    AlertKind.INFRA_OUTAGE,
    AlertKind.MISCONFIGURATION,
    AlertKind.DEPLOY_BREAKAGE,
    AlertKind.FIRST_SIGHTING,
)

# Ledger vocabulary: decisions' reasons (OpsAlert.decision_reason).
HELD_DIGEST, HELD_QUIET, HELD_STORM = "digest", "quiet_hours", "storm_cap"
SKIP_DISABLED, SKIP_NO_DESTINATION = "disabled", "no_destination"
SKIP_COOLDOWN, SKIP_ALREADY_HELD, SKIP_DISPATCH_ERROR = "cooldown", "already_held", "dispatch_error"

NOTICE_STORM, NOTICE_QUIET = "storm_notice", "quiet_summary"

PURPOSE_ALERT, PURPOSE_DIGEST = "core.ops_alert", "core.ops_digest"


@dataclass(frozen=True)
class Problem:
    """One current problem a monitor reports to incidents.sync()."""

    label: str
    kind: str = AlertKind.DEGRADED
    body: str = ""
