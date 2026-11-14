"""BaseAPIView — every non-viewset API endpoint inherits this; there is no other base (§ 9.1)."""

from typing import ClassVar

from rest_framework.permissions import IsAuthenticated
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from core.api_tokens.auth import ApiTokenAuthentication
from core.permissions import CredentialKindAllowed, HasPermission


class BaseAPIView(APIView):
    """
    required_permissions: None denies everyone; [] means any signed-in user; ["a.b.c"] needs each.
    public = True opens it to anyone, and its URL name must be in registry.public_routes
    (dbx.E007). See core.permissions for the full rule.
    """

    required_permissions: ClassVar[list[str] | None] = None
    public: ClassVar[bool] = False
    permission_classes = [HasPermission]
    # A machine token is a separate credential kind (ADR-0016): the token authenticator claims only
    # `Bearer <prefix>_…`; everything else falls through to the project's default (cookie) one.
    authentication_classes = [ApiTokenAuthentication, *api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    # Default closed: a view is machine-reachable only by opting in; human_only refuses tokens.
    credential_kinds: ClassVar[frozenset[str]] = frozenset({"session"})
    human_only: ClassVar[bool] = False

    def get_permissions(self):
        # Public endpoints skip IsAuthenticated; everything else needs a session first, so an
        # anonymous caller gets 401 (authenticate) rather than 403.
        if self.public:
            return [HasPermission()]
        return [CredentialKindAllowed(), IsAuthenticated(), *super().get_permissions()]
