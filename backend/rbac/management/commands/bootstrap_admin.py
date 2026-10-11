"""
Account one (AUTH_BLUEPRINT § 19.1, A25): the first user, created from the shell.

Refuses once any user exists, or it would be a permanent unauthenticated-escalation tool in every
product copied from this core. The password is never an argument (shell history, process list, CI
log): it is prompted twice, or read from BOOTSTRAP_ADMIN_PASSWORD for non-interactive setup.

Lives in rbac because it assigns a role. Like the rest of rbac it reaches the user model through
get_user_model() and never imports users' models (Ch. 2).
"""

import getpass
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from core.audit import log_activity
from rbac import services
from rbac.models import Permission, Role
from rbac.seeding import sync_catalog

PASSWORD_ENV = "BOOTSTRAP_ADMIN_PASSWORD"


class Command(BaseCommand):
    help = (
        "Create the first user: an active superuser holding the administrator role. Refuses if "
        f"any user exists. The password is prompted, or read from {PASSWORD_ENV}."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="The first user's email address.")
        parser.add_argument("--full-name", default="", help="Optional display name.")
        parser.add_argument(
            "--no-input",
            action="store_true",
            help=f"Never prompt: {PASSWORD_ENV} must be set.",
        )

    def handle(self, *args, email, full_name, no_input, **options):
        user_model = get_user_model()
        # Checked before asking for a password, so nobody types one only to be refused. Checked
        # again inside the transaction, which is the check that counts.
        self._refuse_if_any_user(user_model)
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError(f"{email!r} is not a valid email address.") from None

        password = self._read_password(no_input)
        candidate = user_model(email=email, full_name=full_name)
        try:
            validate_password(password, user=candidate)
        except ValidationError as exc:
            # Validator messages describe the rule, never the password itself.
            raise CommandError("Password refused: " + " ".join(exc.messages)) from None

        with transaction.atomic():
            self._refuse_if_any_user(user_model)
            if not Permission.objects.exists():
                sync_catalog()
            # Both idempotent: they make sure administrator exists and holds every permission.
            services.ensure_system_roles()
            services.recompute_administrator()

            user = user_model.objects.create_superuser(email, password, full_name=full_name)
            administrator = Role.objects.get(slug="administrator")
            services.assign_role(actor=None, user=user, role=administrator)
            log_activity("users.user.bootstrapped", target=user)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {user.email}: an active superuser holding the administrator role."
            )
        )

    def _refuse_if_any_user(self, user_model) -> None:
        if user_model.objects.exists():
            raise CommandError(
                "Refusing: users already exist. bootstrap_admin only creates the FIRST account; "
                "every later one is invited by someone who can already sign in."
            )

    def _read_password(self, no_input: bool) -> str:
        from_env = os.environ.get(PASSWORD_ENV)
        if from_env:
            return from_env
        if no_input:
            raise CommandError(f"--no-input was given, so {PASSWORD_ENV} must be set.")
        first = getpass.getpass("Password: ")
        if not first:
            raise CommandError("Refusing an empty password.")
        if getpass.getpass("Password (again): ") != first:
            raise CommandError("The two passwords do not match. Nothing was created.")
        return first
