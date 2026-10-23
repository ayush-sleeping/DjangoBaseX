"""
Data-plane self-checks (OBSERVABILITY.md § 7; BUILD_ORDER 6.2): do the rows the product cannot
function without exist and make sense?

Configuration that lives in rows has no schema to fail loudly: an emptied allow-list or a missing
default role breaks nothing visibly and refuses everyone. A check answers ok | warn | fatal with a
detail and a remedy an operator can act on. `fatal` is reserved for "the product is impossible";
a feature deliberately left dormant is a warn, never a fatal.

The evaluator never raises: a check that throws is `warn` with "check crashed: <ExcType>". A broken
checker must never be worse than the gap it watches. Results are cached for DATAPLANE_CACHE_SECONDS
for the non-boot consumers (health components); `manage.py dataplane --fatal-only` evaluates fresh.
"""

import time
from dataclasses import dataclass

from django.conf import settings

from core.registry import DataPlaneCheck, registry

OK, WARN, FATAL = "ok", "warn", "fatal"
DEFAULT_CACHE_SECONDS = 60


@dataclass(frozen=True)
class Result:
    status: str
    detail: str = ""
    remedy: str = ""


def ok(detail: str = "") -> Result:
    return Result(OK, detail)


def warn(detail: str, *, remedy: str) -> Result:
    return Result(WARN, detail, remedy)


def fatal(detail: str, *, remedy: str) -> Result:
    return Result(FATAL, detail, remedy)


@dataclass(frozen=True)
class Evaluated:
    key: str
    description: str
    status: str
    detail: str
    remedy: str
    ms: int

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "description": self.description,
            "status": self.status,
            "detail": self.detail,
            "remedy": self.remedy,
            "ms": self.ms,
        }


def run_check(check: DataPlaneCheck) -> Evaluated:
    """Never raises; never returns a non-ok result without a remedy."""
    started = time.perf_counter()
    try:
        result = check.fn()
        if not isinstance(result, Result) or result.status not in (OK, WARN, FATAL):
            result = warn(
                f"check returned {type(result).__name__}, not a Result",
                remedy=f"Fix the {check.key} check: return ok(), warn(...) or fatal(...).",
            )
        elif result.status != OK and not result.remedy.strip():
            result = Result(
                result.status,
                result.detail,
                f"Fix the {check.key} check: a non-ok result must say what to do.",
            )
    except Exception as exc:  # noqa: BLE001 — § 7: the evaluator never raises
        result = warn(
            f"check crashed: {type(exc).__name__}",
            remedy=f"Fix the {check.key} check; until then this gap is unwatched.",
        )
    ms = round((time.perf_counter() - started) * 1000)
    return Evaluated(check.key, check.description, result.status, result.detail, result.remedy, ms)


_cache: dict[str, tuple[float, list[Evaluated]]] = {}


def evaluate(*, fresh: bool = False) -> list[Evaluated]:
    """Every registered check, in registration order. Cached per process unless `fresh`."""
    ttl = float(getattr(settings, "DATAPLANE_CACHE_SECONDS", DEFAULT_CACHE_SECONDS))
    now = time.monotonic()
    cached = _cache.get("results")
    if not fresh and cached and now - cached[0] < ttl:
        return cached[1]
    results = [run_check(check) for check in registry.dataplane.checks()]
    _cache["results"] = (now, results)
    return results


def clear_cache() -> None:
    _cache.clear()


def worst(results: list[Evaluated]) -> str:
    statuses = {r.status for r in results}
    if FATAL in statuses:
        return FATAL
    return WARN if WARN in statuses else OK


# --- Core's own checks (registered in CoreConfig.ready) ----------------------------------------


def _active_superuser() -> Result:
    from django.contrib.auth import get_user_model

    if get_user_model().objects.filter(is_active=True, is_superuser=True).exists():
        return ok()
    return fatal(
        "No active superuser: nobody can administer the install.",
        remedy="Run manage.py bootstrap_admin, or reactivate an existing superuser.",
    )


def _administrator_role_held() -> Result:
    from rbac.models import Role, UserRole
    from rbac.services import ADMINISTRATOR

    if not Role.objects.filter(slug=ADMINISTRATOR).exists():
        return fatal(
            "The administrator system role is missing.",
            remedy="Run manage.py migrate (rbac seeds it) or manage.py bootstrap_admin.",
        )
    if not UserRole.objects.filter(role__slug=ADMINISTRATOR, user__is_active=True).exists():
        return fatal(
            "No active account holds the administrator role.",
            remedy="Assign the administrator role under Roles, or run manage.py bootstrap_admin.",
        )
    return ok()


CORE_CHECKS = (
    DataPlaneCheck(
        key="core.active_superuser",
        description="At least one active account can administer the install.",
        fn=_active_superuser,
    ),
    DataPlaneCheck(
        key="core.administrator_role",
        description="The administrator system role exists and an active account holds it.",
        fn=_administrator_role_held,
    ),
)


def register_core_checks() -> None:
    for check in CORE_CHECKS:
        registry.dataplane.register(check)
