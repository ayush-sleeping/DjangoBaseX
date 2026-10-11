from django.test import RequestFactory, SimpleTestCase, override_settings

from core.http import client_ip

PROXY = "10.0.0.1"


def request(xff=None):
    extra = {"REMOTE_ADDR": PROXY}
    if xff is not None:
        extra["HTTP_X_FORWARDED_FOR"] = xff
    return RequestFactory().get("/", **extra)


class ClientIpTests(SimpleTestCase):
    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_no_trusted_proxy_uses_remote_addr(self):
        self.assertEqual(client_ip(request()), PROXY)

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_no_trusted_proxy_ignores_spoofed_forwarded_for(self):
        self.assertEqual(client_ip(request("6.6.6.6")), PROXY)

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_one_proxy_takes_the_rightmost_entry(self):
        self.assertEqual(client_ip(request("203.0.113.7")), "203.0.113.7")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_one_proxy_ignores_a_client_written_prefix(self):
        # The client sent "X-Forwarded-For: 6.6.6.6"; the proxy appended what it really saw.
        self.assertEqual(client_ip(request("6.6.6.6, 203.0.113.7")), "203.0.113.7")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_two_proxies_count_from_the_right(self):
        self.assertEqual(client_ip(request("6.6.6.6, 203.0.113.7, 10.0.0.2")), "203.0.113.7")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_short_chain_falls_back_to_remote_addr(self):
        self.assertEqual(client_ip(request("203.0.113.7")), PROXY)

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_missing_header_falls_back_to_remote_addr(self):
        self.assertEqual(client_ip(request()), PROXY)
