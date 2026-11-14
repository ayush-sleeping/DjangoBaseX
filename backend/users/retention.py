"""
The users module's retention policies (AUTH_BLUEPRINT § 19.2; BUILD_ORDER 1.7, 7.5): the three auth
tables that grow forever. Registered from UsersConfig.ready(). Defaults are the values
auth_cleanup always had (90 / 30 / 7 days); the floors are new.

Never users, invitations, rbac or the audit trail. Never capped: login attempts are a security log
(a cap would let an attacker's own noise roll their tracks off), sessions are live state.
"""

from django.db.models import Q

from core.registry import RetentionPolicy


def dead_sessions(cutoff, now) -> Q:
    """
    A session that stopped working before `cutoff`, and whose refresh token can no longer verify.

    Expired before the cutoff: gone. Revoked before the cutoff: gone only once its token has also
    expired. A revoked token that has not expired is exactly the one a thief replays, and its row
    is what lets refresh recognise the replay and revoke the whole family (§ 6.3). Deleting it
    early would turn "reuse detected, family revoked" into a plain "unknown token".
    Live sessions (not revoked, not expired) match neither branch, whatever their age.
    """
    return Q(expires_at__lt=cutoff) | Q(revoked_at__lt=cutoff, expires_at__lt=now)


def used_or_expired_tokens(cutoff, now) -> Q:
    return Q(used_at__lt=cutoff) | Q(expires_at__lt=cutoff)


POLICIES = (
    RetentionPolicy(
        key="users.login_attempts",
        model="users.LoginAttempt",
        timestamp_field="created_at",
        description="Throttling and forensics; grows with attack traffic, not users.",
        data_class="security_log",
        max_age_days=90,
        # Lockout reads the last 24 hours (users.services.lockout); a week keeps forensics useful.
        min_age_days=7,
    ),
    RetentionPolicy(
        key="users.sessions",
        model="users.UserSession",
        timestamp_field="expires_at",
        description="Sessions that stopped working, once their refresh token is dead too.",
        data_class="security_log",
        max_age_days=30,
        min_age_days=7,
        age_q=dead_sessions,
    ),
    RetentionPolicy(
        key="users.password_reset_tokens",
        model="users.PasswordResetToken",
        timestamp_field="expires_at",
        description="Password-reset tokens that were used or expired.",
        data_class="operational_log",
        max_age_days=7,
        min_age_days=1,
        age_q=used_or_expired_tokens,
    ),
)
