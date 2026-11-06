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
        ("audit_actions", registry.audit_actions.actions),
        ("guards", registry.guards.defs),
        ("jobs", registry.jobs.specs),
        ("doctors", registry.doctors.doctors),
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


# --- Background jobs (JOBS_AND_INTEGRATIONS.md § 1, § 3). E001–E003 are refused at register(). ---

IN_PROCESS_RESULT_BACKENDS = ("cache+memory://", "memory://", "rpc://")


@register()
def check_job_callables(app_configs, **kwargs):
    """dbx.jobs.E004: every spec's func imports and is `def run(ctx) -> int`. dbx.jobs.E003 for a
    cron spec whose expires is not below its period (an Interval's is refused at register())."""
    from .jobs.runner import resolve, signature_problem
    from .jobs.schedules import period_seconds
    from .registry import Cron, registry

    errors = []
    for spec in registry.jobs.specs():
        try:
            func = resolve(spec)
        except (ImportError, AttributeError) as exc:
            errors.append(
                Error(
                    f"job {spec.name}: func {spec.func} does not import: {exc}", id="dbx.jobs.E004"
                )
            )
            continue
        problem = signature_problem(func)
        if problem:
            errors.append(Error(f"job {spec.name}: {spec.func} {problem}", id="dbx.jobs.E004"))
        if isinstance(spec.schedule, Cron):
            try:
                period = period_seconds(spec.schedule)
            except ValueError as exc:
                errors.append(Error(f"job {spec.name}: {exc}", id="dbx.jobs.E003"))
                continue
            if spec.expires is not None and spec.expires >= period:
                errors.append(
                    Error(
                        f"job {spec.name}: expires {spec.expires} is not below the period "
                        f"({period}s)",
                        id="dbx.jobs.E003",
                    )
                )
    return errors


@register()
def check_celery_config(app_configs, **kwargs):
    """dbx.jobs.E010–E015: the § 3 settings that fail silently when wrong."""
    from .env import is_production_like, normalise
    from .registry import registry

    errors = []
    specs = {spec.name: spec for spec in registry.jobs.specs()}
    tasks = _celery_tasks()
    backend = (getattr(settings, "CELERY_RESULT_BACKEND", None) or "").lower()
    for name, task in tasks.items():
        if not task.ignore_result and (
            not backend or backend.startswith(IN_PROCESS_RESULT_BACKENDS)
        ):
            errors.append(
                Error(
                    f"task {name} keeps its result (ignore_result=False) but CELERY_RESULT_BACKEND "
                    f"is {backend or 'unset'}: nobody can read it back.",
                    hint="Configure a shared result backend, or ignore the result (§ 3).",
                    id="dbx.jobs.E010",
                )
            )
        if task.acks_late and not (name in specs and specs[name].idempotent):
            errors.append(
                Error(
                    f"task {name} acks late but is not a JobSpec declared idempotent=True.",
                    hint="A crash re-delivers a late-acked task: only idempotent work may (§ 3).",
                    id="dbx.jobs.E014",
                )
            )
    if getattr(settings, "CELERY_TASK_ACKS_LATE", False):
        errors.append(
            Error(
                "CELERY_TASK_ACKS_LATE is True globally; set it per idempotent task (§ 3).",
                id="dbx.jobs.E014",
            )
        )

    longest = max(
        [getattr(settings, "CELERY_TASK_TIME_LIMIT", 0) or 0]
        + [spec.time_limit for spec in specs.values()]
    )
    visibility = (getattr(settings, "CELERY_BROKER_TRANSPORT_OPTIONS", {}) or {}).get(
        "visibility_timeout",
        3600,  # kombu's Redis default
    )
    if visibility <= longest:
        errors.append(
            Error(
                f"the broker visibility_timeout ({visibility}s) is not above the longest "
                f"time_limit ({longest}s): Redis would redeliver a running task to another worker.",
                hint="Raise CELERY_VISIBILITY_TIMEOUT (§ 3).",
                id="dbx.jobs.E011",
            )
        )

    serializers = {
        getattr(settings, "CELERY_TASK_SERIALIZER", "json"),
        getattr(settings, "CELERY_RESULT_SERIALIZER", "json"),
        *getattr(settings, "CELERY_ACCEPT_CONTENT", ["json"]),
    }
    if serializers - {"json", "application/json"}:
        errors.append(
            Error(
                f"Celery serializers include {sorted(serializers - {'json', 'application/json'})}: "
                "only JSON is accepted (pickle is code execution for anyone who can write to the "
                "broker).",
                id="dbx.jobs.E012",
            )
        )
    if (
        getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)
        and normalise(settings.APP_ENV) != "test"
    ):
        errors.append(
            Error(
                "CELERY_TASK_ALWAYS_EAGER is True outside tests: it hides routing, "
                "serialisation and transaction bugs (§ 3).",
                id="dbx.jobs.E013",
            )
        )
    broker = (getattr(settings, "CELERY_BROKER_URL", "") or "").lower()
    if is_production_like(settings.APP_ENV) and (not broker or broker.startswith("memory://")):
        errors.append(
            Error(
                f"CELERY_BROKER_URL is {broker or 'unset'} in a production-like environment: "
                "tasks would be queued in a process no worker can reach.",
                hint="Set CELERY_BROKER_URL to the shared broker (redis://...).",
                id="dbx.jobs.E015",
            )
        )
    return errors


def _celery_tasks() -> dict:
    """Every task the app knows, Celery's own (celery.*) excluded."""
    from celery import current_app as app  # config/celery.py's app; core never imports config

    return {name: task for name, task in app.tasks.items() if not name.startswith("celery.")}
