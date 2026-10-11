"""Every factory builds once with its defaults. A factory that raises on every call is not rare."""

import inspect

import factory
import pytest

from tests import factories

ALL_FACTORIES = [
    obj
    for _, obj in inspect.getmembers(factories, inspect.isclass)
    if issubclass(obj, factory.django.DjangoModelFactory) and obj.__module__ == factories.__name__
]


def test_factories_are_discovered():
    assert ALL_FACTORIES, "no factories found in tests/factories.py"


@pytest.mark.django_db
@pytest.mark.parametrize("model_factory", ALL_FACTORIES, ids=lambda f: f.__name__)
def test_factory_builds_with_defaults(model_factory):
    instance = model_factory()
    assert instance.pk is not None
