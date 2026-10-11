"""
The ONLY writers to rbac_* tables (AUTH_BLUEPRINT § 8.4). Nothing else writes them — not views, not
the admin (Ch. 20) — so the guards, the cache bump and the audit always happen. Every function is
atomic, bumps the permission cache version, and audits.
"""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core.audit import log_activity

from .models import Permission, Role, RolePermission, UserRole
from .selectors import bump_version

ADMINISTRATOR = "administrator"
STAFF = "staff"


class RbacError(Exception):
    code = "invalid"


class SystemRoleProtected(RbacError):
    """System roles cannot be renamed, deleted or have their grants edited (§ 8.1)."""

    code = "system_role"


class RoleInUse(RbacError):
    code = "role_in_use"

    def __init__(self, user_count: int):
        super().__init__(f"role is held by {user_count} user(s)")
        self.user_count = user_count


class ElevatedRequiresSuperuser(RbacError):
    """
    Only a superuser may grant, revoke, mark, edit, regrant or delete an elevated role (§ 8.2).
    Guarding assignment alone is not enough: whoever may widen an elevated role's grants widens
    every holder at once, which is the same escalation by a side door.
    """

    code = "elevated_requires_superuser"


class LastAdministrator(RbacError):
    """Removing this would leave no one able to fix access (§ 8.3)."""

    code = "last_administrator"


class UnknownPermission(RbacError):
    code = "unknown_permission"

    def __init__(self, codes: list[str]):
        super().__init__(f"unknown or deprecated permission codes: {codes}")
        self.codes = codes


@dataclass(frozen=True)
class GrantDiff:
    added: list[str]
    removed: list[str]


def _require_superuser_for_elevated(actor) -> None:
    # actor=None is the system itself (seeding, migrations, management commands).
    if actor is not None and not actor.is_superuser:
        raise ElevatedRequiresSuperuser


# --- Roles --------------------------------------------------------------------------------------


@transaction.atomic
def create_role(
    *, actor, name, slug, description="", permission_codes=(), is_elevated=False, **fields
) -> Role:
    if is_elevated:
        _require_superuser_for_elevated(actor)
    role = Role.objects.create(
        name=name,
        slug=slug,
        description=description,
        is_elevated=is_elevated,
        created_by=actor,
        updated_by=actor,
        **fields,
    )
    if permission_codes:
        _replace_grants(role, set(permission_codes), actor)
    bump_version()
    log_activity("rbac.role.created", actor=actor, target=role)
    return role


@transaction.atomic
def update_role(*, actor, role: Role, **fields) -> Role:
    if role.is_system and "name" in fields and fields["name"] != role.name:
        raise SystemRoleProtected
    if role.is_elevated or fields.get("is_elevated"):
        _require_superuser_for_elevated(actor)
    mfa_changed = "mfa_required" in fields and fields["mfa_required"] != role.mfa_required
    for field, value in fields.items():
        setattr(role, field, value)
    role.updated_by = actor
    role.save()
    if mfa_changed:
        for assignment in UserRole.objects.filter(role=role).select_related("user"):
            recompute_mfa_enforcement(assignment.user)
    bump_version()
    log_activity("rbac.role.updated", actor=actor, target=role, fields=sorted(fields))
    return role


@transaction.atomic
def delete_role(*, actor, role: Role) -> None:
    if role.is_system:
        raise SystemRoleProtected
    if role.is_elevated:
        _require_superuser_for_elevated(actor)
    holders = UserRole.objects.filter(role=role).count()
    if holders:
        raise RoleInUse(holders)  # PROTECT would refuse too; this answers with a count
    log_activity("rbac.role.deleted", actor=actor, target=role, slug=role.slug)
    role.delete()
    bump_version()


@transaction.atomic
def set_grants(*, actor, role: Role, permission_codes) -> GrantDiff:
    """Full replacement. Returns the diff: "role widened" is the event worth auditing (§ 8.4)."""
    if role.is_system:
        raise SystemRoleProtected
    if role.is_elevated:
        _require_superuser_for_elevated(actor)
    diff = _replace_grants(role, set(permission_codes), actor)
    bump_version()
    log_activity(
        "rbac.role.grants_changed",
        actor=actor,
        target=role,
        added=diff.added,
        removed=diff.removed,
    )
    return diff


def _replace_grants(role: Role, codes: set[str], actor) -> GrantDiff:
    permissions = {
        p.code: p for p in Permission.objects.filter(code__in=codes, is_deprecated=False)
    }
    unknown = sorted(codes - set(permissions))
    if unknown:
        raise UnknownPermission(unknown)
    current = set(role.role_permissions.values_list("permission__code", flat=True))
    removed, added = sorted(current - codes), sorted(codes - current)
    RolePermission.objects.filter(role=role, permission__code__in=removed).delete()
    now = timezone.now()
    RolePermission.objects.bulk_create(
        RolePermission(role=role, permission=permissions[c], granted_at=now, granted_by=actor)
        for c in added
    )
    return GrantDiff(added=added, removed=removed)


# --- Assignments --------------------------------------------------------------------------------


@transaction.atomic
def assign_role(*, actor, user, role: Role) -> UserRole:
    if role.is_elevated:
        _require_superuser_for_elevated(actor)
    assignment, created = UserRole.objects.get_or_create(
        user=user, role=role, defaults={"assigned_at": timezone.now(), "assigned_by": actor}
    )
    if created:
        recompute_mfa_enforcement(user)
        bump_version()
        log_activity("rbac.role.assigned", actor=actor, target=user, role=role.slug)
    return assignment


@transaction.atomic
def revoke_role(*, actor, user, role: Role) -> None:
    if role.is_elevated:
        _require_superuser_for_elevated(actor)
    if role.slug == ADMINISTRATOR and _would_leave_no_administrator(user):
        raise LastAdministrator
    deleted, _ = UserRole.objects.filter(user=user, role=role).delete()
    if deleted:
        recompute_mfa_enforcement(user)
        bump_version()
        log_activity("rbac.role.revoked", actor=actor, target=user, role=role.slug)


def _would_leave_no_administrator(user) -> bool:
    """True when `user` is the last active administrator and no active superuser exists."""
    user_model = type(user)
    if user_model.objects.filter(is_superuser=True, is_active=True).exists():
        return False
    others = UserRole.objects.filter(role__slug=ADMINISTRATOR, user__is_active=True).exclude(
        user=user
    )
    return not others.exists()


def recompute_mfa_enforcement(user) -> None:
    """Derived, never assumed (§ 8.5): MFA is enforced while any held role requires it."""
    enforced = UserRole.objects.filter(user=user, role__mfa_required=True).exists()
    if user.mfa_enforced != enforced:
        type(user).objects.filter(pk=user.pk).update(mfa_enforced=enforced)
        user.mfa_enforced = enforced


# --- System roles (§ 8.1) -----------------------------------------------------------------------


def ensure_system_roles() -> None:
    """Idempotent: the two system roles exist with their fixed flags."""
    Role.objects.update_or_create(
        slug=ADMINISTRATOR,
        defaults={
            "name": "Administrator",
            "description": "Every permission in the catalog, recomputed after every migrate.",
            "is_system": True,
            "is_elevated": True,
        },
    )
    Role.objects.update_or_create(
        slug=STAFF,
        defaults={
            "name": "Staff",
            "description": "Grants nothing. The safe default for a new account.",
            "is_system": True,
            "is_elevated": False,
        },
    )


@transaction.atomic
def recompute_administrator() -> GrantDiff:
    """administrator holds every live permission, so a new module's codes reach it on migrate."""
    role = Role.objects.get(slug=ADMINISTRATOR)
    codes = set(Permission.objects.filter(is_deprecated=False).values_list("code", flat=True))
    diff = _replace_grants(role, codes, actor=None)
    if diff.added or diff.removed:
        bump_version()
        log_activity(
            "rbac.role.grants_changed", target=role, added=diff.added, removed=diff.removed
        )
    return diff
