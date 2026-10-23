"""
Change or reset one setting from the shell, through the same writer as the API (CONFIGURATION.md
§ 9.8). Audited like any other change, with no actor: a system write.

    uv run python manage.py set_setting security.reauth.window_minutes 30 --reason "audit finding"
    uv run python manage.py set_setting security.reauth.actions mfa_disable
    uv run python manage.py set_setting security.reauth.window_minutes --reset
    uv run python manage.py set_setting KEY VALUE --scope user --scope-id <public id>
    uv run python manage.py set_setting KEY VALUE --lock      # lower scopes are ignored

VALUE is text, coerced strictly by the setting's type: a bool takes only true, false, 1 or 0; a
list is comma-separated; a JSON setting takes JSON.
"""

from django.core.management.base import BaseCommand, CommandError

from core.settings_registry import SCOPES, SettingError
from core.settings_service import definition, reset, set_value


class Command(BaseCommand):
    help = "Change or reset one setting (validated and audited like an API write)."

    def add_arguments(self, parser):
        parser.add_argument("key")
        parser.add_argument("value", nargs="?")
        parser.add_argument(
            "--reset", dest="remove", action="store_true", help="remove the override instead"
        )
        parser.add_argument("--scope", choices=SCOPES, default="platform")
        parser.add_argument("--scope-id", default=None, help="the user's or tenant's public id")
        parser.add_argument("--reason", default="", help="recorded in the audit trail")
        lock = parser.add_mutually_exclusive_group()
        lock.add_argument("--lock", dest="locked", action="store_const", const=True)
        lock.add_argument("--unlock", dest="locked", action="store_const", const=False)

    def handle(self, *args, key, value, remove, scope, scope_id, reason, locked, **options):
        where = {"scope": scope, "scope_id": scope_id, "reason": reason}
        try:
            if remove:
                if value is not None:
                    raise CommandError("--reset takes no value")
                removed = reset(key, **where)
                self.stdout.write(f"{key}: {'reset' if removed else 'had no override'} at {scope}")
                return
            if value is None:
                raise CommandError("give a value, or --reset")
            defn = definition(key)
            parsed = defn.coerce_text(value)
            result = set_value(key, defn.to_json(parsed), locked=locked, **where)
        except SettingError as exc:
            raise CommandError(str(exc)) from None
        lock = " (locked)" if result.locked else ""
        self.stdout.write(f"{key} = {defn.to_json(result.value)!r} at {scope}{lock}")
