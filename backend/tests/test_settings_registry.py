"""The settings catalog and its strict coercion (CONFIGURATION.md § 9.1, § 9.3, § 9.4)."""

from dataclasses import dataclass, field

import pytest

from core.registry import Registry, RegistryError
from core.settings_registry import (
    Bool,
    Choice,
    Decimal,
    Int,
    Json,
    SettingDef,
    SettingInvalid,
    String,
    StrList,
    Text,
    meta,
    stored,
    unwrap,
)


def define(**overrides) -> SettingDef:
    base = dict(
        key="users.probe.limit",
        type=Int(min=1, max=100),
        default=10,
        label="A probe limit",
        description="Lower is stricter.",
        group="Probes",
        module="users",
        changed_by_event="A test",
        used_by=("Tests",),
    )
    base.update(overrides)
    return SettingDef(**base)


@pytest.fixture
def reg():
    return Registry().settings


# --- Coercion: validation and casting in one strict step (§ 9.4) ---------------------------------


def test_bool_accepts_only_json_booleans_and_the_four_text_forms():
    d = define(type=Bool(), default=False)
    assert d.coerce(False) is False and d.coerce(True) is True
    assert d.coerce_text("false") is False  # the § 9.4 bug: "false" must never read as True
    assert d.coerce_text("1") is True and d.coerce_text("0") is False
    for bad in ("yes", "False ish", "", "no"):
        with pytest.raises(SettingInvalid):
            d.coerce_text(bad)
    for bad in ("false", 0, 1, None):
        with pytest.raises(SettingInvalid):
            d.coerce(bad)


def test_int_rejects_bool_float_and_text_that_is_not_a_whole_number():
    d = define()
    assert d.coerce(42) == 42
    assert d.coerce_text(" 42 ") == 42
    for bad in (True, 3.0, "42", None):
        with pytest.raises(SettingInvalid):
            d.coerce(bad)
    with pytest.raises(SettingInvalid):
        d.coerce_text("3.5")


def test_bounds_are_validated_on_write_and_clamped_on_read():
    d = define()
    with pytest.raises(SettingInvalid, match="at least 1"):
        d.coerce(0)
    with pytest.raises(SettingInvalid, match="at most 100"):
        d.coerce_text("1000")
    assert d.read(0) == 1 and d.read(1000) == 100  # a row written before the floor existed


def test_decimal_takes_strings_only_and_refuses_nan():
    d = define(type=Decimal(min=None, max=None), default="1.5")
    assert str(d.coerce("2.50")) == "2.50"
    for bad in (2.5, 1, "NaN", "Infinity", "x"):
        with pytest.raises(SettingInvalid):
            d.coerce(bad)


def test_string_text_choice_and_json(reg):
    assert define(type=String(max_length=3), default="ab").coerce("abc") == "abc"
    with pytest.raises(SettingInvalid):
        define(type=String(max_length=3), default="ab").coerce("abcd")
    assert define(type=Text(), default="x").coerce("y" * 2000) == "y" * 2000
    c = define(type=Choice(choices=("a", "b")), default="a")
    assert c.coerce("b") == "b"
    with pytest.raises(SettingInvalid):
        c.coerce("c")

    def only_lists(v):
        if not isinstance(v, list):
            raise ValueError("must be a list")

    j = define(type=Json(validator=only_lists), default=[])
    assert j.coerce([1, "two"]) == [1, "two"]
    with pytest.raises(SettingInvalid):
        j.coerce({"not": "a list"})


def test_str_list_is_closed_deduplicated_and_comma_separated_from_text():
    d = define(type=StrList(choices=("mfa_disable", "export")), default=())
    assert d.coerce(["mfa_disable"]) == ("mfa_disable",)
    assert d.coerce_text("mfa_disable, export") == ("mfa_disable", "export")
    assert d.coerce_text("") == ()
    for bad in (["unknown"], ["mfa_disable", "mfa_disable"], "mfa_disable", [1]):
        with pytest.raises(SettingInvalid):
            d.coerce(bad)


def test_null_is_explicit_never_a_zero(reg):
    with pytest.raises(SettingInvalid, match="is required"):
        define().coerce(None)
    d = define(nullable=True, default=None)
    assert d.coerce(None) is None and d.coerce_text("null") is None


def test_the_wrapper_round_trips_the_indistinguishable_values():
    for value in (False, 0, "", None):  # § 9.3: each must differ from "no row"
        assert unwrap(stored(value)) == value
    for bad in (False, {"value": 1}, {"v": 1, "x": 2}, []):
        with pytest.raises(ValueError):
            unwrap(bad)


# --- Declarations and the catalog (§ 9.1) ---------------------------------------------------------


def test_a_key_outside_the_modules_namespace_is_refused(reg):
    with pytest.raises(RegistryError, match="under its own label"):
        reg.register(define(key="billing.probe.limit"))
    reg.register(define(key="security.probe.limit"))  # reserved namespaces are open to core apps


def test_a_default_that_fails_its_own_type_is_refused(reg):
    with pytest.raises(RegistryError, match="default fails its own type"):
        reg.register(define(default=0))


def test_duplicate_keys_bad_scopes_and_empty_prose_are_refused(reg):
    reg.register(define())
    with pytest.raises(RegistryError, match="already registered"):
        reg.register(define())
    with pytest.raises(RegistryError, match="scopes"):
        reg.register(define(key="users.probe.other", scopes=("galaxy",)))
    with pytest.raises(RegistryError, match="empty label"):
        reg.register(define(key="users.probe.other", label=" "))
    with pytest.raises(RegistryError, match="used_by"):
        reg.register(define(key="users.probe.other", used_by=()))


def test_the_catalog_seals_on_first_read(reg):
    reg.register(define())
    assert [d.key for d in reg.defs()] == ["users.probe.limit"]
    with pytest.raises(RegistryError, match="sealed"):
        reg.register(define(key="users.probe.late"))


def test_register_group_derives_keys_from_the_dataclass(reg):
    @dataclass(frozen=True)
    class Probe:
        limit: int = field(
            default=10,
            metadata=meta(
                Int(min=1, max=100),
                label="A limit",
                description="d",
                changed_by_event="e",
                used_by=("Tests",),
            ),
        )

    reg.register_group(Probe, prefix="users.probe", module="users", group="Probes")
    assert reg.keys_of(Probe) == {"limit": "users.probe.limit"}
    assert reg.get("users.probe.limit").default == 10


def test_register_group_refuses_a_field_without_meta_or_default(reg):
    @dataclass(frozen=True)
    class Bare:
        limit: int = 10

    with pytest.raises(RegistryError, match="no meta"):
        reg.register_group(Bare, prefix="users.probe", module="users", group="Probes")


def test_the_tenant_resolver_registers_once(reg):
    reg.set_tenant_resolver(lambda user: None)
    with pytest.raises(RegistryError, match="already registered"):
        reg.set_tenant_resolver(lambda user: None)
