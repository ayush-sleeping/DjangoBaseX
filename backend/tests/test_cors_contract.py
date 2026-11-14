"""
The browser can actually call the API from the frontend's origin.

In development (and any deployment where the frontend and API are different origins) every API call
is cross-origin. The frontend's client sets custom request headers (X-Request-ID on every call); a
header the CORS preflight does not allow makes the browser drop the real request, and the page says
"Could not reach the server" while the API logs only the OPTIONS. Response headers it reads must be
exposed, or the browser hides them.

The header names are read from the frontend client itself, so adding a header there without
allowing it here fails this test, not a user's browser.
"""

import re
from pathlib import Path

import pytest
from django.test import Client, override_settings

CLIENT_TS = Path(__file__).resolve().parents[2] / "frontend/src/core/lib/api/client.ts"
ORIGIN = "http://web.test"
# CORS-safelisted request headers never need allowing (Fetch standard). Content-Type does when it is
# application/json, so it is not listed here.
SAFELISTED = {"accept", "accept-language", "content-language"}
# Response headers a browser always exposes (CORS-safelisted response headers).
EXPOSED_BY_DEFAULT = {
    "cache-control",
    "content-language",
    "content-length",
    "content-type",
    "expires",
    "last-modified",
    "pragma",
}


def _names(pattern: str) -> set[str]:
    source = CLIENT_TS.read_text(encoding="utf-8")
    found = {name.lower() for name in re.findall(pattern, source)}
    assert found, f"no header names found in {CLIENT_TS}: the pattern no longer matches the client"
    return found


@pytest.mark.django_db
@override_settings(CORS_ALLOWED_ORIGINS=[ORIGIN])
def test_every_header_the_frontend_sends_is_allowed_by_the_preflight():
    sent = _names(r'headers\.set\("([A-Za-z-]+)"') - SAFELISTED
    response = Client().options(
        "/api/auth/login/",
        HTTP_ORIGIN=ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS=",".join(sorted(sent)),
    )
    assert response.status_code == 200
    allowed = {h.strip().lower() for h in response["Access-Control-Allow-Headers"].split(",")}
    assert sent <= allowed, f"the preflight does not allow {sorted(sent - allowed)}"


@pytest.mark.django_db
@override_settings(CORS_ALLOWED_ORIGINS=[ORIGIN])
def test_every_header_the_frontend_reads_is_exposed():
    read = _names(r'res\.headers\.get\("([A-Za-z-]+)"\)') - EXPOSED_BY_DEFAULT
    # An ordinary API route (a 401 here still carries CORS headers); the health probes answer above
    # the CORS middleware, and no browser calls them.
    response = Client().get("/api/auth/me/", HTTP_ORIGIN=ORIGIN)
    exposed = {
        h.strip().lower() for h in response.get("Access-Control-Expose-Headers", "").split(",")
    }
    assert read <= exposed, f"the browser would hide {sorted(read - exposed)}"
