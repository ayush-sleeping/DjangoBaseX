"""
Migrations stay linear and complete (BUILD_ORDER 2.2, DATABASE_MIGRATIONS.md rule 7).

A branched chain is silent until `migrate` runs, which on a deploy is the worst moment to find it.
"""

from collections import defaultdict

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.db.migrations.loader import MigrationLoader


def test_one_migration_head_per_app():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    heads = defaultdict(list)
    for app_label, name in loader.graph.leaf_nodes():
        heads[app_label].append(name)

    branched = {app: sorted(names) for app, names in heads.items() if len(names) > 1}
    assert not branched, (
        "branched migration history (more than one head): "
        + "; ".join(f"{app}: {', '.join(names)}" for app, names in sorted(branched.items()))
        + ". Merge with `makemigrations --merge`, or rebase onto the other branch's migration."
    )


@pytest.mark.django_db  # makemigrations checks the applied history for consistency
def test_no_model_change_is_missing_a_migration():
    try:
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)
    except SystemExit as exc:
        pytest.fail(
            f"makemigrations --check exited {exc.code}: a model changed without a migration. "
            "Run `uv run python manage.py makemigrations` and commit the result."
        )


@pytest.mark.django_db
def test_every_model_has_a_table():
    tables = set(connection.introspection.table_names())
    missing = [
        f"{model._meta.label} -> {model._meta.db_table}"
        for model in apps.get_models(include_auto_created=True)
        if model._meta.managed and not model._meta.proxy and model._meta.db_table not in tables
    ]
    assert not missing, f"models with no table after migrating: {missing}"
