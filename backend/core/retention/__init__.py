"""The retention engine (BUILD_ORDER 7.5; DATA_LIFECYCLE.md § 6): declare a RetentionPolicy and
register it with register(), which also declares its window as a runtime setting."""

from core.registry import Registry, RetentionPolicy
from core.settings_registry import Bool, Int, SettingDef

__all__ = ["RetentionPolicy", "register"]


def register(registry: Registry, policy: RetentionPolicy) -> None:
    """Register `policy` and its settings: `retention.<key>.days` (nullable: empty keeps forever;
    floor = min_age_days) and, for an opt-in policy, `retention.<key>.enabled` (default off)."""
    common = {
        "module": "retention",
        "group": "Data retention",
        "used_by": (f"Retention: {policy.key}",),
    }
    definitions = [
        SettingDef(
            key=policy.days_setting,
            type=Int(min=policy.min_age_days),
            default=policy.max_age_days,
            nullable=True,  # None = keep forever: the policy is skipped
            label=f"Days to keep {policy.key}",
            description=(
                f"{policy.description} Older rows are deleted. Empty keeps them forever; nothing "
                f"under {policy.min_age_days} days is accepted."
            ),
            changed_by_event="An agreed retention policy, or a storage budget",
            **common,
        )
    ]
    if policy.requires_opt_in:
        definitions.append(
            SettingDef(
                key=policy.enabled_setting,
                type=Bool(),
                default=False,  # evidence is never pruned by default
                label=f"Let the scheduled run prune {policy.key}",
                description=(
                    "Off: the daily job never touches it (only an explicit --include-opt-in run "
                    "does). On: rows past the window above are deleted every day."
                ),
                changed_by_event="An agreed audit-trail retention policy",
                **common,
            )
        )
    registry.retention.register(policy, definitions)
