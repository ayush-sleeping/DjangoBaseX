from django.urls import path

from .views import PermissionCatalogView, RoleViewSet, UserRoleViewSet

app_name = "rbac"

role_list = RoleViewSet.as_view({"get": "list", "post": "create"})
role_detail = RoleViewSet.as_view(
    {"get": "retrieve", "patch": "partial_update", "delete": "destroy"}
)
role_permissions = RoleViewSet.as_view({"put": "permissions"})
user_roles = UserRoleViewSet.as_view({"get": "list", "post": "create"})
user_role_detail = UserRoleViewSet.as_view({"delete": "destroy"})

# Mounted at /api/rbac/ (AUTH_BLUEPRINT § 10.3).
urlpatterns = [
    path("permissions/", PermissionCatalogView.as_view(), name="permissions"),
    path("roles/", role_list, name="roles"),
    path("roles/<uuid:public_id>/", role_detail, name="role"),
    path("roles/<uuid:public_id>/permissions/", role_permissions, name="role-permissions"),
    path("users/<uuid:user_public_id>/roles/", user_roles, name="user-roles"),
    path(
        "users/<uuid:user_public_id>/roles/<uuid:public_id>/",
        user_role_detail,
        name="user-role",
    ),
]
