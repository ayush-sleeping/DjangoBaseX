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
def check_registry_seals(app_configs, **kwargs):
    """
    dbx.E009: every catalog seals cleanly at boot. Navigation refuses to seal while an item names an
    undeclared permission, and nothing else reads it before the first request, so without this a
    typo'd nav permission passed every check and then answered 500 on every menu call.
    """
    from .registry import RegistryError, registry

    errors = []
    for name, read in (
        ("permissions", registry.permissions.groups),
        ("navigation", registry.navigation.sections),
        ("health", registry.health.checks),
        ("dataplane", registry.dataplane.checks),
        ("encrypted_fields", registry.encrypted_fields.fields),
        ("api_routes", registry.api_routes.routes),
        ("public_routes", registry.public_routes.routes),
        ("settings", registry.settings.defs),
        ("flags", registry.flags.defs),
        ("lookups", registry.lookups.defs),
        ("guards", registry.guards.defs),
    ):
        try:
            read()
        except RegistryError as exc:
            errors.append(Error(f"registry.{name}: {exc}", id="dbx.E009"))
    return errors


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
        elif isinstance(entry, URLPattern) and (prefix + part).startswith(
            f"{settings.API_PREFIX}/"
        ):
            name = entry.name and (f"{namespace}:{entry.name}" if namespace else entry.name)
            cls = getattr(entry.callback, "cls", None) or getattr(
                entry.callback, "view_class", None
            )
            yield name, cls, prefix + part


@register()
def check_routes_are_gated(app_configs, **kwargs):
    """
    dbx.E001: every /api/ route is a BaseAPIView/BaseViewSet that declares its permissions or is
    public. dbx.E007: `public = True` and registry.public_routes agree, both directions, and
    every ledger entry resolves and carries a reason.
    """
    from .api.views import BaseAPIView
    from .api.viewsets import BaseViewSet
    from .routes import public_routes

    ledger = public_routes()  # the union every app registered (DB-22)

    errors, seen = [], set()
    for name, cls, path in _api_views():
        seen.add(name)
        if name in ledger and not (cls and issubclass(cls, (BaseAPIView, BaseViewSet))):
            continue  # third-party public views (the OpenAPI schema and docs), ledger-listed
        if not (cls and issubclass(cls, (BaseAPIView, BaseViewSet))):
            errors.append(
                Error(
                    f"/{path} ({name}) does not inherit BaseAPIView or BaseViewSet.", id="dbx.E001"
                )
            )
            continue
        if cls.public and name not in ledger:
            errors.append(
                Error(
                    f"/{path} ({name}) is public but not in registry.public_routes.", id="dbx.E007"
                )
            )
        if not cls.public and name in ledger:
            errors.append(
                Error(
                    f"registry.public_routes lists {name}, whose view is not public.", id="dbx.E007"
                )
            )
        if not cls.public and cls.required_permissions is None:
            errors.append(
                Error(
                    f"/{path} ({name}) declares neither required_permissions nor public.",
                    hint="It denies everyone. Declare its codes, [] for any signed-in user, or "
                    "make it public with a registry.public_routes entry. AUTH_BLUEPRINT § 9.1.",
                    id="dbx.E001",
                )
            )
    for name, reason in ledger.items():
        if name not in seen:
            errors.append(
                Error(f"registry.public_routes lists {name}, which is not a route.", id="dbx.E007")
            )
        if len(reason.strip()) < 20:
            errors.append(
                Error(f"registry.public_routes[{name!r}] has no real reason.", id="dbx.E007")
            )
    return errors


@register()
def check_encryption_keys(app_configs, **kwargs):
    """dbx.crypto.E001/E002 (JOBS_AND_INTEGRATIONS.md § 25): the keyring is usable, separate from
    the signing keys, and a probe round-trips per purpose. cfg.E013/W008 are the boot-refusal
    twins; this is the `manage.py check` face of the same rules."""
    from cryptography.fernet import Fernet

    from . import crypto
    from .env import is_production_like
    from .registry import registry

    def registry_encrypted_fields():
        return registry.encrypted_fields.fields()

    errors = []
    keys = [k.strip() for k in getattr(settings, "FIELD_ENCRYPTION_KEYS", []) if k.strip()]
    if not keys:
        if is_production_like(settings.APP_ENV):
            errors.append(
                Error(
                    "FIELD_ENCRYPTION_KEYS is empty outside development.",
                    hint="Generate a key: manage.py generate_secret --kind fernet. § 25.",
                    id="dbx.crypto.E001",
                )
            )
        return errors
    for position, key in enumerate(keys):
        try:
            Fernet(key)
        except Exception:  # noqa: BLE001
            errors.append(
                Error(
                    f"FIELD_ENCRYPTION_KEYS[{position}] is not a valid Fernet key.",
                    hint="manage.py generate_secret --kind fernet. The value is never shown.",
                    id="dbx.crypto.E001",
                )
            )
    for other in ("SECRET_KEY", "JWT_SIGNING_KEY"):
        if getattr(settings, other, "") in keys:
            errors.append(
                Error(
                    f"FIELD_ENCRYPTION_KEYS contains {other}.",
                    hint="Rotating one must not brick the other; use a separate key. § 25.",
                    id="dbx.crypto.E001",
                )
            )
    for spec in registry_encrypted_fields():
        if spec.purpose not in crypto.PURPOSES:
            errors.append(
                Error(
                    f"{spec.model}.{spec.field} registers purpose {spec.purpose!r}, which is not "
                    "in core.crypto.PURPOSES.",
                    hint="Purposes are registered constants; add it there (a reviewed change).",
                    id="dbx.crypto.E003",
                )
            )
    if not errors:
        try:
            crypto.self_test()
        except Exception as exc:  # noqa: BLE001 — the probe's failure is the finding
            errors.append(Error(f"The encryption self-test failed: {exc}", id="dbx.crypto.E002"))
    return errors
