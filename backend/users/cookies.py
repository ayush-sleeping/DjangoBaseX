"""
The three auth cookies (AUTH_BLUEPRINT § 6.1, § 17.5). The only place their names, paths and
flags are decided.

| cookie  | holds                 | JS-readable | path                                        |
|---------|-----------------------|-------------|---------------------------------------------|
| access  | 10-minute JWT         | no          | /api/ (/ when __Host- applies)              |
| refresh | rotating refresh JWT  | no          | /api/auth/refresh/ only — not sent elsewhere |
| csrf    | session-bound token   | yes         | / (the frontend echoes it in X-CSRF-Token)  |
| session | the constant "1"      | no          | / — a marker for page navigations (DB-20)   |

With Secure on and no shared cookie domain, access and csrf get the `__Host-` prefix: the browser
then refuses any Set-Cookie for them that carries a Domain or a non-/ path, which shuts out cookie
injection from sibling subdomains. `__Host-` requires Path=/ and Secure, so it is off in plain-HTTP
development and the refresh cookie keeps its narrow path instead.
"""

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

REFRESH_PATH = f"/{settings.API_PREFIX}/auth/refresh/"  # derived (DB-24)
CSRF_HEADER = "HTTP_X_CSRF_TOKEN"  # X-CSRF-Token


@dataclass(frozen=True)
class CookieNames:
    access: str
    refresh: str
    csrf: str
    session: str
    host_prefixed: bool


def cookie_names() -> CookieNames:
    host_prefixed = settings.AUTH_COOKIE_SECURE and not settings.AUTH_COOKIE_DOMAIN
    prefix = "__Host-" if host_prefixed else ""
    base = settings.AUTH_COOKIE_PREFIX
    return CookieNames(
        access=f"{prefix}{base}_access",
        refresh=f"{base}_refresh",
        csrf=f"{prefix}{base}_csrf",
        session=f"{prefix}{base}_session",
        host_prefixed=host_prefixed,
    )


def _common() -> dict:
    return {
        "secure": settings.AUTH_COOKIE_SECURE,
        "samesite": "Lax",
        "domain": settings.AUTH_COOKIE_DOMAIN or None,
    }


def _access_path(names: CookieNames) -> str:
    return "/" if names.host_prefixed else f"/{settings.API_PREFIX}/"


def set_auth_cookies(response, issued) -> None:
    names = cookie_names()
    session_seconds = max(0, int((issued.session.expires_at - timezone.now()).total_seconds()))
    response.set_cookie(
        names.access,
        issued.access,
        max_age=settings.ACCESS_TOKEN_LIFETIME,
        path=_access_path(names),
        httponly=True,
        **_common(),
    )
    response.set_cookie(
        names.refresh,
        issued.refresh,
        max_age=session_seconds,
        path=REFRESH_PATH,
        httponly=True,
        **_common(),
    )
    response.set_cookie(
        names.csrf, issued.csrf, max_age=session_seconds, path="/", httponly=False, **_common()
    )
    # TECH_DEBT DB-20: the session MARKER. Path=/ so a page navigation (a Next.js route guard)
    # can tell "probably signed in, refresh on the client" from "signed out" once the /api/-scoped
    # access cookie has expired. It holds no credential: the value is a constant, never a token.
    response.set_cookie(
        names.session, "1", max_age=session_seconds, path="/", httponly=True, **_common()
    )


def clear_auth_cookies(response) -> None:
    names = cookie_names()
    common = {"samesite": "Lax", "domain": settings.AUTH_COOKIE_DOMAIN or None}
    response.delete_cookie(names.access, path=_access_path(names), **common)
    response.delete_cookie(names.refresh, path=REFRESH_PATH, **common)
    response.delete_cookie(names.csrf, path="/", **common)
    response.delete_cookie(names.session, path="/", **common)
