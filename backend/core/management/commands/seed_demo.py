"""
manage.py seed_demo: synthetic demo data from every app that ships a `demo.py` (BUILD_ORDER 9.6).

Runs each app's `seed(stdout)` in INSTALLED_APPS order. Idempotent: a second run creates nothing.
Refused when the environment is production-like, so demo accounts can never reach a real deployment.
"""

import importlib
import importlib.util

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from core.env import is_production_like
from core.seeding import SeedResult


def _seeders(only: set[str] | None):
    for config in apps.get_app_configs():
        if only is not None and config.label not in only:
            continue
        if importlib.util.find_spec(f"{config.name}.demo") is None:
            continue
        yield config, importlib.import_module(f"{config.name}.demo").seed


class Command(BaseCommand):
    help = "Create synthetic demo data through each app's services. Idempotent; not in production."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apps",
            default="",
            help="Comma-separated app labels (default: every app with a demo.py).",
        )

    def handle(self, *args, apps: str, **options):
        if is_production_like():
            raise CommandError(
                "Refusing: this environment is production-like. seed_demo creates accounts with "
                "demo addresses and only runs where APP_ENV is a development or test value."
            )
        only = {label.strip() for label in apps.split(",") if label.strip()} or None
        found = list(_seeders(only))
        if only is not None and (missing := only - {config.label for config, _ in found}):
            raise CommandError(f"No demo seeder for: {', '.join(sorted(missing))}.")
        total = SeedResult()
        for config, seed in found:
            result = seed(self.stdout)
            total.created += result.created
            total.skipped += result.skipped
            self.stdout.write(
                f"{config.label}: {result.created} created, {result.skipped} already there"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data: {total.created} created, {total.skipped} already there."
            )
        )
