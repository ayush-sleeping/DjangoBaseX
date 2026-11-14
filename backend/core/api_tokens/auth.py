"""
ApiTokenAuthentication and MachinePrincipal (API_PLATFORM.md § 7–9, ADR-0016).

The authenticator claims ONLY `Authorization: Bearer <prefix>_…`; anything else is ignored so the
cookie authenticator is untouched. A machine never is a User: no password, no session, never a
superuser. has_perm answers true only when the token's scope AND the service role's live grants
both include the code.
"""

import hmac
from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from core.observability.request_id import USER_ID
from core.registry import registry

from .models import ApiToken
from .services import digest_of, role_grants, scope_allows, token_prefix

_TOUCH_EVERY = timedelta(minutes=1)


class MachinePrincipal:
    is_authenticated = True
    is_active = True
    is_anonymous = False
    is_superuser = False  # a machine can never reach "everything"
    is_staff = False
    is_machine = True

    def __init__(self, token: ApiToken):
        self.token = token
        self.consumer = token.consumer
        self.pk = f"consumer:{token.consumer_id}"  # throttle keys never collide with user pks
        self.public_id = token.consumer.public_id
        self._grants: frozenset[str] | None = None

    def has_perm(self, code: str, obj=None) -> bool:
        if code not in registry.permissions.codes():
            return False  # unknown code: deny, as for users
        if not scope_allows(self.token.scopes, code):
            return False  # gate 1: the credential
        if self._grants is None:  # live per request, never frozen on the token
            self._grants = role_grants(self.consumer.service_role_id)
        return code in self._grants  # gate 2: the live ceiling

    def has_perms(self, codes, obj=None) -> bool:
        return all(self.has_perm(code) for code in codes)

    def __str__(self):
        return f"consumer:{self.consumer.name}"


class ApiTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            return None
        try:
            plaintext = parts[1].decode("ascii")
        except UnicodeDecodeError:
            return None
        if not plaintext.startswith(f"{token_prefix()}_"):
            return None  # not ours: leave it to the other authenticators
        digest = digest_of(plaintext)
        token = ApiToken.objects.select_related("consumer").filter(digest=digest).first()
        failure = AuthenticationFailed("Invalid or expired token.")
        if token is None or not hmac.compare_digest(token.digest, digest):
            raise failure
        if token.revoked_at is not None or token.expires_at <= timezone.now():
            raise failure
        if not token.consumer.is_active:
            raise failure
        now = timezone.now()
        if token.last_used_at is None or now - token.last_used_at > _TOUCH_EVERY:
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
        USER_ID.set(f"consumer:{token.consumer.public_id}")
        return (MachinePrincipal(token), token)

    def authenticate_header(self, request):
        return 'Bearer realm="api"'


from drf_spectacular.extensions import OpenApiAuthenticationExtension  # noqa: E402


class ApiTokenScheme(OpenApiAuthenticationExtension):
    """Documents the machine credential in the OpenAPI contract as an HTTP bearer scheme."""

    target_class = "core.api_tokens.auth.ApiTokenAuthentication"
    name = "apiToken"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "description": "An API consumer token."}
