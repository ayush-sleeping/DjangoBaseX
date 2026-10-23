"""
Print one fresh secret in the format the code that reads it expects (OPERATIONS.md § 2 step 5).

    uv run python manage.py generate_secret --kind django    # SECRET_KEY
    uv run python manage.py generate_secret --kind jwt       # JWT_SIGNING_KEY
    uv run python manage.py generate_secret --kind fernet    # MFA_ENCRYPTION_KEY
    uv run python manage.py generate_secret --kind hex       # database and cache passwords
    uv run python manage.py generate_secret --kind password  # the development administrator

The rules are core.secret_policy's. Before Django is installed, scripts/setup.sh uses the same
module through scripts/lib/envfile.py, which imports it.
"""

from django.core.management.base import BaseCommand

from core.secret_policy import GENERATORS, generate


class Command(BaseCommand):
    help = "Print one fresh secret: django, jwt, fernet, hex or password."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=sorted(GENERATORS), required=True)

    def handle(self, *args, kind, **options):
        self.stdout.write(generate(kind))
