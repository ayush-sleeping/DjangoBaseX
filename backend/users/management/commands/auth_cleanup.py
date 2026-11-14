"""
Retention for the three auth tables that grow forever (AUTH_BLUEPRINT § 19.2; BUILD_ORDER 1.7).

Since BUILD_ORDER 7.5 this is one caller of the retention engine (core.retention.engine): the
policies (tables, filters, windows) are registered in users/retention.py and the windows are the
settings `retention.users_*.days`. The job users.auth_cleanup (users/jobs.py) runs the same policies
daily; `manage.py retention` runs them with every other module's. It deletes ONLY:

  users_login_attempt         created_at older than its window (default 90 days)
  users_user_session          dead sessions (users.retention.dead_sessions), 30 days after they
                              stopped working; a live session is never touched
  users_password_reset_token  used or expired, 7 days after that

Never users, invitations, rbac, or the audit trail: core_activity_log is append-only (§ 3.12).
"""

from django.apps import apps
from django.core.management.base import BaseCommand

from core.registry import registry
from core.retention import engine

OWNER = "users"


def table_of(key: str) -> str:
    return apps.get_model(registry.retention.get(key).model)._meta.db_table


class Command(BaseCommand):
    help = (
        "Delete expired auth records: old login attempts, dead sessions, used or expired reset "
        "tokens. --dry-run reports the counts and deletes nothing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Count what would go; delete nothing."
        )

    def handle(self, *args, dry_run, **options):
        for result in engine.run(owner=OWNER, dry_run=dry_run):
            table = table_of(result.key)
            if result.state == engine.DRY_RUN:
                self.stdout.write(f"would delete {result.eligible} from {table}")
            elif result.state == engine.RAN:
                self.stdout.write(f"deleted {result.deleted} from {table}")
            else:
                self.stdout.write(f"skipped {table}: {result.state}")
