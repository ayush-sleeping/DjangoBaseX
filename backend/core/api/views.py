"""BaseAPIView — every non-viewset API endpoint inherits this; there is no other base (§ 9.1)."""

from typing import ClassVar

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.permissions import HasPermission


class BaseAPIView(APIView):
    """
    required_permissions: None denies everyone; [] means any signed-in user; ["a.b.c"] needs each.
    public = True opens it to anyone, and its URL name must be in registry.public_routes
    (dbx.E007). See core.permissions for the full rule.
    """

    required_permissions: ClassVar[list[str] | None] = None
    public: ClassVar[bool] = False
    permission_classes = [HasPermission]

    def get_permissions(self):
        # Public endpoints skip IsAuthenticated; everything else needs a session first, so an
        # anonymous caller gets 401 (authenticate) rather than 403.
        if self.public:
            return [HasPermission()]
        return [IsAuthenticated(), *super().get_permissions()]
