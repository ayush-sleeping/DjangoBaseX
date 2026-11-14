import hashlib
import json
import logging
from urllib.parse import urlsplit

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from core.api.schemas import DynamicBodySerializer, NavigationSerializer
from core.observability import health

from .api.views import BaseAPIView
from .formatting import locale_policy
from .http import client_ip
from .navigation import navigation_for
from .settings_service import resolve
from .theme import BrandPolicy, derived_tokens

csp_logger = logging.getLogger("core.csp")


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

    The display identity, the platform's locale and timezone, and its brand colours (§ 17: numbers
    per theme, derived and AA-checked here; null = the stylesheet's own). Boot identity (cookie
    names, cache prefix) never leaves the server.
    The frontend reads this in its root layout, so a rename is a restart, not a rebuild."""

    public = True  # registry.public_routes
    authentication_classes: list = []

    @extend_schema(responses=DynamicBodySerializer)
    def get(self, request):
        # The platform's locale and timezone too: signed-out pages and server-rendered text format
        # and (from 8.4c) translate with them. Never currency or country — those are not public.
        policy = locale_policy(None)
        return Response(
            {
                "product_name": settings.PRODUCT_NAME,
                "tagline": settings.PRODUCT_TAGLINE,
                "locale": policy.locale,
                "timezone": policy.timezone,
                "brand": derived_tokens(resolve(BrandPolicy, None).primary),
            }
        )


class CspReportThrottle(SimpleRateThrottle):
    """60/min per client address (hashed): a page in a bad loop must not flood the logs. The rate is
    set here, not in settings: it is a property of this endpoint, not of a deployment."""

    scope = "csp_report"
    rate = "60/min"

    def get_cache_key(self, request, view):
        ident = hashlib.sha256((client_ip(request) or "").encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


CSP_REPORT_MAX_BYTES = 16 * 1024


def _origin(uri) -> str:
    """Scheme and host only: a blocked URI's path and query can carry tokens; never logged."""
    if not isinstance(uri, str) or not uri:
        return ""
    if "://" not in uri:
        return uri[:40]  # "inline", "eval", "data", "self": a keyword, not a URL
    parts = urlsplit(uri)
    return f"{parts.scheme}://{parts.hostname or ''}"[:200]


class CspReportView(BaseAPIView):
    """POST /api/public/csp-report/: browsers' CSP violation reports (FRONTEND_PLATFORM § 18).

    Accepts the legacy `application/csp-report` body and the Reporting API's
    `application/reports+json` list. Logs the directive, the blocked ORIGIN and the page PATH only;
    never the query string or the sample (they can carry tokens or user data). Always 204: a report
    endpoint that errors makes browsers retry."""

    public = True  # registry.public_routes
    authentication_classes: list = []
    throttle_classes = [CspReportThrottle]
    parser_classes: list = []  # the body is read raw, bounded, and parsed here
    schema = None  # browser-to-server telemetry, not part of the API contract

    def post(self, request):
        length = request.META.get("CONTENT_LENGTH") or "0"
        if not length.isdigit() or int(length) > CSP_REPORT_MAX_BYTES:
            return Response(status=413)
        try:
            body = json.loads(request.body or b"null")
        except (ValueError, UnicodeDecodeError):
            return Response(status=204)
        reports = []
        if isinstance(body, dict) and isinstance(body.get("csp-report"), dict):
            reports.append(("enforce-or-report", body["csp-report"]))
        elif isinstance(body, list):
            for item in body[:20]:
                if isinstance(item, dict) and item.get("type") == "csp-violation":
                    if isinstance(item.get("body"), dict):
                        reports.append(("reporting-api", item["body"]))
        for source, report in reports:
            directive = report.get("effective-directive") or report.get("effectiveDirective") or ""
            blocked = report.get("blocked-uri") or report.get("blockedURL") or ""
            document = report.get("document-uri") or report.get("documentURL") or ""
            csp_logger.warning(
                "csp violation",
                extra={
                    "csp_directive": str(directive)[:60],
                    "csp_blocked": _origin(blocked),
                    "csp_page": urlsplit(document).path[:200] if isinstance(document, str) else "",
                    "csp_disposition": str(report.get("disposition", ""))[:20],
                    "csp_source": source,
                },
            )
        return Response(status=204)


class NavigationView(BaseAPIView):
    """GET /api/me/navigation/: the menu this user may follow, built from registry.navigation."""

    required_permissions = []  # any signed-in user; the items are filtered per permission

    @extend_schema(responses=NavigationSerializer)
    def get(self, request):
        return Response({"sections": navigation_for(request.user)})
