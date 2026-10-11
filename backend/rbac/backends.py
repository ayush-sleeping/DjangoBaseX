"""RBACBackend — the ONE thing that answers has_perm (AUTH_BLUEPRINT § 7.4, A9, A12)."""

from django.contrib.auth.backends import BaseBackend

from core.audit import log_activity

from .selectors import permission_codes_for


class RBACBackend(BaseBackend):
    """
    Grants nothing at authentication; answers has_perm from roles. The superuser bypass is decided
    HERE, and audited every time, which only works because users.User.has_perm skips Django's own
    superuser short-circuit.
    """

    def has_perm(self, user_obj, perm, obj=None) -> bool:
        if not user_obj or not user_obj.is_authenticated or not user_obj.is_active:
            return False
        if user_obj.is_superuser:
            log_activity("authz.superuser_bypass", actor=user_obj, permission=perm)
            return True
        return perm in permission_codes_for(user_obj)

    def get_all_permissions(self, user_obj, obj=None) -> set[str]:
        return set(permission_codes_for(user_obj))

    def has_module_perms(self, user_obj, app_label) -> bool:
        if not user_obj or not user_obj.is_active:
            return False
        if user_obj.is_superuser:
            return True
        return any(code.startswith(f"{app_label}.") for code in permission_codes_for(user_obj))
