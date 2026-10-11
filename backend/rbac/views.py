"""
/api/rbac/ (AUTH_BLUEPRINT § 10.3). Thin: validate, call rbac.services, respond. Every lookup goes
through visible_to(), so an id the caller may not see answers 404, never 403 (API_DESIGN.md).
"""

from django.contrib.auth import get_user_model
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response

from core.api.views import BaseAPIView
from core.api.viewsets import BaseViewSet

from . import services
from .models import Permission, PermissionGroup, Role
from .serializers import (
    AssignRoleSerializer,
    CatalogGroupSerializer,
    GrantsSerializer,
    RoleCreateSerializer,
    RoleSerializer,
    RoleUpdateSerializer,
)

User = get_user_model()  # rbac never imports users' models (Ch. 2)


def error(exc: services.RbacError, http_status: int, details=None) -> Response:
    body = {"error": {"code": exc.code, "message": str(exc) or exc.__doc__ or exc.code}}
    if details is not None:
        body["error"]["details"] = details
    return Response(body, status=http_status)


def invalid(serializer) -> Response:
    return Response(
        {
            "error": {
                "code": "invalid",
                "message": "Check the fields.",
                "details": serializer.errors,
            }
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def rbac_error_response(exc: services.RbacError) -> Response:
    if isinstance(exc, services.ElevatedRequiresSuperuser):
        return error(exc, status.HTTP_403_FORBIDDEN)
    if isinstance(exc, services.UnknownPermission):
        return error(exc, status.HTTP_400_BAD_REQUEST, details=exc.codes)
    if isinstance(exc, services.RoleInUse):
        return error(exc, status.HTTP_409_CONFLICT, details={"user_count": exc.user_count})
    return error(exc, status.HTTP_409_CONFLICT)  # SystemRoleProtected, LastAdministrator


def roles_for_response(user):
    live = Prefetch("permissions", queryset=Permission.objects.filter(is_deprecated=False))
    return (
        Role.objects.visible_to(user)
        .annotate(user_count=Count("user_roles", distinct=True))
        .prefetch_related(live)
        # Explicit: Count() makes Django drop Meta.ordering, and a page boundary on an unordered
        # list repeats or skips rows. pk breaks ties (API_PLATFORM.md list pipeline).
        .order_by("name", "pk")
    )


class PermissionCatalogView(BaseAPIView):
    required_permissions = ["rbac.permissions.view"]

    def get(self, request):
        groups = PermissionGroup.objects.prefetch_related("permissions")
        return Response(CatalogGroupSerializer(groups, many=True).data)


class RoleViewSet(
    BaseViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
):
    serializer_class = RoleSerializer
    required_permissions = {
        "list": ["rbac.roles.view"],
        "retrieve": ["rbac.roles.view"],
        "create": ["rbac.roles.create"],
        "partial_update": ["rbac.roles.update"],
        "destroy": ["rbac.roles.delete"],
        "permissions": ["rbac.roles.update"],
    }

    def get_queryset(self):
        return roles_for_response(self.request.user)

    def _fresh(self, role) -> Response:
        return RoleSerializer(self.get_queryset().get(pk=role.pk)).data

    def create(self, request):
        serializer = RoleCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        data = dict(serializer.validated_data)
        try:
            role = services.create_role(
                actor=request.user, permission_codes=data.pop("permissions"), **data
            )
        except services.RbacError as exc:
            return rbac_error_response(exc)
        return Response(self._fresh(role), status=status.HTTP_201_CREATED)

    def partial_update(self, request, public_id=None):
        role = self.get_object()
        serializer = RoleUpdateSerializer(data=request.data, context={"role": role})
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            services.update_role(actor=request.user, role=role, **serializer.validated_data)
        except services.RbacError as exc:
            return rbac_error_response(exc)
        return Response(self._fresh(role))

    def destroy(self, request, public_id=None):
        try:
            services.delete_role(actor=request.user, role=self.get_object())
        except services.RbacError as exc:
            return rbac_error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["put"])
    def permissions(self, request, public_id=None):
        """Full replacement of the role's grants; answers with the diff."""
        role = self.get_object()
        serializer = GrantsSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        try:
            diff = services.set_grants(
                actor=request.user,
                role=role,
                permission_codes=serializer.validated_data["permissions"],
            )
        except services.RbacError as exc:
            return rbac_error_response(exc)
        return Response({"added": diff.added, "removed": diff.removed})


class UserRoleViewSet(BaseViewSet):
    """The roles one user holds. The user is resolved through users' own visible_to()."""

    required_permissions = {
        "list": ["rbac.roles.view"],
        "create": ["rbac.roles.assign"],
        "destroy": ["rbac.roles.assign"],
    }

    def _user(self):
        users = User.objects.visible_to(self.request.user)
        return get_object_or_404(users, public_id=self.kwargs["user_public_id"])

    def list(self, request, user_public_id=None):
        held = roles_for_response(request.user).filter(user_roles__user=self._user())
        return Response(RoleSerializer(held, many=True).data)

    def create(self, request, user_public_id=None):
        user = self._user()
        serializer = AssignRoleSerializer(data=request.data)
        if not serializer.is_valid():
            return invalid(serializer)
        role = get_object_or_404(
            Role.objects.visible_to(request.user), public_id=serializer.validated_data["role"]
        )
        try:
            services.assign_role(actor=request.user, user=user, role=role)
        except services.RbacError as exc:
            return rbac_error_response(exc)
        data = RoleSerializer(roles_for_response(request.user).get(pk=role.pk)).data
        return Response(data, status=status.HTTP_201_CREATED)

    def destroy(self, request, user_public_id=None, public_id=None):
        user = self._user()
        role = get_object_or_404(Role.objects.visible_to(request.user), public_id=public_id)
        try:
            services.revoke_role(actor=request.user, user=user, role=role)
        except services.RbacError as exc:
            return rbac_error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
