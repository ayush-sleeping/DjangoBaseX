"""
manage.py export_frontend_contracts [--check]

Writes frontend/src/generated/ from the backend (FRONTEND_PLATFORM § 24): the OpenAPI document,
permission codes, status metadata, list ordering allow-lists, public routes and the navigation
manifest. Then run `npm run contracts` in frontend/ to turn openapi.json into api.d.ts.

--check writes nothing and exits 1 naming every stale file (what CI's drift test does in-process).
Runs under any settings; config.settings_test is the deterministic choice without a .env:
    DJANGO_SETTINGS_MODULE=config.settings_test uv run python manage.py export_frontend_contracts
"""

from django.core.management.base import BaseCommand, CommandError

from core import contracts


class Command(BaseCommand):
    help = "Write the frontend's generated contracts (src/generated/) from the backend."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check", action="store_true", help="Write nothing; fail if any file is stale."
        )

    def handle(self, *args, check=False, **options):
        rendered = contracts.render_all()
        if check:
            stale = contracts.stale_files(rendered=rendered)
            if stale:
                raise CommandError(
                    f"stale generated contracts: {', '.join(stale)}. Run `{contracts.COMMAND}` "
                    "then `npm run contracts` in frontend/, and commit src/generated/."
                )
            self.stdout.write(f"{len(rendered)} generated contracts are current.")
            return
        changed = contracts.write_all(rendered=rendered)
        for name in changed:
            self.stdout.write(f"wrote src/generated/{name}")
        self.stdout.write(
            f"{len(changed)} of {len(rendered)} files changed."
            + (" Now run `npm run contracts` in frontend/." if "openapi.json" in changed else "")
        )
