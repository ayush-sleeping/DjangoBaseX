"""Login and password-reset throttles (AUTH_BLUEPRINT § 6.2 step 1, § 6.6, A17, A20)."""

import pytest
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from users.throttles import LoginThrottle, PasswordResetThrottle

factory = APIRequestFactory()
VICTIM, IP, OTHER_IP = "victim@example.com", "203.0.113.7", "198.51.100.1"


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        return Response(status=204)


class ForgotView(LoginView):
    throttle_classes = [PasswordResetThrottle]


def post(view, email=VICTIM, ip=IP, **extra):
    request = factory.post("/", {"email": email}, format="json", REMOTE_ADDR=ip, **extra)
    return view.as_view()(request).status_code


# --- Login: 5/min per (identifier, ip) ----------------------------------------------------------


def test_the_sixth_login_in_a_minute_for_one_pair_is_throttled():
    assert [post(LoginView) for _ in range(6)] == [204] * 5 + [429]


def test_another_email_or_another_ip_is_a_different_pair():
    for _ in range(5):
        post(LoginView)
    assert post(LoginView) == 429
    assert post(LoginView, email="someone-else@example.com") == 204
    assert post(LoginView, ip=OTHER_IP) == 204


def test_the_email_is_normalised_before_keying():
    for _ in range(5):
        post(LoginView)
    assert post(LoginView, email="  Victim@EXAMPLE.com ") == 429


def test_a_spoofed_forwarded_for_does_not_change_the_key_without_trusted_proxies(settings):
    settings.TRUSTED_PROXY_COUNT = 0
    statuses = [post(LoginView, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}") for i in range(6)]
    assert statuses == [204] * 5 + [429]


def test_the_key_follows_client_ip_behind_a_trusted_proxy(settings):
    # Every request arrives from the same load balancer; the client is the rightmost XFF entry.
    settings.TRUSTED_PROXY_COUNT = 1
    for _ in range(5):
        post(LoginView, HTTP_X_FORWARDED_FOR=f"1.1.1.1, {IP}")
    assert post(LoginView, HTTP_X_FORWARDED_FOR=f"9.9.9.9, {IP}") == 429  # spoofed head ignored
    assert post(LoginView, HTTP_X_FORWARDED_FOR=OTHER_IP) == 204


def test_a_body_without_an_email_is_still_throttled():
    def send():
        return LoginView.as_view()(factory.post("/", [], format="json", REMOTE_ADDR=IP))

    assert [send().status_code for _ in range(6)] == [204] * 5 + [429]


def test_no_raw_email_or_ip_in_the_cache_key():
    request = LoginView().initialize_request(
        factory.post("/", {"email": VICTIM}, format="json", REMOTE_ADDR=IP)
    )
    for throttle in (LoginThrottle(), PasswordResetThrottle()):
        key = throttle.get_cache_key(request, view=None)
        assert "victim" not in key and IP not in key
        assert key.startswith(f"throttle_{throttle.scope}_")


# --- Password reset: 3/hour per identifier ------------------------------------------------------


def test_the_fourth_reset_request_for_one_address_is_throttled_from_any_ip():
    statuses = [post(ForgotView, ip=f"203.0.113.{i}") for i in range(4)]
    assert statuses == [204] * 3 + [429]


def test_reset_throttling_is_per_identifier():
    for _ in range(3):
        post(ForgotView)
    assert post(ForgotView) == 429
    assert post(ForgotView, email="someone-else@example.com") == 204


@pytest.mark.parametrize("view", [LoginView, ForgotView])
def test_throttles_answer_429_with_retry_after(view):
    for _ in range(5):
        post(view)
    request = factory.post("/", {"email": VICTIM}, format="json", REMOTE_ADDR=IP)
    response = view.as_view()(request)
    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0
