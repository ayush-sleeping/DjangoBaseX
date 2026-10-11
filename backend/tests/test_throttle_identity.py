"""
TECH_DEBT DB-30: DRF's throttles must key on the same client address as core.http.client_ip().

With NUM_PROXIES unset, DRF keys AnonRateThrottle on the WHOLE client-supplied X-Forwarded-For,
so rotating that header gives every request a fresh bucket and the limit means nothing.
"""

from django.conf import settings
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import AnonRateThrottle

from core.http import client_ip


def drf_request(xff=None, remote="10.0.0.1"):
    extra = {"REMOTE_ADDR": remote}
    if xff is not None:
        extra["HTTP_X_FORWARDED_FOR"] = xff
    return Request(APIRequestFactory().get("/", **extra))


def test_drf_trusts_exactly_as_many_proxies_as_client_ip():
    assert settings.REST_FRAMEWORK["NUM_PROXIES"] == settings.TRUSTED_PROXY_COUNT


def test_a_spoofed_forwarded_for_does_not_change_the_throttle_identity():
    throttle = AnonRateThrottle()
    idents = {throttle.get_ident(drf_request(xff=f"6.6.6.{n}")) for n in range(5)}
    assert idents == {"10.0.0.1"}  # one bucket, however the header is rotated


def test_drf_and_client_ip_agree_behind_a_proxy(settings):
    rest = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    settings.REST_FRAMEWORK, settings.TRUSTED_PROXY_COUNT = rest, 1
    request = drf_request(xff="6.6.6.6, 203.0.113.7")
    assert AnonRateThrottle().get_ident(request) == client_ip(request) == "203.0.113.7"
