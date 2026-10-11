"""
Boot-time system checks (AUTH_BLUEPRINT § 9.2). They run on every manage.py command, so a
misconfiguration cannot reach a passing check. Settings are read as strings: core imports no app.
"""

from django.conf import settings
from django.core.checks import Error, register
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
