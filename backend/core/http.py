"""Request helpers every app shares. The one place the caller's IP address is decided."""

from django.conf import settings


def client_ip(request) -> str | None:
    """
    The caller's address, or None. Never trusts a header we have not been told to trust.

    Behind N proxies the real client is the Nth entry from the RIGHT of X-Forwarded-For: each
    trusted proxy appends what it saw, and everything to the left of them is whatever the client
    chose to send. Taking the leftmost entry lets a caller pick a new identity per request and walk
    straight past throttling and lockout (AUTH_BLUEPRINT § 17.3).
    """
    n = settings.TRUSTED_PROXY_COUNT
    if n <= 0:
        return request.META.get("REMOTE_ADDR")
    header = request.META.get("HTTP_X_FORWARDED_FOR", "")
    chain = [part.strip() for part in header.split(",") if part.strip()]
    return chain[-n] if len(chain) >= n else request.META.get("REMOTE_ADDR")
