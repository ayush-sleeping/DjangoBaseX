"""
Every model with an owner or tenant field is registered for scoping (DATA_LIFECYCLE.md § 12.1,
BUILD_ORDER 9.3). A model that carries "whose is this row" and says nothing about who may see it is
how a cross-tenant read ships.

OWNER FIELD, precisely: a forward relation to the user model named one of OWNER_FIELD_NAMES
(the person a row belongs to or was filed by), OR any field whose name starts with `tenant`.
Audit stamps (`updated_by`, `resolved_by`, `granted_by`, `revoked_by`, `invited_by`, `actor`) record
who touched a row; they are not visibility and do not make a model owned.

Also: a write action goes through `writable_by` (self.scope), never a bare `visible_to` in a
BaseViewSet's get_queryset, so an invisible row is a 404 on PATCH/PUT/DELETE.
"""

import ast

import pytest
from django.apps import apps
from django.conf import settings

from core.querysets import VisibleToQuerySet
from core.registry import RegistryError, ScopeSpec, ScopingRegistry, registry
from tests.architecture.sources import iter_python_sources, rel

OWNER_FIELD_NAMES = frozenset({"owner", "user", "created_by", "uploaded_by", "recipient"})


def owner_or_tenant_fields(model) -> list[str]:
    found = []
    for field in model._meta.get_fields():
        if field.auto_created or not getattr(field, "concrete", False):
            continue
        is_user_fk = (
            field.is_relation
            and field.related_model is not None
            and field.related_model._meta.label_lower == settings.AUTH_USER_MODEL.lower()
        )
        if field.name.startswith("tenant") or (is_user_fk and field.name in OWNER_FIELD_NAMES):
            found.append(field.name)
    return found


def test_every_model_with_an_owner_or_tenant_field_is_registered_for_scoping():
    # Our apps only: a framework app's tables (django.contrib.admin's LogEntry) are not ours.
    models = [m for m in apps.get_models() if not m._meta.app_config.name.startswith("django.")]
    assert len(models) > 20, "the model scan is empty: it is looking in the wrong place"
    owned = {m._meta.label: owner_or_tenant_fields(m) for m in models if owner_or_tenant_fields(m)}
    assert owned, "no model has an owner or tenant field: the definition flags nothing"
    registered = {spec.model for spec in registry.scoping.specs()}
    missing = sorted(label for label in owned if label not in registered)
    assert not missing, (
        f"models with an owner/tenant field {{label: fields}} but no registry.scoping entry: "
        f"{ {label: owned[label] for label in missing} }. Register ScopeSpec(...) from ready(): "
        "scoped (visible_to) or not_scoped_because=<reason>."
    )


def test_every_registration_names_a_real_model_and_keeps_its_promise():
    specs = registry.scoping.specs()
    assert specs, "nothing registered in registry.scoping"
    for spec in specs:
        model = apps.get_model(spec.model)
        for field in (spec.owner_field, spec.tenant_field):
            if field:
                model._meta.get_field(field)
        if spec.scoped:
            queryset = model._default_manager.all()
            assert isinstance(queryset, VisibleToQuerySet), f"{spec.model}: queryset base"
            assert type(queryset).visible_to is not VisibleToQuerySet.visible_to, (
                f"{spec.model} is registered as scoped but does not implement visible_to()"
            )


def test_only_declared_fields_are_owner_fields_on_scoped_models():
    for spec in registry.scoping.specs():
        if spec.scoped and spec.owner_field:
            assert spec.owner_field in owner_or_tenant_fields(apps.get_model(spec.model))


def test_positive_control_an_unregistered_owned_model_is_caught():
    class Fake:
        class _meta:  # noqa: N801
            label = "fake.Owned"

            @staticmethod
            def get_fields():
                class F:
                    auto_created = False
                    concrete = True
                    is_relation = False
                    name = "tenant_id"

                return [F()]

    assert owner_or_tenant_fields(Fake) == ["tenant_id"]
    assert "fake.Owned" not in {s.model for s in registry.scoping.specs()}


def test_positive_control_the_definition_sees_real_owner_fields_and_ignores_audit_stamps():
    assert owner_or_tenant_fields(apps.get_model("core", "PrivateFile")) == ["uploaded_by"]
    assert owner_or_tenant_fields(apps.get_model("core", "Notification")) == ["recipient"]
    assert owner_or_tenant_fields(apps.get_model("core", "Setting")) == []  # updated_by only


def test_the_registry_refuses_silence_and_duplicates():
    reg = ScopingRegistry()
    with pytest.raises(RegistryError, match="real sentence"):
        reg.register(ScopeSpec(model="core.Setting", not_scoped_because="no"))
    reg.register(ScopeSpec(model="core.Setting", not_scoped_because="Platform-wide configuration."))
    with pytest.raises(RegistryError, match="already registered"):
        reg.register(ScopeSpec(model="core.Setting"))
    with pytest.raises(RegistryError, match="model must be"):
        reg.register(ScopeSpec(model="setting"))


def _viewset_scoping_violations(source: str, filename: str) -> list[str]:
    out = []
    for cls in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(cls, ast.ClassDef):
            continue
        bases = {b.id for b in cls.bases if isinstance(b, ast.Name)}
        if "BaseViewSet" not in bases:
            continue
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef) and fn.name == "get_queryset":
                for node in ast.walk(fn):
                    if isinstance(node, ast.Attribute) and node.attr == "visible_to":
                        out.append(f"{filename}:{node.lineno} {cls.name}.get_queryset")
    return out


def test_a_viewset_scopes_through_self_scope_so_writes_use_writable_by():
    scanned, violations = 0, []
    for path in iter_python_sources():
        if path.name != "views.py" and "api" not in path.parts:
            continue
        scanned += 1
        violations += _viewset_scoping_violations(path.read_text(), rel(path))
    assert scanned, "no view module scanned"
    assert not violations, (
        f"get_queryset calls visible_to() directly (reads only): use self.scope(...): {violations}"
    )


def test_positive_control_the_viewset_scan_sees_a_bare_visible_to():
    source = (
        "class V(BaseViewSet):\n"
        "    def get_queryset(self):\n"
        "        return M.objects.visible_to(self.request.user)\n"
    )
    assert _viewset_scoping_violations(source, "x.py")
