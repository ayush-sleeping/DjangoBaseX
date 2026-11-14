"""BaseViewSet — every API viewset inherits this; there is no other base (§ 9.1)."""

from typing import ClassVar

from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.settings import api_settings

from core.api.listing import run_list
from core.api_tokens.auth import ApiTokenAuthentication
from core.permissions import CredentialKindAllowed, HasPermission


class BaseViewSet(viewsets.GenericViewSet):
    """
    required_permissions maps each action to its codes; an action missing from it denies.
    Filtering and ordering are opt-in per field: forgetting closes the door (API_DESIGN.md).
    """

    required_permissions: ClassVar[dict[str, list[str]] | None] = None
    public: ClassVar[bool] = False
    permission_classes = [HasPermission]
    # A machine token is a separate credential kind (ADR-0016): the token authenticator claims only
    # `Bearer <prefix>_…`; everything else falls through to the project's default (cookie) one.
    authentication_classes = [ApiTokenAuthentication, *api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    # Default closed: a view is machine-reachable only by opting in; human_only refuses tokens.
    credential_kinds: ClassVar[frozenset[str]] = frozenset({"session"})
    human_only: ClassVar[bool] = False
    lookup_field = "public_id"  # internal ids never appear in a URL (A15)

    filterset_fields: ClassVar[tuple[str, ...]] = ()
    ordering_fields: ClassVar[tuple[str, ...]] = ()
    # Params the view reads itself (search, custom filters); anything else is a 400 (listing.py).
    accepted_params: ClassVar[tuple[str, ...]] = ()
    max_page_size: ClassVar[int] = 100

    def get_permissions(self):
        # Same rule as BaseAPIView: a session first (anonymous → 401), unless declared public.
        if self.public:
            return [HasPermission()]
        return [CredentialKindAllowed(), IsAuthenticated(), *super().get_permissions()]

    def scope(self, queryset):
        """
        The one way a viewset applies Layer-2 scoping (DATA_LIFECYCLE.md § 12.4): reads narrow with
        visible_to(), every unsafe method (update, destroy and any write @action) with
        writable_by(). Pass the model's manager or queryset; an invisible row is then a 404.
        """
        user = self.request.user
        if self.request.method in SAFE_METHODS:
            return queryset.visible_to(user)
        return queryset.writable_by(user)

    def filter_queryset(self, queryset):
        return run_list(queryset, self, self.request.query_params)
