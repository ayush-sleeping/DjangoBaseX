"""
Demo users (BUILD_ORDER 9.6): created through `users.services`, so the audit row and token exist.

Natural key: the email, on the reserved `.test` domain. Users created in this run share one random
throwaway password, printed once and stored nowhere else; users that already exist keep theirs.
"""

import secrets

from django.contrib.auth import get_user_model

from core.seeding import DEMO_DOMAIN, SeedResult
from users.services import users as user_services

DEMO_USERS = (
    (f"admin@{DEMO_DOMAIN}", "Demo Admin"),
    (f"support@{DEMO_DOMAIN}", "Demo Support"),
    (f"viewer@{DEMO_DOMAIN}", "Demo Viewer"),
)


def seed(stdout) -> SeedResult:
    result = SeedResult()
    user_model = get_user_model()
    password = secrets.token_urlsafe(16)
    for email, full_name in DEMO_USERS:
        if user_model.objects.filter(email=email).exists():
            result.skipped += 1
            continue
        user = user_services.create_user(actor=None, email=email, full_name=full_name)
        user.set_password(password)
        user.save(update_fields=["password"])
        result.created += 1
    if result.created:
        stdout.write(f"Demo users @{DEMO_DOMAIN} ({result.created} new) sign in with: {password}")
    return result
