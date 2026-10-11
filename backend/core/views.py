from django.db import connection
from rest_framework import status
from rest_framework.response import Response

from .api.views import BaseAPIView


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
                "app": "DjangoBaseX",
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
