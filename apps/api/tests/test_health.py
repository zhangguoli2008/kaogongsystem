from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_demo_mode(test_settings):
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider_mode": "demo"}
