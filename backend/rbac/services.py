"""
Every write to roles, grants and assignments (AUTH_BLUEPRINT § 7.4, Ch. 8). Nothing else writes
these tables — not views, not the admin (Ch. 20) — so the cache bump and the audit always happen.
The elevated-role and last-superuser guards (§ 8.2–8.3) and the roles API arrive with 1.4.
"""

from django.db import transaction
from django.utils import timezone

from core.audit import log_activity

from .models import Permission, Role, RolePermission, UserRole
from .selectors import bump_version


def create_role(*, name: str, slug: str, actor=None, **fields) -> Role:
    role = Role.objects.create(name=name, slug=slug, created_by=actor, updated_by=actor, **fields)
    log_activity("rbac.role.created", actor=actor, target=role)
    return role


@transaction.atomic
def set_grants(role: Role, codes: set[str], *, actor=None) -> None:
    """Make the role grant exactly `codes`. Unknown codes are refused, never silently dropped."""
    permissions = {
        p.code: p for p in Permission.objects.filter(code__in=codes, is_deprecated=False)
    }
    unknown = set(codes) - set(permissions)
    if unknown:
        raise ValueError(f"unknown or deprecated permission codes: {sorted(unknown)}")
    current = set(role.role_permissions.values_list("permission__code", flat=True))
    RolePermission.objects.filter(role=role, permission__code__in=current - set(codes)).delete()
    now = timezone.now()
    RolePermission.objects.bulk_create(
        RolePermission(role=role, permission=permissions[c], granted_at=now, granted_by=actor)
        for c in set(codes) - current
    )
    bump_version()
    log_activity(
        "rbac.role.grants_changed",
        actor=actor,
        target=role,
        added=sorted(set(codes) - current),
        removed=sorted(current - set(codes)),
    )


@transaction.atomic
def assign_role(user, role: Role, *, actor=None) -> UserRole:
    assignment, created = UserRole.objects.get_or_create(
        user=user, role=role, defaults={"assigned_at": timezone.now(), "assigned_by": actor}
    )
    if created:
        _sync_mfa_enforced(user)
        bump_version()
        log_activity("rbac.role.assigned", actor=actor, target=user, role=role.slug)
    return assignment


@transaction.atomic
def revoke_role(user, role: Role, *, actor=None) -> None:
    deleted, _ = UserRole.objects.filter(user=user, role=role).delete()
    if deleted:
        _sync_mfa_enforced(user)
        bump_version()
        log_activity("rbac.role.revoked", actor=actor, target=user, role=role.slug)


def _sync_mfa_enforced(user) -> None:
    """A role with mfa_required forces user.mfa_enforced; losing the last such role releases it."""
    enforced = UserRole.objects.filter(user=user, role__mfa_required=True).exists()
    if user.mfa_enforced != enforced:
        type(user).objects.filter(pk=user.pk).update(mfa_enforced=enforced)
        user.mfa_enforced = enforced
