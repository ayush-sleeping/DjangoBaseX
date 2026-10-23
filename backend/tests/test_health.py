"""Health in three rungs (OBSERVABILITY.md § 6; BUILD_ORDER 6.2)."""

from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.observability import health
from core.registry import HealthCheck
from rbac import services
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db
COMPONENTS = "/api/health/components/"


def client_with(*codes) -> APIClient:
    """A signed-in principal holding exactly these codes (the settings API test's pattern)."""
    user = UserFactory()
    if codes:
        slug = f"probe-{user.pk}"
        services.assign_role(
            actor=None,
            user=user,
            role=services.create_role(
                actor=None, name=slug, slug=slug, permission_codes=list(codes)
            ),
        )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def boom():
    raise RuntimeError("connection to server at db.internal:5432, user app refused")


# --- Live: no I/O -------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/health/", "/api/health/live/"])
def test_live_does_no_io(client, path):
    with (
        mock.patch("django.db.backends.utils.CursorWrapper.execute", side_effect=boom),
        mock.patch("django.core.cache.cache.set", side_effect=boom),
    ):
        response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response["Cache-Control"] == "no-store"


def test_live_carries_no_product_identity(client, settings):
    settings.PRODUCT_NAME = "Acme Portal"
    assert "Acme" not in client.get("/api/health/live/").content.decode()


# --- Ready: database + cache, fixed tokens ------------------------------------------------------


def test_ready_is_200_when_both_dependencies_answer(client):
    response = client.get("/api/health/ready/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_503_with_fixed_token_when_db_down(client):
    with mock.patch.object(health, "probe_database", side_effect=boom):
        response = client.get("/api/health/ready/")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "failed": ["database"]}
    assert "db.internal" not in response.content.decode()


def test_ready_503_when_the_cache_round_trip_fails(client):
    with mock.patch.object(health, "probe_cache", return_value=False):
        response = client.get("/api/health/ready/")
    assert response.status_code == 503
    assert response.json()["failed"] == ["cache"]


def test_ready_answers_with_unknown_host_header(client):
    response = client.get("/api/health/ready/", HTTP_HOST="not-in-allowed-hosts.test")
    assert response.status_code == 200


def test_ready_exempt_from_throttle(client, settings):
    rates = {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "anon": "2/min"}
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates}
    for _ in range(10):
        assert client.get("/api/health/ready/").status_code == 200


def test_public_rungs_are_routed_and_named():
    assert reverse("core:health") == "/api/health/"
    assert reverse("core:health-live") == "/api/health/live/"
    assert reverse("core:health-ready") == "/api/health/ready/"


# --- Components: permission-gated, never 500 ----------------------------------------------------


@pytest.fixture
def monitor():
    """A principal that holds core.health.view and nothing else."""
    return client_with("core.health.view")


def test_components_requires_the_permission():
    assert APIClient().get(COMPONENTS).status_code == 401
    assert client_with().get(COMPONENTS).status_code == 403


def test_monitoring_principal_reads_components_and_nothing_else(monitor):
    response = monitor.get(COMPONENTS)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["release"]
    assert body["components"]["database"] == {
        "status": "ok",
        "detail": "",
        "ms": mock.ANY,
        "critical": True,
    }
    assert body["components"]["migrations"]["status"] == "ok"
    assert monitor.get("/api/auth/me/").status_code == 200  # signed in...
    assert monitor.get("/api/users/").status_code == 403  # ...and that is all it may do


def test_a_probe_that_raises_is_reported_not_propagated():
    result = health.run_probe(HealthCheck("search", "Search", boom, critical=False))
    assert result.status == "degraded"
    assert result.detail.startswith("RuntimeError: ")
    assert "db.internal" in result.detail  # scrubbed of secrets, not of facts


def test_a_probe_that_hangs_times_out(settings):
    import time

    settings.HEALTH_PROBE_TIMEOUT_SECONDS = 0.05
    result = health.run_probe(HealthCheck("slow", "Slow", lambda: time.sleep(1) or True))
    assert result.status == "down"
    assert "timed out" in result.detail


def test_noncritical_failure_cannot_make_install_down(monitor):
    with mock.patch.object(
        health.registry.health,
        "checks",
        return_value=(HealthCheck("search", "Search", boom, critical=False),),
    ):
        response = monitor.get(COMPONENTS)
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["components"]["search"]["status"] == "degraded"


def test_degraded_is_200_and_down_is_503(monitor):
    with mock.patch.object(health, "probe_cache", side_effect=boom):
        response = monitor.get(COMPONENTS)
    assert response.status_code == 503
    assert response.json()["status"] == "down"
    assert response.json()["components"]["cache"]["status"] == "down"


def test_components_never_500s(monitor):
    with mock.patch.object(health, "run_probe", side_effect=boom):
        response = monitor.get(COMPONENTS)
    assert response.status_code == 503
    assert response.json()["status"] == "down"
