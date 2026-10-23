from django.conf import settings
from rest_framework.response import Response

from core.observability import health

from .api.views import BaseAPIView
from .navigation import navigation_for


class LiveView(BaseAPIView):
    """GET /api/health/live/ and its alias /api/health/: no I/O (OBSERVABILITY § 6).

    HealthShortCircuitMiddleware answers first; this view exists so reverse() works and the
    public-route ledger stays honest, and answers exactly the same."""

    public = True  # registry.public_routes
    authentication_classes: list = []
    throttle_classes: list = []
    schema = None  # excluded from the OpenAPI document

    def get(self, request):
        return health.live()


class ReadyView(LiveView):
    """GET /api/health/ready/: database + cache, fixed-token 503, never cached."""

    def get(self, request):
        return health.ready()


class ComponentsView(BaseAPIView):
    """GET /api/health/components/: every probe, per component; degraded is 200, down is 503."""

    required_permissions = ["core.health.view"]
    schema = None

    def get(self, request):
        try:
            body, code = health.components()
        except Exception:  # noqa: BLE001 — a health endpoint that 500s when unwell is useless
            body, code = {"status": health.DOWN, "release": health.read_release()}, 503
        return Response(body, status=code)


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
