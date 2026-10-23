from django.conf import settings
from django.db import connection
from rest_framework import status
from rest_framework.response import Response

from .api.views import BaseAPIView
from .navigation import navigation_for


class HealthView(BaseAPIView):
    """Public liveness/readiness probe."""

    public = True  # registry.public_routes
    authentication_classes: list = []

    def get(self, request):
        checks = {"database": self._check_database()}
        healthy = all(checks.values())
        return Response(
            {
                "status": "ok" if healthy else "degraded",
                "checks": checks,
            },
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _check_database() -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception:
            return False


class PublicConfigView(BaseAPIView):
    """GET /api/public/config/: what any visitor's page needs before sign-in (CONFIGURATION § 7).

    The display identity only. Boot identity (cookie names, cache prefix) never leaves the server.
    The frontend reads this in its root layout, so a rename is a restart, not a rebuild."""

    public = True  # registry.public_routes
    authentication_classes: list = []

    def get(self, request):
        return Response(
            {"product_name": settings.PRODUCT_NAME, "tagline": settings.PRODUCT_TAGLINE}
        )


class NavigationView(BaseAPIView):
    """GET /api/me/navigation/: the menu this user may follow, built from registry.navigation."""

    required_permissions = []  # any signed-in user; the items are filtered per permission

    def get(self, request):
        return Response({"sections": navigation_for(request.user)})
