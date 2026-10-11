"""BaseViewSet — every API viewset inherits this; there is no other base (§ 9.1)."""

from typing import ClassVar

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from core.permissions import HasPermission


class BaseViewSet(viewsets.GenericViewSet):
    """
    required_permissions maps each action to its codes; an action missing from it denies.
    Filtering and ordering are opt-in per field: forgetting closes the door (API_DESIGN.md).
    """

    required_permissions: ClassVar[dict[str, list[str]] | None] = None
    public: ClassVar[bool] = False
    permission_classes = [HasPermission]
    lookup_field = "public_id"  # internal ids never appear in a URL (A15)

    filterset_fields: ClassVar[tuple[str, ...]] = ()
    ordering_fields: ClassVar[tuple[str, ...]] = ()
    max_page_size: ClassVar[int] = 100

    def get_permissions(self):
        # Same rule as BaseAPIView: a session first (anonymous → 401), unless declared public.
        if self.public:
            return [HasPermission()]
        return [IsAuthenticated(), *super().get_permissions()]
