"""
manage.py setup_token (OPERATIONS.md § 3): issue the one-time token the first-run wizard asks for.

Prints the token once, to this terminal only (never a log), and stores just its hash. Refuses once
an active superuser exists. Running it again replaces the earlier token.
"""

from django.core.management.base import BaseCommand, CommandError

from rbac import setup


class Command(BaseCommand):
    help = "Issue the one-time setup token for the first-run wizard."

    def handle(self, *args, **options):
        try:
            token = setup.issue_token()
        except setup.SetupSealed:
            raise CommandError("Setup is already complete: an active superuser exists.") from None
        self.stdout.write(f"Setup token (shown once): {token}")
