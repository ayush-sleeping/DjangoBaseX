"""POST /api/public/csp-report/ (FRONTEND_PLATFORM § 18, BUILD_ORDER 8.5)."""

import json
import logging

import pytest
from django.core.cache import cache

from core.views import CSP_REPORT_MAX_BYTES, CspReportThrottle

URL = "/api/public/csp-report/"
LEGACY = {
    "csp-report": {
        "document-uri": "https://app.example.test/users/42?token=SECRET&x=1",
        "effective-directive": "script-src-elem",
        "blocked-uri": "https://cdn.evil.test/path/a.js?key=SECRET2",
        "disposition": "report",
        "script-sample": "SAMPLESECRET",
    }
}
REPORTING_API = [
    {
        "type": "csp-violation",
        "url": "https://app.example.test/users/42?token=SECRET",
        "body": {
            "documentURL": "https://app.example.test/users/42?token=SECRET&x=1",
            "effectiveDirective": "img-src",
            "blockedURL": "https://img.evil.test/p.png?key=SECRET2",
            "disposition": "enforce",
        },
    }
]


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def _post(client, body, content_type="application/csp-report"):
    data = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return client.post(URL, data=data, content_type=content_type)


def _records(caplog):
    return [r for r in caplog.records if r.name == "core.csp"]


def test_a_legacy_report_is_204_and_logs_origin_and_path_only(client, caplog):
    with caplog.at_level(logging.WARNING, logger="core.csp"):
        assert _post(client, LEGACY).status_code == 204
    (record,) = _records(caplog)
    assert record.csp_directive == "script-src-elem"
    assert record.csp_blocked == "https://cdn.evil.test"
    assert record.csp_page == "/users/42"
    everything = caplog.text + json.dumps(record.__dict__, default=str)
    for leaked in ("SECRET", "SECRET2", "SAMPLESECRET", "token=", "key=", "?x=1"):
        assert leaked not in everything


def test_a_reporting_api_body_is_204_and_logs_origin_and_path_only(client, caplog):
    with caplog.at_level(logging.WARNING, logger="core.csp"):
        assert _post(client, REPORTING_API, "application/reports+json").status_code == 204
    (record,) = _records(caplog)
    assert (record.csp_directive, record.csp_blocked, record.csp_page) == (
        "img-src",
        "https://img.evil.test",
        "/users/42",
    )
    assert "SECRET" not in caplog.text


def test_an_oversized_body_is_413_and_nothing_is_logged(client, caplog):
    body = json.dumps({"csp-report": {"blocked-uri": "x" * (CSP_REPORT_MAX_BYTES + 1)}})
    with caplog.at_level(logging.WARNING, logger="core.csp"):
        assert _post(client, body).status_code == 413
    assert not _records(caplog)


@pytest.mark.parametrize("garbage", [b"not json", b"\xff\xfe", b"", b"[1,2]", b'{"csp-report": 3}'])
def test_garbage_is_204_and_logs_nothing(client, caplog, garbage):
    with caplog.at_level(logging.WARNING, logger="core.csp"):
        assert _post(client, garbage).status_code == 204
    assert not _records(caplog)


def test_it_is_throttled_per_address(client, monkeypatch):
    monkeypatch.setattr(CspReportThrottle, "rate", "3/min")
    statuses = [_post(client, LEGACY).status_code for _ in range(5)]
    assert statuses == [204, 204, 204, 429, 429]
