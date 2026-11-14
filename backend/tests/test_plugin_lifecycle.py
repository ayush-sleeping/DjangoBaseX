"""
The soft-disable contract, the uniform contribution shape and the service contracts
(BUILD_ORDER 9.1; EXTENSIBILITY § 3, § 15, § 18).

A fixture plugin "probe" registers from a module named `djx_probe.wiring`, so every catalog
attributes its contributions to the plugin exactly as it does a real one. The example plugin's own
end-to-end version (its data untouched, a real URL) lives in its test file.
"""

import types

import pytest
from celery import Celery
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import path

from config.celery import app
from core.jobs.celery import register_task
from core.locks import MemoryStore, set_store
from core.plugin_gate import include_args
from core.plugin_state import set_enabled
from core.registry import (
    BootstrapContributor,
    HelpPage,
    JobSpec,
    NoProvider,
    Registry,
    RegistryError,
    SearchSource,
    ServiceUnavailable,
    owner_label,
    plugin_state,
    registry,
)
from tests.core.jobs import fakes
from tests.core.jobs.dbs import DATABASES, runs

WIRING = """
from core.registry import (
    BootstrapContributor, HelpPage, JobSpec, NavItem, NavSection, SearchSource,
)


def register(reg):
    item = NavItem("home", "Probe", "/probe")
    reg.navigation.register(NavSection(key="probe", label="Probe", module="probe", items=(item,)))
    reg.search_sources.register(
        SearchSource(key="probe.things", label="Things", search=lambda q: [])
    )
    reg.help_pages.register(HelpPage(key="probe.intro", title="Probe", body="How probe works"))
    reg.bootstrap.register(BootstrapContributor("probe", lambda request: {"on": True}))
    reg.services.provide("probe.total.v1", lambda **kw: 42)
    reg.jobs.register(JobSpec(
        name="probe.count", func="tests.core.jobs.fakes.count_three", owner_module="probe",
        description="A fixture job. If it stops, only these tests notice.",
    ))
"""


def probe_registry() -> Registry:
    """A Registry holding what the fixture plugin contributes, attributed to djx_probe.wiring."""
    module = types.ModuleType("djx_probe.wiring")
    exec(compile(WIRING, "djx_probe/wiring.py", "exec"), module.__dict__)  # noqa: S102
    reg = Registry()
    module.register(reg)
    return reg


@pytest.fixture
def disabled(monkeypatch):
    """Switch fixture plugins off the way production does: through plugin_state's provider."""
    labels: set[str] = set()
    monkeypatch.setattr(plugin_state, "_provider", lambda: frozenset(labels))
    return labels


def surfaces(reg: Registry) -> dict:
    return {
        "nav": [s.key for s in reg.navigation.visible_to(frozenset(), True)],
        "search": [s.key for s in reg.search_sources.enabled()],
        "help": [p.key for p in reg.help_pages.enabled()],
        "bootstrap": [c.key for c in reg.bootstrap.enabled()],
        "service": reg.services.has_service("probe.total.v1"),
        "job": reg.jobs.runnable("probe.count"),
    }


def test_the_fixture_attributes_every_contribution_to_the_plugin():
    reg = probe_registry()
    assert reg.navigation.owner("probe") == "djx_probe.wiring"
    assert reg.services.owner("probe.total.v1") == "djx_probe.wiring"
    assert owner_label("djx_probe.wiring") == "probe"
    assert owner_label("users.apps") is None and owner_label("core.registry") is None


def test_disabling_a_plugin_hides_every_registry_surface_and_enabling_restores_it(disabled):
    reg = probe_registry()
    on = surfaces(reg)
    assert on == {
        "nav": ["probe"],
        "search": ["probe.things"],
        "help": ["probe.intro"],
        "bootstrap": ["probe"],
        "service": True,
        "job": True,
    }

    disabled.add("probe")
    assert surfaces(reg) == {
        "nav": [],
        "search": [],
        "help": [],
        "bootstrap": [],
        "service": False,
        "job": False,
    }
    # Hidden, not removed: the catalogue still holds them, so enabling restores them exactly.
    assert [s.key for s in reg.search_sources.all()] == ["probe.things"]

    disabled.clear()
    assert surfaces(reg) == on


def test_a_platform_owner_is_never_switched_off(disabled):
    disabled.add("users")  # not a plugin label: owner_label never maps users.* to one
    reg = Registry()
    reg.help_pages.register(HelpPage(key="core.intro", title="Core", body="b"))
    assert [p.key for p in reg.help_pages.enabled()] == ["core.intro"]


def test_a_plugin_route_answers_403_plugin_disabled_and_enabled_answers_through(disabled):
    module = types.ModuleType("djx_probe.urls")
    module.app_name = "probe"
    module.urlpatterns = [path("ping/", lambda request: HttpResponse("pong"), name="ping")]
    patterns, app_name = include_args(module, "djx_probe.wiring")
    assert app_name == "probe"
    request = RequestFactory().get("/api/probe/ping/")
    view = patterns[0].callback

    assert view(request).content == b"pong"
    disabled.add("probe")
    response = view(request)
    assert response.status_code == 403
    assert b'"plugin_disabled"' in response.content
    # A platform-owned mount is never gated, whatever the set says.
    platform = include_args(module, "core.urls")[0][0].callback
    assert platform(request).content == b"pong"


def test_a_second_provider_of_a_contract_is_refused():
    reg = probe_registry()
    with pytest.raises(RegistryError, match="already registered"):
        reg.services.provide("probe.total.v1", lambda **kw: 1)


def test_the_contract_name_is_versioned():
    reg = Registry()
    with pytest.raises(RegistryError, match="key is not"):
        reg.services.provide("probe.total", lambda **kw: 1)


def test_a_service_call_answers_or_fails_deliberately(disabled):
    reg = probe_registry()
    assert reg.services.call_service("probe.total.v1") == 42
    with pytest.raises(NoProvider):
        reg.services.call_service("probe.absent.v1")
    disabled.add("probe")
    with pytest.raises(ServiceUnavailable):
        reg.services.call_service("probe.total.v1")


def test_registration_after_sealing_is_refused():
    reg = probe_registry()
    reg.help_pages.all()
    with pytest.raises(RegistryError, match="sealed"):
        reg.help_pages.register(HelpPage(key="x.late", title="t", body="b"))


def test_a_duplicate_key_and_a_wrong_spec_type_are_refused():
    reg = Registry()
    reg.search_sources.register(SearchSource(key="a.b", label="l", search=lambda q: []))
    with pytest.raises(RegistryError, match="already registered"):
        reg.search_sources.register(SearchSource(key="a.b", label="l", search=lambda q: []))
    with pytest.raises(RegistryError, match="expected a SearchSource"):
        reg.search_sources.register(HelpPage(key="a.c", title="t", body="b"))


def test_a_when_predicate_gates_a_contribution():
    reg = Registry()
    on = {"v": False}
    reg.bootstrap.register(BootstrapContributor("flaggy", lambda r: 1), when=lambda: on["v"])
    assert reg.bootstrap.enabled() == ()
    on["v"] = True
    assert [c.key for c in reg.bootstrap.enabled()] == ["flaggy"]


# --- The switch itself: a typed runtime setting, no table ---------------------------------------


@pytest.mark.django_db
def test_the_switch_is_a_runtime_setting_and_never_touches_the_platform():
    assert plugin_state.is_enabled("probe")
    set_enabled("probe", False, reason="the fixture plugin is misbehaving here")
    assert not plugin_state.is_enabled("probe") and plugin_state.is_enabled("other")
    set_enabled("probe", True)
    assert plugin_state.is_enabled("probe")
    with pytest.raises(ValueError, match="platform app"):
        set_enabled("users", False)


# --- A disabled plugin's job does not run -------------------------------------------------------


@pytest.mark.django_db(databases=DATABASES)
def test_a_disabled_plugins_job_skips_at_run_time_and_is_recorded(disabled, monkeypatch):
    app.finalize(auto=True)
    fakes.CALLS.clear()
    set_store(MemoryStore())
    try:
        spec = JobSpec(
            name="probe.count",
            func="tests.core.jobs.fakes.count_three",
            owner_module="probe",
            description="A fixture job. If it stops, only these tests notice.",
        )
        monkeypatch.setitem(registry.jobs._owner_of, "probe.count", "djx_probe.wiring")
        task = register_task(Celery("test", set_as_current=False), spec)

        assert task.apply(task_id="live").get() == 3
        disabled.add("probe")
        assert task.apply(task_id="off").get() == 0
        assert len(fakes.CALLS) == 1  # only the enabled run executed
        assert runs().get(task_id="off").error_message == "plugin_disabled"
        disabled.clear()
        assert task.apply(task_id="back").get() == 3
    finally:
        set_store(None)
