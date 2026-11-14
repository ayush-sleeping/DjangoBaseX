"""users' bulk actions (DOMAIN_PRIMITIVES.md § 5): each goes through the single-row service."""

from core.api.bulk import Skip
from core.registry import BulkAction

from .services import users as users_service


def _deactivate(*, actor, obj, reason: str = "") -> None:
    if not obj.is_active:
        raise Skip("already_inactive", "Already deactivated.")
    try:
        users_service.deactivate(actor=actor, user=obj, reason=reason)
    except users_service.UsersError as exc:
        raise Skip(exc.code, str(exc) or exc.code) from exc


ACTIONS = (
    BulkAction(
        resource="users.user",
        name="deactivate",
        label="Deactivate",
        permission="users.users.deactivate",
        handler=_deactivate,
    ),
)
