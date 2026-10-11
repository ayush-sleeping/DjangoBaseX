"""
Reads for authorization — the hottest path in the system (AUTH_BLUEPRINT § 7.4).

Two cache layers: on the user object for the rest of the request, then the shared cache keyed on a
global version. rbac.services bumps the version on ANY grant, role or assignment change, which
invalidates every user at once: a role edit changes many users, and enumerating them is slower and
easy to get wrong. A permission change never needs a deploy or a restart.
"""

from django.core.cache import cache

from .models import Permission, UserRole

VERSION_KEY = "rbac:perms:version"
TTL_SECONDS = 600
_REQUEST_ATTR = "_rbac_permission_codes"


def current_version() -> int:
    version = cache.get(VERSION_KEY)
    if version is None:
        cache.add(VERSION_KEY, 1, timeout=None)
        version = cache.get(VERSION_KEY, 1)
    return version


def bump_version() -> None:
    try:
        cache.incr(VERSION_KEY)
    except ValueError:  # the key was evicted or never set
        cache.set(VERSION_KEY, current_version() + 1, timeout=None)


def permission_codes_for(user) -> frozenset[str]:
    """The union of the user's roles' non-deprecated permission codes. Superuser NOT implied."""
    if user is None or not getattr(user, "is_authenticated", False) or not user.is_active:
        return frozenset()
    cached = getattr(user, _REQUEST_ATTR, None)
    if cached is not None:
        return cached
    key = f"rbac:perms:{user.pk}:{current_version()}"
    codes = cache.get(key)
    if codes is None:
        codes = frozenset(
            Permission.objects.filter(
                role_permissions__role__user_roles__user=user, is_deprecated=False
            )
            .values_list("code", flat=True)
            .distinct()
        )
        cache.set(key, codes, TTL_SECONDS)
    setattr(user, _REQUEST_ATTR, codes)
    return codes


def roles_for(user):
    return UserRole.objects.filter(user=user).select_related("role")
