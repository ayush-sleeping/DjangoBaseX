"""
Guard modes: off · log_only · enforce (CONFIGURATION.md § 13; BUILD 5.4).

A guard is a refusal added to a system that already has traffic. Its shipped default reproduces
today's behaviour, so installing it changes no response; tightening to enforce is a later, audited
admin action on the `<key>.mode` setting — with log_only in between, which evaluates fully, records
what it would have blocked, and lets the request through.

    register_guard(GuardDef(
        key="rbac.grant_beyond_actor", default_mode="log_only",
        description="Refuse granting a role a permission the acting user does not hold.",
        error_code="authz.grant_beyond_actor",
    ))  # from AppConfig.ready(); also declares the rbac.grant_beyond_actor.mode Choice setting

    check_guard("rbac.grant_beyond_actor", violated=actor_lacks_code, actor=..., code=...)

The day-one guards (default-deny, the elevated-role guard, the last-superuser guard) are NOT guards
in this sense: they enforce from the first commit, because there is no prior behaviour to preserve.
"""

import logging

from rest_framework import status
from rest_framework.exceptions import APIException

from core.audit import log_activity
from core.registry import GUARD_MODES, GuardDef, registry
from core.settings_registry import Choice, SettingDef
from core.settings_service import get_setting

__all__ = ["GuardDef", "GuardRefused", "check_guard", "guard_mode", "register_guard"]

logger = logging.getLogger("core.guards")


class GuardRefused(APIException):
    """An enforce-mode refusal, with the guard's stable error code."""

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "guard_refused"

    def __init__(self, guard: GuardDef):
        self.guard = guard
        super().__init__(
            detail={"error": {"code": guard.error_code, "message": guard.description}},
            code=guard.error_code,
        )


def register_guard(guard: GuardDef) -> None:
    """
    Declare the guard AND its `<key>.mode` setting in one call, so a guard cannot exist without a
    switch and a label (§ 13). Call from AppConfig.ready().
    """
    registry.guards.register(guard)
    registry.settings.register(
        SettingDef(
            key=f"{guard.key}.mode",
            type=Choice(choices=GUARD_MODES),
            default=guard.default_mode,
            label=f"Guard mode: {guard.description}",
            description=(
                "off evaluates nothing; log_only records what would be blocked and lets it "
                "through; enforce refuses with a stable error code. The shipped default is "
                "today's behaviour — tighten on evidence."
            ),
            group="Guards",
            module=guard.key.split(".", 1)[0],
            changed_by_event="Evidence from log_only (would-block counts), or an incident",
            used_by=(guard.description,),
        )
    )


def guard_mode(key: str) -> str:
    """The guard's current mode. Unreadable resolves to the DECLARED default, never to enforce-by-
    accident or off-by-accident (§ 13): get_setting already degrades to the code default, and the
    code default is the declaration's."""
    guard = registry.guards.get(key)  # KeyError for an undeclared guard: a typo, not a mode
    try:
        mode = get_setting(f"{key}.mode")
    except Exception:  # noqa: BLE001 — a broken settings path must not decide a guard's direction
        logger.warning("core.guard.fallback", extra={"guard_key": key, "reason": "settings"})
        return guard.default_mode
    return mode if mode in GUARD_MODES else guard.default_mode


def check_guard(key: str, violated: bool, **context) -> None:
    """
    The one call a guarded code path makes. Not violated: nothing happens. Violated: off records
    nothing; log_only writes guard.would_block and passes; enforce writes guard.blocked and raises
    the guard's catalogued error.
    """
    if not violated:
        return
    guard = registry.guards.get(key)
    mode = guard_mode(key)
    if mode == "off":
        return
    verb = "guard.blocked" if mode == "enforce" else "guard.would_block"
    try:  # recording degrades, it never decides the request's fate
        log_activity(verb, context.pop("actor", None), guard=key, mode=mode, **context)
    except Exception:  # noqa: BLE001
        logger.warning("core.guard.not_recorded", extra={"guard_key": key})
    if mode == "enforce":
        raise GuardRefused(guard)
