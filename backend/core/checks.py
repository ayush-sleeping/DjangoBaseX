"""
Boot-time system checks (AUTH_BLUEPRINT § 9.2). They run on every manage.py command, so a
misconfiguration cannot reach a passing check. Settings are read as strings: core imports no app.
"""

from django.conf import settings
from django.core.checks import Error, register
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils.module_loading import import_string

RBAC_BACKEND = "rbac.backends.RBACBackend"
LOCAL_CACHES = (
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.dummy.DummyCache",
)


@register()
def check_shared_cache(app_configs, **kwargs):
    """dbx.E005: throttles, lockout and session liveness are per worker on a per-process cache."""
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if not settings.DEBUG and backend in LOCAL_CACHES:
        return [
            Error(
                f"CACHES['default'] is {backend.rsplit('.', 1)[-1]} with DEBUG=False.",
                hint="Set CACHE_URL to a shared cache (redis://...). AUTH_BLUEPRINT § 17.4.",
                id="dbx.E005",
            )
        ]
    return []


@register()
def check_single_grant_path(app_configs, **kwargs):
    """dbx.E006: only RBACBackend answers has_perm; every other backend declares it grants none."""
    errors = []
    for path in settings.AUTHENTICATION_BACKENDS:
        if path == RBAC_BACKEND:
            continue
        if getattr(import_string(path), "contributes_permissions", True):
            errors.append(
                Error(
                    f"Authentication backend {path} may grant permissions beside RBAC.",
                    hint="Subclass it with contributes_permissions = False and empty permission "
                    "methods (users.backends.CredentialsOnlyBackend). AUTH_BLUEPRINT § 7.4a.",
                    id="dbx.E006",
                )
            )
    if RBAC_BACKEND not in settings.AUTHENTICATION_BACKENDS:
        errors.append(Error(f"{RBAC_BACKEND} is not in AUTHENTICATION_BACKENDS.", id="dbx.E006"))
    return errors


DEFAULT_DENY = "core.permissions.DefaultDeny"


@register()
def check_default_deny(app_configs, **kwargs):
    """dbx.E004: DRF's default is DefaultDeny, so a view that skips the bases is closed."""
    defaults = settings.REST_FRAMEWORK.get("DEFAULT_PERMISSION_CLASSES", [])
    if list(defaults) != [DEFAULT_DENY]:
        return [
            Error(
                f"REST_FRAMEWORK DEFAULT_PERMISSION_CLASSES is {list(defaults)!r}.",
                hint=f"Set it to [{DEFAULT_DENY!r}]. AUTH_BLUEPRINT § 9.1.",
                id="dbx.E004",
            )
        ]
    return []


def _api_views(patterns=None, prefix="", namespace=None):
    """(url name, view class or None, path) for every route under /api/."""
    if patterns is None:
        patterns = get_resolver().url_patterns
    for entry in patterns:
        part = str(entry.pattern)
        if isinstance(entry, URLResolver):
            ns = namespace
            if entry.namespace:
                ns = f"{namespace}:{entry.namespace}" if namespace else entry.namespace
            yield from _api_views(entry.url_patterns, prefix + part, ns)
        elif isinstance(entry, URLPattern) and (prefix + part).startswith("api/"):
            name = entry.name and (f"{namespace}:{entry.name}" if namespace else entry.name)
            cls = getattr(entry.callback, "cls", None) or getattr(
                entry.callback, "view_class", None
            )
            yield name, cls, prefix + part


@register()
def check_routes_are_gated(app_configs, **kwargs):
    """
    dbx.E001: every /api/ route is a BaseAPIView/BaseViewSet that declares its permissions or is
    public. dbx.E007: `public = True` and core.routes.PUBLIC_ROUTES agree, both directions, and
    every ledger entry resolves and carries a reason.
    """
    from .api.views import BaseAPIView
    from .api.viewsets import BaseViewSet
    from .routes import PUBLIC_ROUTES

    errors, seen = [], set()
    for name, cls, path in _api_views():
        seen.add(name)
        if name in PUBLIC_ROUTES and not (cls and issubclass(cls, (BaseAPIView, BaseViewSet))):
            continue  # third-party public views (the OpenAPI schema and docs), ledger-listed
        if not (cls and issubclass(cls, (BaseAPIView, BaseViewSet))):
            errors.append(
                Error(
                    f"/{path} ({name}) does not inherit BaseAPIView or BaseViewSet.", id="dbx.E001"
                )
            )
            continue
        if cls.public and name not in PUBLIC_ROUTES:
            errors.append(
                Error(f"/{path} ({name}) is public but not in PUBLIC_ROUTES.", id="dbx.E007")
            )
        if not cls.public and name in PUBLIC_ROUTES:
            errors.append(
                Error(f"PUBLIC_ROUTES lists {name}, whose view is not public.", id="dbx.E007")
            )
        if not cls.public and cls.required_permissions is None:
            errors.append(
                Error(
                    f"/{path} ({name}) declares neither required_permissions nor public.",
                    hint="It denies everyone. Declare its codes, [] for any signed-in user, or "
                    "make it public with a PUBLIC_ROUTES entry. AUTH_BLUEPRINT § 9.1.",
                    id="dbx.E001",
                )
            )
    for name, reason in PUBLIC_ROUTES.items():
        if name not in seen:
            errors.append(
                Error(f"PUBLIC_ROUTES lists {name}, which is not a route.", id="dbx.E007")
            )
        if len(reason.strip()) < 20:
            errors.append(Error(f"PUBLIC_ROUTES[{name!r}] has no real reason.", id="dbx.E007"))
    return errors
