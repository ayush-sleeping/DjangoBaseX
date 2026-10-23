"""
The seam every app contributes through (AUTH_BLUEPRINT § 2, § 7.1, § 7.2, and § 2 of
CORE_ARCHITECTURE_PLAN).

Standard library only: nothing from core, rbac or any app. An app declares its permissions, its
navigation, its health checks and its API routes by importing this module, never rbac or core, so
no module depends on another's models just to plug in (A6, A7).

Boot-time and one-way. Apps register() from AppConfig.ready(); the first read of a catalog seals
it, and every later register() raises. Nothing has to know when boot finished: dbx.E009 reads every
catalog after django.setup() (and config/urls.py reads api_routes), which seals them all on every
manage.py invocation, so a catalog that cannot seal fails the check rather than a request (§ 7.2).
There is no unregister: a catalog that changes under a running app answers differently depending on
when you ask.

A registry holds a key, a label and at most a callable, never an app's model or schema.
"""

import re
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import MISSING, dataclass, fields, replace
from datetime import date
from types import MappingProxyType

# "<module>.<feature>.<action>". The action is deliberately not checked against a fixed list:
# the vocabulary in § 7.1 is guidance, and real codes need verbs like "send" and "revoke".
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_MODULE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
# Navigation and health keys: they appear in API payloads and frontend code, so keep them plain.
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
# URL segment under /api/. Hyphens, not underscores: it is a URL.
PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
_DOTTED_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

# /api/<prefix>/ values a plugin cannot take, because core already serves them or will: auth and
# users (users.urls, mounted at /api/), rbac, schema and docs (config/urls.py), health (core.urls),
# and admin, core and api, which would read as something they are not.
RESERVED_PREFIXES = frozenset(
    {
        "admin",
        "api",
        "auth",
        "core",
        "docs",
        "extensions",  # EXTENSIBILITY § 9: the Extensions page's API
        "health",
        "me",
        "meta",
        "rbac",
        "schema",
        "users",
    }
)
# Where a policy dataclass field carries its declaration: core.settings_registry.meta() writes it.
SETTING_METADATA_KEY = "core.setting"
# A Django URL name, optionally namespaced (nested namespaces allowed): "schema", "users:login",
# "billing:payments:callback". Hyphens and underscores, as Django's own names use both.
URL_NAME_PATTERN = re.compile(r"^(?:[a-z][a-z0-9_-]*:)*[a-z][a-z0-9_-]*$")
# The ledger's rule (AUTH_BLUEPRINT § 9.2): a reason is a sentence a reviewer can disagree with.
MIN_REASON_LENGTH = 20


# --- Specs: what an app hands in ------------------------------------------------------------------


@dataclass(frozen=True)
class PermissionSpec:
    code: str  # "<module>.<feature>.<action>"
    label: str


@dataclass(frozen=True)
class PermissionGroupSpec:
    code: str
    label: str
    module: str
    order: int = 100
    permissions: tuple[PermissionSpec, ...] = ()


@dataclass(frozen=True)
class NavItem:
    key: str  # unique within its section
    label: str
    path: str  # frontend path, starts with "/"
    permission: str | None = None  # None = any signed-in user


@dataclass(frozen=True)
class NavSection:
    key: str  # unique across sections
    label: str
    module: str
    order: int = 100
    items: tuple[NavItem, ...] = ()


@dataclass(frozen=True)
class HealthCheck:
    key: str
    label: str
    check: Callable[[], bool]
    critical: bool = True


@dataclass(frozen=True)
class DataPlaneCheck:
    """A required-rows check (OBSERVABILITY § 7). fn returns core.dataplane.ok/warn/fatal."""

    key: str  # "core.active_superuser": <owner>.<what>
    description: str
    fn: Callable[[], object]


@dataclass(frozen=True)
class EncryptedField:
    """A column holding ciphertext from core.crypto, so rotation knows the complete set (§ 25)."""

    model: str  # "users.MfaDevice"
    field: str  # "totp_secret_ciphertext"
    purpose: str  # "mfa_totp"

    @property
    def key(self) -> str:
        return f"{self.model}.{self.field}"


@dataclass(frozen=True)
class ApiRoute:
    prefix: str  # "billing" → mounted at /api/billing/
    urlconf: str  # dotted module path


class RegistryError(Exception):
    """A declaration a catalog refuses. Raised at boot, naming the offender."""


# --- The shared mechanics -----------------------------------------------------------------------


class _Catalog:
    """Register until the first read, then frozen. Each register() is all or nothing."""

    def __init__(self) -> None:
        self._sealed = False
        self._lock = threading.Lock()
        self._owner_of: dict[str, str] = {}

    def owner(self, key: str) -> str:
        """The module that registered `key` (best effort), or "" when nothing registered it.
        The plugin conventions test attributes registrations by it (BUILD_ORDER 3.2)."""
        return self._owner_of.get(key, "")

    def seal(self) -> None:
        with self._lock:
            self._sealed = True

    @property
    def sealed(self) -> bool:
        return self._sealed

    def _refuse_if_sealed(self, what: str) -> None:
        # Caller holds the lock.
        if self._sealed:
            raise RegistryError(
                f"{what} registered after the catalog was sealed (it was already read). "
                "Register from AppConfig.ready()."
            )


def _require_label(name: str, label: object) -> None:
    if not isinstance(label, str) or not label.strip():
        raise RegistryError(f"{name} has an empty label")


# --- Permissions --------------------------------------------------------------------------------


class PermissionRegistry(_Catalog):
    def __init__(self) -> None:
        super().__init__()
        self._groups: dict[str, PermissionGroupSpec] = {}
        self._group_by_code: dict[str, PermissionGroupSpec] = {}

    def register(self, group: PermissionGroupSpec) -> None:
        """All or nothing: a refused group leaves the catalog exactly as it was."""
        owner = _caller_module()
        with self._lock:
            self._refuse_if_sealed(f"permission group {getattr(group, 'code', group)!r}")
            self._validate(group)
            self._groups[group.code] = group
            self._owner_of[group.code] = owner
            for spec in group.permissions:
                self._group_by_code[spec.code] = group

    def groups(self) -> tuple[PermissionGroupSpec, ...]:
        self.seal()
        return tuple(sorted(self._groups.values(), key=lambda g: (g.order, g.code)))

    def codes(self) -> frozenset[str]:
        self.seal()
        return frozenset(self._group_by_code)

    def group_for(self, code: str) -> PermissionGroupSpec:
        """The group declaring `code`. KeyError when no group does."""
        self.seal()
        return self._group_by_code[code]

    def _validate(self, group: PermissionGroupSpec) -> None:
        if not isinstance(group, PermissionGroupSpec):
            raise RegistryError(f"expected a PermissionGroupSpec, got {type(group).__name__}")
        name = f"permission group {group.code!r}"
        if not isinstance(group.code, str) or not group.code.strip():
            raise RegistryError(f"{name} has an empty code")
        _require_label(name, group.label)
        if not isinstance(group.module, str) or not _MODULE_PATTERN.match(group.module):
            raise RegistryError(
                f"{name} has module {group.module!r}: lowercase letters, digits and _ only"
            )
        if group.code in self._groups:
            raise RegistryError(
                f"{name} is already registered (module {self._groups[group.code].module!r}). "
                "Group codes are unique; a second registration is a conflict, not an update."
            )

        seen: set[str] = set()
        for spec in group.permissions:
            if not isinstance(spec, PermissionSpec):
                raise RegistryError(f"{name} lists {spec!r}, which is not a PermissionSpec")
            if not isinstance(spec.code, str) or not CODE_PATTERN.match(spec.code):
                raise RegistryError(
                    f"{name}: permission code {spec.code!r} is not <module>.<feature>.<action> "
                    "(lowercase letters, digits and _, starting with a letter)"
                )
            module = spec.code.split(".", 1)[0]
            if module != group.module:
                raise RegistryError(
                    f"{name}: permission {spec.code!r} is outside its module {group.module!r}. "
                    f"A module declares only codes that start with '{group.module}.' (A7)."
                )
            _require_label(f"{name}: permission {spec.code!r}", spec.label)
            if spec.code in seen:
                raise RegistryError(f"{name} lists permission {spec.code!r} twice")
            if spec.code in self._group_by_code:
                owner = self._group_by_code[spec.code].code
                raise RegistryError(
                    f"{name}: permission {spec.code!r} is already declared by group {owner!r}"
                )
            seen.add(spec.code)


# --- Navigation ---------------------------------------------------------------------------------


class NavigationRegistry(_Catalog):
    """
    Sidebar sections. Each item names the permission that gates it, and sealing checks every one
    against the sibling PermissionRegistry, so a nav item can never point at a typo'd code (the
    nav-side twin of dbx.E002). Sealing navigation therefore seals permissions too: reading the
    nav means boot is over for both.
    """

    def __init__(self, permissions: PermissionRegistry) -> None:
        super().__init__()
        self._permissions = permissions
        self._sections: dict[str, NavSection] = {}

    def register(self, section: NavSection) -> None:
        owner = _caller_module()
        with self._lock:
            self._refuse_if_sealed(f"nav section {getattr(section, 'key', section)!r}")
            self._validate(section)
            self._sections[section.key] = section
            self._owner_of[section.key] = owner

    def sections(self) -> tuple[NavSection, ...]:
        self.seal()
        return tuple(sorted(self._sections.values(), key=lambda s: (s.order, s.key)))

    def visible_to(self, codes: frozenset[str], is_superuser: bool) -> tuple[NavSection, ...]:
        """Items the user may follow (a superuser, all of them); sections left empty are dropped.
        This only shapes a menu: every endpoint still decides for itself."""
        visible = []
        for section in self.sections():
            items = tuple(
                item
                for item in section.items
                if is_superuser or item.permission is None or item.permission in codes
            )
            if items:
                visible.append(replace(section, items=items))
        return tuple(visible)

    def seal(self) -> None:
        """Refuses to seal while any item names an undeclared permission, so every read raises
        until it is fixed, rather than the first read raising and later ones passing."""
        with self._lock:
            if self._sealed:
                return
            known = self._permissions.codes()
            unknown = [
                f"{section.key}/{item.key} → {item.permission!r}"
                for section in self._sections.values()
                for item in section.items
                if item.permission is not None and item.permission not in known
            ]
            if unknown:
                raise RegistryError(
                    "nav items gated on permissions no app declares (each would be hidden from "
                    "everyone but superusers): " + ", ".join(sorted(unknown))
                )
            self._sealed = True

    def _validate(self, section: NavSection) -> None:
        if not isinstance(section, NavSection):
            raise RegistryError(f"expected a NavSection, got {type(section).__name__}")
        name = f"nav section {section.key!r}"
        if not isinstance(section.key, str) or not _KEY_PATTERN.match(section.key):
            raise RegistryError(f"{name}: key must be lowercase letters, digits, _ and -")
        _require_label(name, section.label)
        if not isinstance(section.module, str) or not _MODULE_PATTERN.match(section.module):
            raise RegistryError(
                f"{name} has module {section.module!r}: lowercase letters, digits and _ only"
            )
        if section.key in self._sections:
            raise RegistryError(
                f"{name} is already registered (module {self._sections[section.key].module!r})"
            )

        seen: set[str] = set()
        for item in section.items:
            if not isinstance(item, NavItem):
                raise RegistryError(f"{name} lists {item!r}, which is not a NavItem")
            where = f"{name}: item {item.key!r}"
            if not isinstance(item.key, str) or not _KEY_PATTERN.match(item.key):
                raise RegistryError(f"{where}: key must be lowercase letters, digits, _ and -")
            if item.key in seen:
                raise RegistryError(f"{name} lists item {item.key!r} twice")
            _require_label(where, item.label)
            # "//host" is protocol-relative: a link that leaves the site.
            if (
                not isinstance(item.path, str)
                or not item.path.startswith("/")
                or item.path.startswith("//")
            ):
                raise RegistryError(f"{where}: path {item.path!r} must be a site path starting /")
            if item.permission is not None and (
                not isinstance(item.permission, str) or not CODE_PATTERN.match(item.permission)
            ):
                raise RegistryError(
                    f"{where}: permission {item.permission!r} is not <module>.<feature>.<action>"
                )
            seen.add(item.key)


# --- Health -------------------------------------------------------------------------------------


class HealthRegistry(_Catalog):
    """Readiness checks. A critical check failing makes the app not ready; others only report."""

    def __init__(self) -> None:
        super().__init__()
        self._checks: dict[str, HealthCheck] = {}

    def register(self, check: HealthCheck) -> None:
        owner = _caller_module()
        with self._lock:
            self._refuse_if_sealed(f"health check {getattr(check, 'key', check)!r}")
            if not isinstance(check, HealthCheck):
                raise RegistryError(f"expected a HealthCheck, got {type(check).__name__}")
            name = f"health check {check.key!r}"
            if not isinstance(check.key, str) or not _KEY_PATTERN.match(check.key):
                raise RegistryError(f"{name}: key must be lowercase letters, digits, _ and -")
            _require_label(name, check.label)
            if not callable(check.check):
                raise RegistryError(f"{name}: check must be callable, got {check.check!r}")
            if not isinstance(check.critical, bool):
                raise RegistryError(f"{name}: critical must be True or False")
            if check.key in self._checks:
                raise RegistryError(f"{name} is already registered")
            self._checks[check.key] = check
            self._owner_of[check.key] = owner

    def checks(self) -> tuple[HealthCheck, ...]:
        """In registration order, which follows INSTALLED_APPS."""
        self.seal()
        return tuple(self._checks.values())


# --- Data-plane checks --------------------------------------------------------------------------


_DATAPLANE_KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_MODEL_LABEL = re.compile(r"^[a-z][a-z0-9_]*\.[A-Z][A-Za-z0-9]*$")
_PURPOSE = re.compile(r"^[a-z][a-z0-9_]*$")


class DataPlaneRegistry(_Catalog):
    """Required-rows checks, evaluated by core.dataplane. A fatal one means the product is
    impossible; the evaluator never raises, so a broken check is never worse than its gap."""

    def __init__(self) -> None:
        super().__init__()
        self._checks: dict[str, DataPlaneCheck] = {}

    def register(self, check: DataPlaneCheck) -> None:
        owner = _caller_module()
        with self._lock:
            self._refuse_if_sealed(f"data-plane check {getattr(check, 'key', check)!r}")
            if not isinstance(check, DataPlaneCheck):
                raise RegistryError(f"expected a DataPlaneCheck, got {type(check).__name__}")
            name = f"data-plane check {check.key!r}"
            if not isinstance(check.key, str) or not _DATAPLANE_KEY.match(check.key):
                raise RegistryError(f"{name}: key must be <owner>.<what>, lowercase")
            _require_label(name, check.description)
            if not callable(check.fn):
                raise RegistryError(f"{name}: fn must be callable, got {check.fn!r}")
            if check.key in self._checks:
                raise RegistryError(f"{name} is already registered")
            self._checks[check.key] = check
            self._owner_of[check.key] = owner

    def checks(self) -> tuple[DataPlaneCheck, ...]:
        self.seal()
        return tuple(self._checks.values())


# --- Encrypted fields ---------------------------------------------------------------------------


# --- Audit actions ------------------------------------------------------------------------------

# DATA_LIFECYCLE.md § 4.5: a closed set, so the UI has one colour map and a plugin cannot invent a
# fourteenth shade of red.
AUDIT_TONES = ("neutral", "info", "success", "warning", "danger", "security")
AUDIT_ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$")


@dataclass(frozen=True)
class AuditAction:
    key: str  # "module.entity.verb" (two to four segments: "auth.login", "rbac.role.created")
    label: str
    tone: str  # one of AUDIT_TONES
    channel: str  # auth · security · settings · rbac · data · per-plugin


class AuditActionRegistry(_Catalog):
    """Declared audit actions. An UNREGISTERED action still logs (losing an audit row because a
    label was missing is the wrong trade); this catalog only supplies label, tone and channel."""

    def __init__(self) -> None:
        super().__init__()
        self._actions: dict[str, AuditAction] = {}

    def register(self, *, key: str, label: str, tone: str, channel: str) -> None:
        owner = _caller_module()
        with self._lock:
            name = f"audit action {key!r}"
            self._refuse_if_sealed(name)
            if not isinstance(key, str) or not AUDIT_ACTION_PATTERN.match(key):
                raise RegistryError(f"{name}: not module.entity.verb (lowercase, digits, _)")
            _require_label(name, label)
            if tone not in AUDIT_TONES:
                raise RegistryError(f"{name}: tone {tone!r} is not one of {AUDIT_TONES}")
            if not isinstance(channel, str) or not _MODULE_PATTERN.match(channel):
                raise RegistryError(f"{name}: channel must be a lowercase identifier")
            if key in self._actions:
                raise RegistryError(
                    f"{name} is already registered by {self._owner_of[key]}; "
                    f"registered again by {owner}"
                )
            self._actions[key] = AuditAction(key, label, tone, channel)
            self._owner_of[key] = owner

    def get(self, key: str) -> AuditAction | None:
        self.seal()
        return self._actions.get(key)

    def actions(self) -> tuple[AuditAction, ...]:
        self.seal()
        return tuple(self._actions[k] for k in sorted(self._actions))


class EncryptedFieldRegistry(_Catalog):
    """Every column holding core.crypto ciphertext, so rotate_encryption walks the complete set.
    Purposes are validated against core.crypto's constants by a system check, not here: this
    module stays standard-library only."""

    def __init__(self) -> None:
        super().__init__()
        self._fields: dict[str, EncryptedField] = {}

    def register(self, spec: EncryptedField) -> None:
        owner = _caller_module()
        with self._lock:
            self._refuse_if_sealed(f"encrypted field {getattr(spec, 'key', spec)!r}")
            if not isinstance(spec, EncryptedField):
                raise RegistryError(f"expected an EncryptedField, got {type(spec).__name__}")
            name = f"encrypted field {spec.key!r}"
            if not isinstance(spec.model, str) or not _MODEL_LABEL.match(spec.model):
                raise RegistryError(f"{name}: model must be 'app_label.ModelName'")
            if not isinstance(spec.field, str) or not spec.field.endswith("_ciphertext"):
                raise RegistryError(f"{name}: field must be named *_ciphertext")
            if not _PURPOSE.match(spec.field[: -len("_ciphertext")] or "-"):
                raise RegistryError(f"{name}: field must be a lowercase identifier")
            if not isinstance(spec.purpose, str) or not _PURPOSE.match(spec.purpose):
                raise RegistryError(f"{name}: purpose must be lowercase letters, digits and _")
            if spec.key in self._fields:
                raise RegistryError(f"{name} is already registered")
            self._fields[spec.key] = spec
            self._owner_of[spec.key] = owner

    def fields(self) -> tuple[EncryptedField, ...]:
        self.seal()
        return tuple(self._fields.values())


# --- API routes ---------------------------------------------------------------------------------


class ApiRouteRegistry(_Catalog):
    """URLconfs mounted at /api/<prefix>/ by config/urls.py. Nothing is imported here: a urlconf
    that does not import fails where it is included, with Django's own error."""

    def __init__(self) -> None:
        super().__init__()
        self._routes: dict[str, ApiRoute] = {}

    def register(self, prefix: str, urlconf: str) -> None:
        owner = _caller_module()
        with self._lock:
            name = f"api route {prefix!r}"
            self._refuse_if_sealed(name)
            if not isinstance(prefix, str) or not PREFIX_PATTERN.match(prefix):
                raise RegistryError(
                    f"{name}: prefix must be lowercase letters, digits and -, starting with a "
                    "letter"
                )
            if prefix in RESERVED_PREFIXES:
                raise RegistryError(
                    f"{name}: /api/{prefix}/ is reserved for core "
                    f"(reserved: {', '.join(sorted(RESERVED_PREFIXES))})"
                )
            if not isinstance(urlconf, str) or not _DOTTED_PATTERN.match(urlconf):
                raise RegistryError(f"{name}: urlconf {urlconf!r} is not a dotted module path")
            if prefix in self._routes:
                raise RegistryError(
                    f"{name} is already registered for {self._routes[prefix].urlconf!r}"
                )
            for route in self._routes.values():
                if route.urlconf == urlconf:
                    raise RegistryError(
                        f"{name}: urlconf {urlconf!r} is already mounted at "
                        f"/api/{route.prefix}/. Mounting it twice duplicates every URL name."
                    )
            self._routes[prefix] = ApiRoute(prefix=prefix, urlconf=urlconf)
            self._owner_of[prefix] = owner

    def routes(self) -> tuple[ApiRoute, ...]:
        """Sorted by prefix, so the URL table does not depend on INSTALLED_APPS order."""
        self.seal()
        return tuple(sorted(self._routes.values(), key=lambda r: r.prefix))


# --- Public routes ------------------------------------------------------------------------------


class PublicRouteRegistry(_Catalog):
    """
    The exemption ledger as a seam (AUTH_BLUEPRINT § 9.2; EXTENSIBILITY § 9; TECH_DEBT DB-22).

    Every /api/ route refuses an anonymous caller unless its URL name is registered here with a
    reason. Core registers its own entries the same way a plugin does, so the route test and
    dbx.E007 read one union and a plugin never edits core to open an endpoint.
    """

    def __init__(self) -> None:
        super().__init__()
        self._routes: dict[str, str] = {}

    def register(self, url_name: str, reason: str) -> None:
        owner = _caller_module()
        with self._lock:
            name = f"public route {url_name!r}"
            self._refuse_if_sealed(name)
            if not isinstance(url_name, str) or not URL_NAME_PATTERN.match(url_name):
                raise RegistryError(
                    f"{name}: not a URL name. Use 'name' or 'namespace:name' (lowercase letters, "
                    "digits, _ and -)."
                )
            if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON_LENGTH:
                raise RegistryError(
                    f"{name}: the reason must be a sentence a reviewer can disagree with, at least "
                    f"{MIN_REASON_LENGTH} characters. It opens an endpoint to the internet."
                )
            if url_name in self._routes:
                raise RegistryError(
                    f"{name} is already registered by {self._owner_of[url_name]}; registered again "
                    f"by {owner}. One route, one reason."
                )
            self._routes[url_name] = reason.strip()
            self._owner_of[url_name] = owner

    def routes(self) -> Mapping[str, str]:
        """url_name → reason, sorted by name, read-only."""
        self.seal()
        return MappingProxyType(dict(sorted(self._routes.items())))


# --- Feature flags and guards ---------------------------------------------------------------------

# "<module>.<name>", two segments: a guard's mode setting appends ".mode" and must still be a valid
# three-segment setting key.
FLAG_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
GUARD_MODES = ("off", "log_only", "enforce")


@dataclass(frozen=True)
class FlagDef:
    """A temporary gate (CONFIGURATION.md § 11). State and targeting live in the database; the
    declaration carries what review owns: who answers for it and when it must be gone."""

    key: str
    owner: str  # a team or person who answers "can this be removed yet?"
    expires_on: date  # past it, CI fails (test_no_expired_flags)
    description: str


@dataclass(frozen=True)
class GuardDef:
    """A refusal added to live traffic (CONFIGURATION.md § 13). Its mode is the registry setting
    `<key>.mode`; core.guards.register_guard declares both, so no guard exists without a switch."""

    key: str
    default_mode: str  # today's behaviour: off or log_only; enforce needs a written reason
    description: str
    error_code: str  # the stable code an enforce refusal answers with
    enforce_reason: str = ""


class FlagRegistry(_Catalog):
    """Declared feature flags. An unregistered key is off, always; no default parameter exists."""

    def __init__(self) -> None:
        super().__init__()
        self._defs: dict[str, FlagDef] = {}

    def register(self, definition: FlagDef) -> None:
        owner = _caller_module()
        with self._lock:
            if not isinstance(definition, FlagDef):
                raise RegistryError(f"expected a FlagDef, got {type(definition).__name__}")
            name = f"flag {definition.key!r}"
            self._refuse_if_sealed(name)
            if not isinstance(definition.key, str) or not FLAG_KEY_PATTERN.match(definition.key):
                raise RegistryError(f"{name}: not <module>.<name> (lowercase, digits, _)")
            if not isinstance(definition.expires_on, date):
                raise RegistryError(f"{name} has no expiry date: flags are temporary (§ 11)")
            for field_name in ("owner", "description"):
                if (
                    not isinstance(getattr(definition, field_name), str)
                    or not getattr(definition, field_name).strip()
                ):
                    raise RegistryError(f"{name} has an empty {field_name}")
            if definition.key in self._defs:
                raise RegistryError(
                    f"{name} is already registered by {self._owner_of[definition.key]}; "
                    f"registered again by {owner}"
                )
            self._defs[definition.key] = definition
            self._owner_of[definition.key] = owner

    def __contains__(self, key: str) -> bool:
        self.seal()
        return key in self._defs

    def get(self, key: str) -> FlagDef:
        self.seal()
        return self._defs[key]

    def defs(self) -> tuple[FlagDef, ...]:
        self.seal()
        return tuple(self._defs[k] for k in sorted(self._defs))


class GuardRegistry(_Catalog):
    """Declared guards. Register through core.guards.register_guard, which also declares the
    `<key>.mode` setting — this catalog alone would be a guard without a switch."""

    def __init__(self) -> None:
        super().__init__()
        self._defs: dict[str, GuardDef] = {}

    def register(self, definition: GuardDef) -> None:
        owner = _caller_module()
        with self._lock:
            if not isinstance(definition, GuardDef):
                raise RegistryError(f"expected a GuardDef, got {type(definition).__name__}")
            name = f"guard {definition.key!r}"
            self._refuse_if_sealed(name)
            if not isinstance(definition.key, str) or not FLAG_KEY_PATTERN.match(definition.key):
                raise RegistryError(f"{name}: not <module>.<name> (lowercase, digits, _)")
            if definition.default_mode not in GUARD_MODES:
                raise RegistryError(f"{name}: default_mode must be one of {GUARD_MODES}")
            if definition.default_mode == "enforce" and not definition.enforce_reason.strip():
                raise RegistryError(
                    f"{name} defaults to enforce without a written reason (§ 13: the shipped "
                    "default is today's behaviour unless it closes a known vulnerability)"
                )
            for field_name in ("description", "error_code"):
                if (
                    not isinstance(getattr(definition, field_name), str)
                    or not getattr(definition, field_name).strip()
                ):
                    raise RegistryError(f"{name} has an empty {field_name}")
            if definition.key in self._defs:
                raise RegistryError(
                    f"{name} is already registered by {self._owner_of[definition.key]}; "
                    f"registered again by {owner}"
                )
            self._defs[definition.key] = definition
            self._owner_of[definition.key] = owner

    def get(self, key: str) -> GuardDef:
        self.seal()
        return self._defs[key]

    def defs(self) -> tuple[GuardDef, ...]:
        self.seal()
        return tuple(self._defs[k] for k in sorted(self._defs))


# --- Lookups --------------------------------------------------------------------------------------

# Seed entries: (key, label) or (key, label, is_system). A system entry is one code refers to by
# key (an "other — please specify"); it cannot be deactivated.
LOOKUP_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class LookupSetDef:
    """An admin-editable vocabulary (CONFIGURATION.md § 14). The set and its seed keys are code's;
    every value, label and ordering is the admin's, in core_lookup_value."""

    set_key: str  # "crm.lead_source" — <module>.<name>
    label: str
    seed: tuple = ()
    admin_can_add: bool = True
    meta_schema: Callable | None = None  # validates a value's meta dict; raises ValueError


class LookupRegistry(_Catalog):
    """Declared lookup sets. Membership of VALUES is the table's, at request time — this catalog
    only says which sets exist and what they seed."""

    def __init__(self) -> None:
        super().__init__()
        self._defs: dict[str, LookupSetDef] = {}

    def register(self, definition: LookupSetDef) -> None:
        owner = _caller_module()
        with self._lock:
            if not isinstance(definition, LookupSetDef):
                raise RegistryError(f"expected a LookupSetDef, got {type(definition).__name__}")
            name = f"lookup set {definition.set_key!r}"
            self._refuse_if_sealed(name)
            if not isinstance(definition.set_key, str) or not FLAG_KEY_PATTERN.match(
                definition.set_key
            ):
                raise RegistryError(f"{name}: not <module>.<name> (lowercase, digits, _)")
            _require_label(name, definition.label)
            seen = set()
            for entry in definition.seed:
                if not isinstance(entry, tuple) or len(entry) not in (2, 3):
                    raise RegistryError(f"{name}: seed entries are (key, label[, is_system])")
                key, label = entry[0], entry[1]
                if not isinstance(key, str) or not LOOKUP_KEY_PATTERN.match(key):
                    raise RegistryError(f"{name}: seed key {key!r} is not a slug")
                _require_label(f"{name}: seed {key!r}", label)
                if key in seen:
                    raise RegistryError(f"{name} seeds {key!r} twice")
                seen.add(key)
            if definition.set_key in self._defs:
                raise RegistryError(
                    f"{name} is already registered by {self._owner_of[definition.set_key]}; "
                    f"registered again by {owner}"
                )
            self._defs[definition.set_key] = definition
            self._owner_of[definition.set_key] = owner

    def __contains__(self, set_key: str) -> bool:
        self.seal()
        return set_key in self._defs

    def get(self, set_key: str) -> LookupSetDef:
        self.seal()
        return self._defs[set_key]

    def defs(self) -> tuple[LookupSetDef, ...]:
        self.seal()
        return tuple(self._defs[k] for k in sorted(self._defs))


# --- Settings -----------------------------------------------------------------------------------


class SettingRegistry(_Catalog):
    """
    Declared settings (CONFIGURATION.md § 9.1). A key exists only if a module registered it; the
    settings service refuses to read or write any other. The declarations themselves (SettingDef,
    the types, meta()) are core.settings_registry's. This catalog takes them by shape, so this
    module stays standard library only.
    """

    def __init__(self) -> None:
        super().__init__()
        self._defs: dict = {}
        self._policies: dict[type, dict[str, str]] = {}
        self._tenant_resolver: Callable | None = None

    def register(self, definition) -> None:
        self._add([definition], _caller_module())

    def register_group(
        self,
        policy: type,
        *,
        prefix: str,
        module: str,
        group: str,
        scopes: tuple[str, ...] | None = None,
        exposure: str | None = None,
    ) -> None:
        """
        A frozen dataclass of related settings: each field's default is the code default and its
        metadata comes from core.settings_registry.meta(). All or nothing.
        """
        owner = _caller_module()
        name = f"setting group {getattr(policy, '__name__', policy)!r}"
        params = getattr(policy, "__dataclass_params__", None)
        if params is None or not params.frozen:
            raise RegistryError(f"{name} is not a frozen dataclass")
        definitions, keys = [], {}
        for f in fields(policy):
            build = f.metadata.get(SETTING_METADATA_KEY)
            if build is None:
                raise RegistryError(f"{name}: field {f.name!r} has no meta(...) declaration")
            if f.default is MISSING:
                raise RegistryError(f"{name}: field {f.name!r} has no default (the code default)")
            fixed = {"scopes": scopes, "exposure": exposure}
            fixed = {k: v for k, v in fixed.items() if v is not None and k not in build.keywords}
            definitions.append(
                build(
                    key=f"{prefix}.{f.name}", default=f.default, module=module, group=group, **fixed
                )
            )
            keys[f.name] = f"{prefix}.{f.name}"
        if not definitions:
            raise RegistryError(f"{name} declares no fields")
        self._add(definitions, owner, policy=(policy, keys))

    def _add(self, definitions: list, owner: str, policy=None) -> None:
        with self._lock:
            for definition in definitions:
                key = getattr(definition, "key", None)
                name = f"setting {key!r}"
                self._refuse_if_sealed(name)
                if not callable(getattr(definition, "problems", None)):
                    raise RegistryError(f"expected a SettingDef, got {type(definition).__name__}")
                problems = definition.problems()
                if problems:
                    raise RegistryError(f"{name}: {'; '.join(problems)}")
                if key in self._defs or sum(d.key == key for d in definitions) > 1:
                    first = self._owner_of.get(key, owner)
                    raise RegistryError(
                        f"{name} is already registered by {first}; registered again by {owner}. "
                        "One key, one declaration."
                    )
            if policy is not None and policy[0] in self._policies:
                raise RegistryError(f"setting group {policy[0].__name__!r} is already registered")
            for definition in definitions:
                self._defs[definition.key] = definition
                self._owner_of[definition.key] = owner
            if policy is not None:
                self._policies[policy[0]] = policy[1]

    def set_tenant_resolver(self, resolver: Callable) -> None:
        """
        The tenant step of the cascade: resolver(user) -> the tenant's public id, or None. Core
        registers none (ADR-0011), so the step is inert until a tenancy module does.
        """
        owner = _caller_module()
        with self._lock:
            self._refuse_if_sealed("the tenant resolver")
            if not callable(resolver):
                raise RegistryError("the tenant resolver must be callable")
            if self._tenant_resolver is not None:
                raise RegistryError(
                    f"a tenant resolver is already registered by {self._owner_of['<tenant>']}; "
                    f"registered again by {owner}"
                )
            self._tenant_resolver = resolver
            self._owner_of["<tenant>"] = owner

    def tenant_resolver(self) -> Callable | None:
        self.seal()
        return self._tenant_resolver

    def get(self, key: str):
        """The declaration for `key`. UnknownSetting (from core.settings_registry) is the service's
        to raise; here a miss is a KeyError, like PermissionRegistry.group_for."""
        self.seal()
        return self._defs[key]

    def defs(self) -> tuple:
        """Every declaration, sorted by key."""
        self.seal()
        return tuple(self._defs[k] for k in sorted(self._defs))

    def keys_of(self, policy: type) -> Mapping[str, str]:
        """field name → key, for a policy registered with register_group(). KeyError otherwise."""
        self.seal()
        return MappingProxyType(self._policies[policy])

    def policies(self) -> Mapping[type, Mapping[str, str]]:
        """Every registered policy class → its field-name-to-key map. For the § 9.11 reader scan."""
        self.seal()
        return MappingProxyType({p: MappingProxyType(k) for p, k in self._policies.items()})


def _caller_module() -> str:
    """The module that called register(), for naming both sides of a duplicate. Best effort."""
    try:
        return sys._getframe(2).f_globals.get("__name__", "an unknown module")
    except ValueError:
        return "an unknown module"


# --- The whole seam -----------------------------------------------------------------------------


class Registry:
    """Everything apps contribute at boot. Each instance owns its own catalogs."""

    def __init__(self) -> None:
        self.permissions = PermissionRegistry()
        # Navigation checks its items against THIS registry's permissions, never another's.
        self.navigation = NavigationRegistry(self.permissions)
        self.health = HealthRegistry()
        self.dataplane = DataPlaneRegistry()
        self.encrypted_fields = EncryptedFieldRegistry()
        self.audit_actions = AuditActionRegistry()
        self.api_routes = ApiRouteRegistry()
        self.public_routes = PublicRouteRegistry()
        self.settings = SettingRegistry()
        self.flags = FlagRegistry()
        self.lookups = LookupRegistry()
        self.guards = GuardRegistry()


# The process-wide instance. Tests build their own and never touch this one.
registry = Registry()
