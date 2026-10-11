import pytest


@pytest.mark.django_db
def test_health_is_public_and_reports_the_database(client):
    response = client.get("/api/health/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": True}
