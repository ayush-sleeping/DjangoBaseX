"""
The databases a job-run test touches. The recorder writes through settings.JOB_RUN_DB_ALIAS:
"monitor" (its own connection) on PostgreSQL, "default" on SQLite :memory: (config/settings_test).
"""

from django.conf import settings

ALIAS = settings.JOB_RUN_DB_ALIAS
DATABASES = ["default"] if ALIAS == "default" else ["default", ALIAS]
SEPARATE_CONNECTION = ALIAS != "default"


def runs():
    from core.models import JobRun

    return JobRun.objects.using(ALIAS)
