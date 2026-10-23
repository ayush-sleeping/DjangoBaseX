"""
What a setting is: its type, its strict coercion and its declaration (CONFIGURATION.md § 9.1, § 9.4;
BUILD_ORDER 5.3). The catalog that holds the declarations is `registry.settings` (core/registry.py);
reading and writing values is core/settings_service.py.

Standard library only (core.registry is too): a module declares its settings by importing this,
never a model. Nothing here touches the database or Django.

    registry.settings.register(SettingDef(
        key="security.lockout.threshold",
        type=Int(min=3, max=100),
        default=10,
        label="Failed sign-ins before an account is locked",
        description="Lower locks attackers out sooner and locks real people out more often.",
        group="Sign-in protection", module="users",
        changed_by_event="A credential-stuffing wave, or support load from lockouts",
        used_by=("Sign-in",),
    ))

Or a frozen dataclass of related settings, whose field defaults ARE the code defaults (§ 9.6):

    @dataclass(frozen=True)
    class ReauthPolicy:
        window_minutes: int = field(default=15, metadata=meta(Int(min=1, max=1440), label=..., ...))

    registry.settings.register_group(ReauthPolicy, prefix="security.reauth", module="users",
                                     group="Re-authentication")

Coercion is strict: "false" is never True, True is never 1, a float is never a decimal. A value is
checked against its bounds when written and clamped to them when read, so a row written before a
floor existed cannot get past it.
"""

import decimal
import functools
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.registry import SETTING_METADATA_KEY

# Resolution order, most specific first (§ 9.5). A declaration allows a subset.
SCOPES = ("user", "tenant", "platform")
# Namespaces any core app may use besides its own label (§ 9.1).
RESERVED_NAMESPACES = frozenset({"platform", "security"})
EXPOSURES = frozenset({"private", "authenticated", "public"})
# "<namespace>.<group>.<name>": dotted, namespaced, stable, the API contract. Two segments are
# allowed ONLY under the reserved namespaces (the § 15 platform identity keys); a module's or
# plugin's key always carries its group, so "namespace = module" keeps meaning something.
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$")
TWO_SEGMENT = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_MODULE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class SettingError(Exception):
    code = "invalid_setting"


class UnknownSetting(SettingError):
    """An unregistered key. Always raised, never defaulted: a typo is not a value (§ 9.6)."""

    code = "unknown_setting"

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"{key!r} is not a registered setting.")


class SettingInvalid(SettingError):
    """A value the setting's type or bounds refuse. Names the key and the rule, never the value."""

    code = "invalid_value"

    def __init__(self, key: str, rule: str):
        self.key, self.rule = key, rule
        super().__init__(f"{key} {rule}.")


# --- Types ---------------------------------------------------------------------------------------
#
# Each type turns a JSON value (the API, the database) or a text value (the CLI) into a Python
# value, or raises ValueError with the rule it broke. Bounds are separate from parsing: a write
# checks them, a read clamps to them.


class SettingType:
    name = ""

    def parse(self, value: Any) -> Any:
        """A JSON value of the right shape, or ValueError. No bounds."""
        raise NotImplementedError

    def parse_text(self, text: str) -> Any:
        return self.parse(text)

    def check(self, value: Any) -> None:
        """ValueError when `value` is outside the bounds."""

    def clamp(self, value: Any) -> Any:
        return value

    def to_json(self, value: Any) -> Any:
        return value

    def describe(self) -> dict:
        """The type as the settings screen needs it."""
        return {"type": self.name}


@dataclass(frozen=True)
class _Bounded(SettingType):
    min: Any = None
    max: Any = None

    def check(self, value):
        if self.min is not None and value < self.min:
            raise ValueError(f"must be at least {self.min}")
        if self.max is not None and value > self.max:
            raise ValueError(f"must be at most {self.max}")

    def clamp(self, value):
        if self.min is not None and value < self.min:
            return self.min
        if self.max is not None and value > self.max:
            return self.max
        return value

    def describe(self):
        return {"type": self.name, "min": self.to_json(self.min), "max": self.to_json(self.max)}


@dataclass(frozen=True)
class Bool(SettingType):
    name = "bool"
    # From text, only these. "false" read as True is how a security control is quietly off (§ 9.4).
    TEXT = {"true": True, "false": False, "1": True, "0": False}

    def parse(self, value):
        if type(value) is not bool:
            raise ValueError("must be true or false")
        return value

    def parse_text(self, text):
        try:
            return self.TEXT[text.strip()]
        except KeyError:
            raise ValueError("must be one of true, false, 1, 0") from None


@dataclass(frozen=True)
class Int(_Bounded):
    name = "int"

    def parse(self, value):
        if type(value) is not int:  # bool is an int subclass; a float is not a whole number
            raise ValueError("must be a whole number")
        return value

    def parse_text(self, text):
        if not re.fullmatch(r"-?[0-9]+", text.strip()):
            raise ValueError("must be a whole number")
        return int(text.strip())


@dataclass(frozen=True)
class Decimal(_Bounded):
    name = "decimal"

    def parse(self, value):
        # Strings only: a float has already lost the cents it was meant to hold.
        if not isinstance(value, str):
            raise ValueError("must be a decimal number written as a string")
        try:
            number = decimal.Decimal(value.strip())
        except decimal.InvalidOperation:
            raise ValueError("must be a decimal number") from None
        if not number.is_finite():
            raise ValueError("must be a finite decimal number")
        return number

    def to_json(self, value):
        return None if value is None else str(value)


@dataclass(frozen=True)
class String(SettingType):
    max_length: int = 1000
    name = "string"

    def parse(self, value):
        if not isinstance(value, str):
            raise ValueError("must be text")
        if len(value) > self.max_length:
            raise ValueError(f"must be at most {self.max_length} characters")
        return value

    def describe(self):
        return {"type": self.name, "max_length": self.max_length}


@dataclass(frozen=True)
class Text(String):
    max_length: int = 20000
    name = "text"


@dataclass(frozen=True)
class Choice(SettingType):
    choices: tuple[str, ...] = ()
    name = "choice"

    def parse(self, value):
        if not isinstance(value, str) or value not in self.choices:
            raise ValueError(f"must be one of {', '.join(self.choices)}")
        return value

    def describe(self):
        return {"type": self.name, "choices": list(self.choices)}


@dataclass(frozen=True)
class StrList(SettingType):
    """A set of names, e.g. the actions that need re-authentication. Read as a tuple; written as a
    JSON list; from text, comma-separated. `choices`, when given, is the closed vocabulary."""

    choices: tuple[str, ...] | None = None
    name = "str_list"

    def parse(self, value):
        if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
            raise ValueError("must be a list of names")
        items = tuple(v.strip() for v in value)
        if any(not v for v in items):
            raise ValueError("must not contain an empty name")
        if len(set(items)) != len(items):
            raise ValueError("must not list a name twice")
        if self.choices is not None:
            unknown = sorted(set(items) - set(self.choices))
            if unknown:
                raise ValueError(f"lists {', '.join(unknown)}, not among {', '.join(self.choices)}")
        return items

    def parse_text(self, text):
        return self.parse([v for v in text.split(",") if v.strip()])

    def to_json(self, value):
        return None if value is None else list(value)

    def describe(self):
        choices = None if self.choices is None else list(self.choices)
        return {"type": self.name, "choices": choices}


@dataclass(frozen=True)
class Json(SettingType):
    """Any JSON value; `validator(value)` raises ValueError for a shape the reader cannot use."""

    validator: Callable[[Any], None] | None = None
    name = "json"

    def parse(self, value):
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("must be a JSON value") from None
        if self.validator is not None:
            self.validator(value)
        return value

    def parse_text(self, text):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            raise ValueError("must be a JSON value") from None
        return self.parse(value)


# --- The declaration -----------------------------------------------------------------------------


@dataclass(frozen=True)
class SettingDef:
    key: str  # "<namespace>.<group>.<name>"
    type: SettingType
    default: Any  # the SAFE value: a switch that enables risk defaults off (§ 9.6)
    label: str  # a sentence
    description: str  # the consequence of changing it
    group: str
    module: str  # the registering app's label
    changed_by_event: str  # what happens in the world that makes someone change it (§ 10)
    used_by: tuple[str, ...]  # the surfaces it governs (§ 9.12)
    scopes: tuple[str, ...] = ("platform",)
    exposure: str = "private"  # private · authenticated · public
    nullable: bool = False  # None is a legitimate answer ("unlimited"), never zero (§ 9.4)

    # Coercion. Every failure is SettingInvalid naming this key.

    def _parse(self, value, parse):
        if value is None:
            if self.nullable:
                return None
            raise SettingInvalid(self.key, "is required")
        try:
            return parse(value)
        except ValueError as exc:
            raise SettingInvalid(self.key, str(exc)) from None

    def coerce(self, value: Any) -> Any:
        """A JSON value to write: shape and bounds both enforced."""
        parsed = self._parse(value, self.type.parse)
        if parsed is not None:
            try:
                self.type.check(parsed)
            except ValueError as exc:
                raise SettingInvalid(self.key, str(exc)) from None
        return parsed

    def coerce_text(self, text: str) -> Any:
        """Text from the CLI: shape and bounds both enforced."""
        if self.nullable and text.strip().lower() == "null":
            return None
        parsed = self._parse(text, self.type.parse_text)
        try:
            self.type.check(parsed)
        except ValueError as exc:
            raise SettingInvalid(self.key, str(exc)) from None
        return parsed

    def read(self, stored: Any) -> Any:
        """A stored value to use: shape enforced, bounds clamped (§ 9.4)."""
        parsed = self._parse(stored, self.type.parse)
        return parsed if parsed is None else self.type.clamp(parsed)

    def to_json(self, value: Any) -> Any:
        return self.type.to_json(value)

    @property
    def namespace(self) -> str:
        return self.key.split(".", 1)[0]

    def problems(self) -> list[str]:
        """Why this declaration cannot be registered; empty when it can. The catalog raises them."""
        out = []
        if not isinstance(self.key, str) or not KEY_PATTERN.match(self.key):
            return [f"key {self.key!r} is not <namespace>.<group>.<name> (a-z, 0-9, _)"]
        if TWO_SEGMENT.match(self.key) and self.namespace not in RESERVED_NAMESPACES:
            return [
                f"key {self.key!r} has two segments: only the reserved namespaces "
                f"({', '.join(sorted(RESERVED_NAMESPACES))}) may drop the group"
            ]
        if not isinstance(self.module, str) or not _MODULE_PATTERN.match(self.module):
            out.append(f"module {self.module!r}: lowercase letters, digits and _ only")
        elif self.namespace != self.module and self.namespace not in RESERVED_NAMESPACES:
            out.append(
                f"key starts {self.namespace!r}: a module declares keys under its own label "
                f"({self.module}.) or a reserved one ({', '.join(sorted(RESERVED_NAMESPACES))})"
            )
        if not isinstance(self.type, SettingType):
            out.append(f"type {self.type!r} is not a setting type (Bool, Int, Decimal, ...)")
        for name in ("label", "description", "group", "changed_by_event"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                out.append(f"has an empty {name}")
        if (
            not isinstance(self.used_by, tuple)
            or not self.used_by
            or not all(isinstance(u, str) and u.strip() for u in self.used_by)
        ):
            out.append("used_by must name at least one surface, as a tuple of strings")
        if (
            not isinstance(self.scopes, tuple)
            or not self.scopes
            or len(set(self.scopes)) != len(self.scopes)
            or not set(self.scopes) <= set(SCOPES)
        ):
            out.append(f"scopes {self.scopes!r} must be a tuple drawn from {SCOPES}")
        if self.exposure not in EXPOSURES:
            out.append(f"exposure {self.exposure!r} is not one of {sorted(EXPOSURES)}")
        if not out:
            try:
                self.coerce(self.to_json(self.default))
            except SettingInvalid as exc:
                out.append(f"its default fails its own type: {exc.rule}")
        return out


def meta(
    type: SettingType,
    *,
    label: str,
    description: str,
    changed_by_event: str,
    used_by: tuple[str, ...],
    scopes: tuple[str, ...] | None = None,
    exposure: str | None = None,
    nullable: bool = False,
) -> dict:
    """
    One field's declaration, for a policy dataclass registered with register_group(). The type is
    explicit, never inferred from the annotation: `int` cannot say min=1.
    """
    fixed = {"scopes": scopes, "exposure": exposure}
    return {
        SETTING_METADATA_KEY: functools.partial(
            SettingDef,
            type=type,
            label=label,
            description=description,
            changed_by_event=changed_by_event,
            used_by=used_by,
            nullable=nullable,
            **{k: v for k, v in fixed.items() if v is not None},
        )
    }


def stored(value: Any) -> dict:
    """The row's JSON, always wrapped: a stored false, 0, "" or null is never "no row" (§ 9.3)."""
    return {"v": value}


def unwrap(row_value: Any) -> Any:
    """The value inside a row's wrapper. ValueError for a row not written by the service."""
    if not isinstance(row_value, dict) or set(row_value) != {"v"}:
        raise ValueError('is not stored as {"v": ...}')
    return row_value["v"]
