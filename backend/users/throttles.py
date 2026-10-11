"""
Throttles for the endpoints the whole internet can reach (AUTH_BLUEPRINT § 6.2 step 1, § 6.6, A17).

Rates live in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]. The IP always comes from
core.http.client_ip, never REMOTE_ADDR directly (A20, § 17.3), and the key is a hash, so no address
sits in the cache.
"""

import hashlib

from rest_framework.throttling import SimpleRateThrottle

from core.http import client_ip

from .models.user import normalize_email


def _identifier(request) -> str:
    data = request.data
    email = data.get("email", "") if hasattr(data, "get") else ""
    return normalize_email(str(email))


def _digest(*parts: str) -> str:
    # NUL cannot appear in an email or an IP, so ("a", "bc") and ("ab", "c") never collide.
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


class LoginThrottle(SimpleRateThrottle):
    """5/min per (identifier, ip) pair: both together, so one victim's address cannot be throttled
    away from everyone else by an attacker on another IP."""

    scope = "login"

    def get_cache_key(self, request, view):
        ident = _digest(_identifier(request), client_ip(request) or "")
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordResetThrottle(SimpleRateThrottle):
    """3/hour per identifier, from any IP: it bounds how many emails one address can be sent."""

    scope = "password_reset"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": _digest(_identifier(request))}


class MfaVerifyThrottle(SimpleRateThrottle):
    """5/min per mfa_token (§ 6.8): its own budget, so the 10⁶-wide code space is the real limit."""

    scope = "mfa_verify"

    def get_cache_key(self, request, view):
        data = request.data
        token = data.get("mfa_token", "") if hasattr(data, "get") else ""
        return self.cache_format % {"scope": self.scope, "ident": _digest(str(token))}


class MfaThrottle(SimpleRateThrottle):
    """10/min per signed-in user across setup, confirm, disable and password confirmation."""

    scope = "mfa"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class InvitationAcceptThrottle(SimpleRateThrottle):
    """10/hour per IP on the public accept endpoint (§ 10.1): long tokens, but not free guesses."""

    scope = "invitation_accept"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": _digest(client_ip(request) or "")}
