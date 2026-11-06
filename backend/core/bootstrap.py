"""
GET /api/me/bootstrap/ — the shell's one round trip after sign-in (FRONTEND_PLATFORM.md § 7,
BUILD_ORDER 8.2).

The response is assembled from contributors, each owning one top-level key and declared essential
or not:

- an ESSENTIAL contributor that raises fails the whole response (a 500): the frontend's permission
  provider then fails closed, never open on a half-built answer;
- any other contributor that raises is left out and its key listed in `degraded`: a broken badge or
  flag lookup must never break sign-in.

core holds the engine and core's own contributors. The identity sections (`user`, `session`) belong
to the users app, which composes them with CORE_CONTRIBUTORS (users never the other way round).
The contributor list is a plain tuple for now; it moves into core.registry with the full registry
catalogue (BUILD_ORDER 9.1), keeping this shape.

`permissions` is the EFFECTIVE set, computed by effective_permissions(): the one function both this
endpoint and /api/auth/me/ use, so the UI and the API never compute it two ways.
"""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from .contracts import PluginScope, status_table
from .flags import flags_for
from .navigation import navigation_for
from .observability.health import read_release
from .registry import registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Contributor:
    key: str  # the top-level key it fills; unique across the response
    build: Callable[[Any], Any]  # request -> JSON-serialisable value
    essential: bool = False


def effective_permissions(user) -> list[str]:
    """Every code `user.has_perm()` would grant, sorted. A superuser holds the whole catalogue: the
    superuser bypass is folded in here, so the frontend never special-cases it (§ 9)."""
    if not user.is_active:
        return []
    if user.is_superuser:
        return sorted(registry.permissions.codes())
    return sorted(user.get_all_permissions())


CORE_CONTRIBUTORS: tuple[Contributor, ...] = (
    Contributor("permissions", lambda request: effective_permissions(request.user), essential=True),
    Contributor("server_time", lambda request: timezone.now().isoformat(), essential=True),
    Contributor("nav", lambda request: navigation_for(request.user)),
    Contributor("flags", lambda request: flags_for(request.user)),
    Contributor("build", lambda request: read_release()),
    # Every status's tone and label, linked plugins' included: the frontend's generated table holds
    # core's only, so a plugin's chips take their tone from here (FRONTEND_PLATFORM § 13).
    Contributor("statuses", lambda request: status_table(PluginScope.none())),
)


def assemble(request, contributors: Iterable[Contributor]) -> dict:
    """The bootstrap body. An essential contributor's exception propagates (→ 500)."""
    body: dict[str, Any] = {}
    degraded: list[str] = []
    for contributor in contributors:
        if contributor.key in body or contributor.key == "degraded":
            raise ValueError(f"bootstrap key {contributor.key!r} is contributed twice")
        if contributor.essential:
            body[contributor.key] = contributor.build(request)
            continue
        try:
            body[contributor.key] = contributor.build(request)
        except Exception:  # noqa: BLE001 — a decorative section must never fail sign-in
            logger.exception("bootstrap contributor %r failed", contributor.key)
            degraded.append(contributor.key)
    body["degraded"] = degraded
    return body
