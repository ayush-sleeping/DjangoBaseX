"""
The seam every app contributes through (AUTH_BLUEPRINT § 2, § 7.1, § 7.2, and § 2 of
CORE_ARCHITECTURE_PLAN).

Standard library only: nothing from core, rbac or any app. An app declares its permissions, its
navigation, its health checks and its API routes by importing this module, never rbac or core, so
no module depends on another's models just to plug in (A6, A7).

Boot-time and one-way. Apps register() from AppConfig.ready(); the first read of a catalog seals
it, and every later register() raises. Nothing has to know when boot finished: the system checks
and config/urls.py read the catalogs after django.setup(), which is what seals them on every
manage.py invocation (§ 7.2). There is no unregister: a catalog that changes under a running app
answers differently depending on when you ask.

A registry holds a key, a label and at most a callable, never an app's model or schema.
"""

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace

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
    {"admin", "api", "auth", "core", "docs", "health", "rbac", "schema", "users"}
)


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
        with self._lock:
            self._refuse_if_sealed(f"permission group {getattr(group, 'code', group)!r}")
            self._validate(group)
            self._groups[group.code] = group
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
        with self._lock:
            self._refuse_if_sealed(f"nav section {getattr(section, 'key', section)!r}")
            self._validate(section)
            self._sections[section.key] = section

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

    def checks(self) -> tuple[HealthCheck, ...]:
        """In registration order, which follows INSTALLED_APPS."""
        self.seal()
        return tuple(self._checks.values())


# --- API routes ---------------------------------------------------------------------------------


class ApiRouteRegistry(_Catalog):
    """URLconfs mounted at /api/<prefix>/ by config/urls.py. Nothing is imported here: a urlconf
    that does not import fails where it is included, with Django's own error."""

    def __init__(self) -> None:
        super().__init__()
        self._routes: dict[str, ApiRoute] = {}

    def register(self, prefix: str, urlconf: str) -> None:
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

    def routes(self) -> tuple[ApiRoute, ...]:
        """Sorted by prefix, so the URL table does not depend on INSTALLED_APPS order."""
        self.seal()
        return tuple(sorted(self._routes.values(), key=lambda r: r.prefix))


# --- The whole seam -----------------------------------------------------------------------------


class Registry:
    """Everything apps contribute at boot. Each instance owns its own catalogs."""

    def __init__(self) -> None:
        self.permissions = PermissionRegistry()
        # Navigation checks its items against THIS registry's permissions, never another's.
        self.navigation = NavigationRegistry(self.permissions)
        self.health = HealthRegistry()
        self.api_routes = ApiRouteRegistry()


# The process-wide instance. Tests build their own and never touch this one.
registry = Registry()
