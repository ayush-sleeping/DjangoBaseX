"""The SDK facade's version contract (EXTENSIBILITY § 16, BUILD_ORDER 9.1)."""

import pytest

from core import sdk


def test_every_export_resolves_and_the_list_is_sorted():
    assert sdk.__all__ == sorted(sdk.__all__)
    for name in sdk.__all__:
        assert getattr(sdk, name) is not None, name


def test_an_unknown_export_is_an_attribute_error():
    with pytest.raises(AttributeError):
        sdk.not_a_thing  # noqa: B018


def test_the_current_version_has_a_changelog_entry():
    assert sdk.SDK_VERSION in sdk.SDK_CHANGELOG


def test_compatibility_is_same_major_and_at_least_the_minor():
    major, minor = sdk.SDK_VERSION
    assert sdk.is_compatible(f"{major}.{minor}") and sdk.is_compatible(f"{major}.0")
    assert not sdk.is_compatible(f"{major}.{minor + 1}")  # built against a newer core
    assert not sdk.is_compatible(f"{major + 1}.0")  # a different major


def test_require_version_fails_fast_and_a_malformed_target_is_refused():
    sdk.require_version("1.0")
    with pytest.raises(sdk.SDKVersionError, match="provides"):
        sdk.require_version("99.0")
    with pytest.raises(sdk.SDKVersionError, match="not a version"):
        sdk.require_version("one")


def test_plugin_enabled_reads_the_one_switch(monkeypatch):
    from core.registry import plugin_state

    monkeypatch.setattr(plugin_state, "_provider", lambda: frozenset({"gone"}))
    assert not sdk.plugin_enabled("gone") and sdk.plugin_enabled("here")
