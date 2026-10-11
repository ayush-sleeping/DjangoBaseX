"""
The shared vocabulary every app declares into (AUTH_BLUEPRINT § 2, § 7.1, § 7.2).

Standard library only: nothing from core, rbac or any app. An app declares its permissions by
importing this module, never rbac, so no module depends on authorization's models just to name a
right (A6, A7).

Boot-time and one-way. Apps register() from AppConfig.ready(); the first read (groups(), codes(),
group_for()) seals the catalog, and every later register() raises. Nothing has to know when boot
finished: the system checks read the catalog after django.setup(), which is what seals it on every
manage.py invocation (§ 7.2).
"""

import re
import threading
from dataclasses import dataclass

# "<module>.<feature>.<action>". The action is deliberately not checked against a fixed list:
# the vocabulary in § 7.1 is guidance, and real codes need verbs like "send" and "revoke".
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_MODULE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


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


class RegistryError(Exception):
    """A declaration the catalog refuses. Raised at boot, naming the offender."""


class PermissionRegistry:
    def __init__(self) -> None:
        self._groups: dict[str, PermissionGroupSpec] = {}
        self._group_by_code: dict[str, PermissionGroupSpec] = {}
        self._sealed = False
        self._lock = threading.Lock()

    def register(self, group: PermissionGroupSpec) -> None:
        """All or nothing: a refused group leaves the catalog exactly as it was."""
        with self._lock:
            if self._sealed:
                raise RegistryError(
                    f"permission group {getattr(group, 'code', group)!r} registered after the "
                    "catalog was sealed (it was already read). Register from AppConfig.ready()."
                )
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

    def seal(self) -> None:
        with self._lock:
            self._sealed = True

    @property
    def sealed(self) -> bool:
        return self._sealed

    def _validate(self, group: PermissionGroupSpec) -> None:
        if not isinstance(group, PermissionGroupSpec):
            raise RegistryError(f"expected a PermissionGroupSpec, got {type(group).__name__}")
        name = f"permission group {group.code!r}"
        if not isinstance(group.code, str) or not group.code.strip():
            raise RegistryError(f"{name} has an empty code")
        if not isinstance(group.label, str) or not group.label.strip():
            raise RegistryError(f"{name} has an empty label")
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
            if not isinstance(spec.label, str) or not spec.label.strip():
                raise RegistryError(f"{name}: permission {spec.code!r} has an empty label")
            if spec.code in seen:
                raise RegistryError(f"{name} lists permission {spec.code!r} twice")
            if spec.code in self._group_by_code:
                owner = self._group_by_code[spec.code].code
                raise RegistryError(
                    f"{name}: permission {spec.code!r} is already declared by group {owner!r}"
                )
            seen.add(spec.code)


class Registry:
    """Everything apps contribute at boot. 1.3 adds navigation, settings and health beside it."""

    def __init__(self) -> None:
        self.permissions = PermissionRegistry()


# The process-wide instance. Tests build their own PermissionRegistry() and never touch this one.
registry = Registry()
