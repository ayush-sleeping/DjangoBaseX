"""
BUILD_ORDER 9.2 done-when tests and the machine-caller contract (ADR-0016).

Gates: a machine request passes only if the token's scope AND the service role's live grants both
include the code. Revoked, expired and deactivated callers are 401. The plaintext is never
retrievable after the create response.
"""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient

from core.api.views import BaseAPIView
from core.api_tokens import services
from core.api_tokens.models import ApiToken
from core.models import PrivateFile
from rbac import services as rbac
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

CODE = "settings.settings.view"


class ProbeView(BaseAPIView):
    """A token-accepting endpoint, mounted only in these tests."""

    required_permissions = [CODE]
    credential_kinds = frozenset({"session", "token"})

    def get(self, request):
        return Response({"ok": True})


class SessionOnlyView(BaseAPIView):
    required_permissions = [CODE]

    def get(self, request):
        return Response({"ok": True})


urlpatterns = [
    path("probe/", ProbeView.as_view()),
    path("session-only/", SessionOnlyView.as_view()),
]


def make_role(*codes):
    slug = f"svc-{len(codes)}-{timezone.now().timestamp()}".replace(".", "-")
    return rbac.create_role(actor=None, name=slug, slug=slug, permission_codes=list(codes))


def consumer_with(role, name="warehouse-sync"):
    return services.create_consumer(actor=None, name=name, service_role=role)


def issue(consumer, scopes, days=30):
    return services.issue_token(
        actor=None,
        consumer=consumer,
        name="main",
        scopes=scopes,
        expires_at=timezone.now() + timedelta(days=days),
    )


def bearer(plaintext):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    return client


@pytest.fixture
def machine_urls():
    with override_settings(ROOT_URLCONF="tests.core.test_api_platform"):
        yield


def test_both_gates_must_pass(machine_urls):
    role = make_role(CODE)
    consumer = consumer_with(role)
    _, both = issue(consumer, [CODE])
    assert bearer(both).get("/probe/").status_code == 200

    # role grants it, the token's scope does not
    _, other_scope = issue(consumer, [CODE])
    token = ApiToken.objects.get(digest=services.digest_of(other_scope))
    ApiToken.objects.filter(pk=token.pk).update(scopes=["settings.flags.view"])
    assert bearer(other_scope).get("/probe/").status_code == 403

    # scope is on the token, but the role lost the permission since issue: live ceiling
    rbac.set_grants(actor=None, role=role, permission_codes=[])
    assert bearer(both).get("/probe/").status_code == 403


def test_a_wildcard_token_is_bounded_by_its_role(machine_urls):
    consumer = consumer_with(make_role())  # grants nothing
    _, plaintext = issue(consumer, ["*"])
    assert bearer(plaintext).get("/probe/").status_code == 403


def test_revoked_expired_and_inactive_are_401(machine_urls):
    consumer = consumer_with(make_role(CODE))
    revoked, p_revoked = issue(consumer, [CODE])
    services.revoke_token(actor=None, token=revoked, reason="leaked")
    expired, p_expired = issue(consumer, [CODE])
    ApiToken.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert bearer(p_revoked).get("/probe/").status_code == 401
    assert bearer(p_expired).get("/probe/").status_code == 401
    _, live = issue(consumer, [CODE])
    assert bearer(live).get("/probe/").status_code == 200
    services.update_consumer(actor=None, consumer=consumer, is_active=False, disabled_reason="x")
    assert bearer(live).get("/probe/").status_code == 401
    assert bearer("not-a-token").get("/probe/").status_code == 401  # no cookie either


def test_a_token_does_not_reach_a_session_only_view_and_cookie_users_are_unaffected(machine_urls):
    consumer = consumer_with(make_role(CODE))
    _, plaintext = issue(consumer, [CODE])
    refused = bearer(plaintext).get("/session-only/")
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "credential_not_accepted"

    user = UserFactory()
    rbac.assign_role(actor=None, user=user, role=make_role(CODE))
    human = APIClient()
    human.force_authenticate(user=user)
    assert human.get("/session-only/").status_code == 200
    assert human.get("/probe/").status_code == 200


def test_a_token_authenticates_as_a_machine_never_a_user(machine_urls):
    consumer = consumer_with(make_role(CODE))
    token, plaintext = issue(consumer, [CODE])
    from core.api_tokens.auth import ApiTokenAuthentication

    request = APIClient().get("/probe/", HTTP_AUTHORIZATION=f"Bearer {plaintext}").wsgi_request
    principal, auth = ApiTokenAuthentication().authenticate(request)
    assert principal.is_machine and not principal.is_superuser
    assert auth.pk == token.pk
    assert not hasattr(principal, "email")


def test_the_plaintext_is_stored_as_a_digest_and_never_returned_again():
    role = make_role(
        "core.api_consumers.view", "core.api_consumers.manage", "core.api_tokens.issue"
    )
    admin = UserFactory()
    rbac.assign_role(actor=None, user=admin, role=role)
    client = APIClient()
    client.force_authenticate(user=admin)
    created = client.post(
        "/api/consumers/",
        {"name": "site-feed", "service_role": make_role(CODE).slug},
        format="json",
    )
    assert created.status_code == 201
    consumer_id = created.json()["id"]
    issued = client.post(
        f"/api/consumers/{consumer_id}/tokens/",
        {
            "name": "main",
            "scopes": [CODE],
            "expires_at": (timezone.now() + timedelta(days=30)).isoformat(),
        },
        format="json",
    )
    assert issued.status_code == 201
    assert "no-store" in issued["Cache-Control"]
    plaintext = issued.json()["token"]
    row = ApiToken.objects.get()
    assert plaintext not in (row.digest, row.prefix) and row.digest == services.digest_of(plaintext)
    listing = client.get(f"/api/consumers/{consumer_id}/tokens/")
    assert "token" not in listing.json()[0] and plaintext not in listing.content.decode()
    # a token cannot administer tokens: the admin API is human-only
    assert bearer(plaintext).get("/api/consumers/").status_code == 403


def test_a_typo_scope_and_an_ungranted_scope_are_refused_at_issue():
    consumer = consumer_with(make_role(CODE))
    for scopes in (["settings.settings.vieww"], ["settings.flags.manage"], [], ["*", CODE]):
        with pytest.raises(services.TokenError):
            issue(consumer, scopes)
    with pytest.raises(services.TokenError):  # expiry is required and capped
        services.issue_token(
            actor=None, consumer=consumer, name="x", scopes=[CODE], expires_at=None
        )
    with pytest.raises(services.TokenError):
        issue(consumer, [CODE], days=services.MAX_LIFETIME_DAYS + 1)
    assert ApiToken.objects.count() == 0


def test_rotation_mints_a_successor_and_ends_the_predecessor_after_the_overlap(machine_urls):
    consumer = consumer_with(make_role(CODE))
    old, old_plain = issue(consumer, [CODE], days=90)
    new, new_plain = services.rotate_token(actor=None, token=old)
    old.refresh_from_db()
    assert new.rotated_from_id == old.pk and new.scopes == [CODE] and new_plain != old_plain
    assert old.expires_at <= timezone.now() + timedelta(hours=services.ROTATION_OVERLAP_HOURS)
    assert bearer(old_plain).get("/probe/").status_code == 200  # still inside the overlap
    assert bearer(new_plain).get("/probe/").status_code == 200


def test_every_machine_change_is_audited(audit_rows):
    consumer = consumer_with(make_role(CODE))
    token, _ = issue(consumer, [CODE])
    services.set_scopes(actor=None, token=token, scopes=[CODE])
    successor, _ = services.rotate_token(actor=None, token=token)
    services.revoke_token(actor=None, token=successor)
    services.update_consumer(actor=None, consumer=consumer, is_active=False)
    seen = {row.action for row in audit_rows()}
    assert {
        "core.api_consumer.created",
        "core.api_token.issued",
        "core.api_token.scopes_changed",
        "core.api_token.rotated",
        "core.api_token.revoked",
        "core.api_consumer.deactivated",
    } <= seen


# --- the shared list pipeline ----------------------------------------------------------------


def test_a_list_sorted_on_a_non_unique_column_never_repeats_or_drops_a_row_across_pages():
    admin = UserFactory()
    rbac.assign_role(actor=None, user=admin, role=make_role("users.users.view", "rbac.roles.view"))
    for _ in range(45):  # more than two pages, every row sharing one sort key
        UserFactory(full_name="Same Name")
    client = APIClient()
    client.force_authenticate(user=admin)
    seen, url = [], "/api/users/?ordering=full_name"
    while url:
        body = client.get(url).json()
        seen += [row["email"] for row in body["results"]]
        url = body["next"]
    expected = set(UserFactory._meta.model.objects.values_list("email", flat=True))
    assert len(seen) == len(set(seen)) == len(expected) == 46
    assert expected == set(seen)


def test_unknown_filter_and_ordering_params_are_a_400_not_ignored():
    admin = UserFactory()
    rbac.assign_role(actor=None, user=admin, role=make_role("users.users.view"))
    client = APIClient()
    client.force_authenticate(user=admin)
    typo = client.get("/api/users/?is_actve=true")
    assert typo.status_code == 400 and typo.json()["error"]["code"] == "unknown_parameter"
    bad_order = client.get("/api/users/?ordering=password")
    assert bad_order.status_code == 400
    assert client.get("/api/users/?search=a&page=1").status_code == 200


# --- the 429 contract -----------------------------------------------------------------------


def test_a_429_carries_retry_after_and_the_throttled_code():
    from rest_framework.exceptions import Throttled

    from core.api.exceptions import handler

    class View:
        throttle_scope = "login"

    response = handler(Throttled(wait=0.2), {"view": View(), "request": None})
    assert response.status_code == 429
    assert response["Retry-After"] == "1"  # never below 1
    error = response.data["error"]
    assert error["code"] == "throttled" and error["retry_after_seconds"] == 1
    assert error["details"] == {"scope": "login"}


# --- uploads and private serving ------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def uploader(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    user = UserFactory()
    rbac.assign_role(actor=None, user=user, role=make_role("core.files.upload", "core.files.view"))
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def upload(client, name, data):
    return client.post(
        "/api/files/",
        {"purpose": "general", "file": SimpleUploadedFile(name, data)},
        format="multipart",
    )


def test_an_upload_renamed_to_png_but_containing_html_is_refused(uploader):
    refused = upload(uploader, "photo.png", b"<html><script>alert(1)</script></html>")
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "unsupported_file_type"
    assert PrivateFile.objects.count() == 0
    # a real PNG under a PDF name disagrees with itself too
    assert upload(uploader, "photo.pdf", PNG).status_code == 400
    assert PrivateFile.objects.count() == 0


def test_a_real_png_is_stored_privately_and_served_only_through_the_permission_check(
    uploader, tmp_path
):
    created = upload(uploader, "logo.png", PNG)
    assert created.status_code == 201
    file_id = created.json()["id"]
    served = uploader.get(f"/api/files/{file_id}/")
    assert served.status_code == 200
    assert served["Content-Type"] == "image/png" and served["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in served["Content-Disposition"]
    stored = list((tmp_path / "private").iterdir())
    assert (
        len(stored) == 1 and stored[0].name == f"{file_id}.png"
    )  # generated name, not the client's

    nobody = UserFactory()
    outsider = APIClient()
    outsider.force_authenticate(user=nobody)
    assert outsider.get(f"/api/files/{file_id}/").status_code == 404  # reveals nothing
    assert APIClient().get(f"/api/files/{file_id}/").status_code == 401
