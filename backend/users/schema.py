"""
How the API authenticates, described for OpenAPI (FRONTEND_PLATFORM § 24, BUILD_ORDER 8.4a).

The session is httpOnly cookies (ADR-0009), which drf-spectacular cannot infer from
CookieJWTAuthentication: without this every authenticated view is described as unauthenticated and
warns. The cookie's NAME comes from settings at runtime; the schema names the scheme, not a value a
deployment changes, so the committed contract does not differ per deployment.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class CookieJWTScheme(OpenApiAuthenticationExtension):
    target_class = "users.authentication.CookieJWTAuthentication"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "access",
            "description": (
                "The httpOnly access cookie (<AUTH_COOKIE_PREFIX>_access, __Host- prefixed over "
                "HTTPS), set by POST /api/auth/login/ and rotated by /api/auth/refresh/. Unsafe "
                "methods also send X-CSRF-Token."
            ),
        }
