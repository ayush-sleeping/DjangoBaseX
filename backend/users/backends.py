"""The credentials backend: checks passwords and grants nothing (AUTH_BLUEPRINT § 7.4a)."""

from django.contrib.auth.backends import AllowAllUsersModelBackend


class CredentialsOnlyBackend(AllowAllUsersModelBackend):
    """
    AllowAllUsersModelBackend so login can record *why* an inactive account was refused (§ 6.2),
    with ModelBackend's permission machinery switched off. Otherwise anything written into
    auth_permission or auth_group (which the Django admin can edit) would be a second grant path
    beside RBAC. dbx.E006 refuses to boot with any backend that has not declared this.
    """

    contributes_permissions = False

    def get_user_permissions(self, user_obj, obj=None):
        return set()

    def get_group_permissions(self, user_obj, obj=None):
        return set()

    def get_all_permissions(self, user_obj, obj=None):
        return set()

    def has_perm(self, user_obj, perm, obj=None):
        return False

    def has_module_perms(self, user_obj, app_label):
        return False
