from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import create_app


def test_health_reports_demo_mode(test_settings):
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider_mode": "demo"}


def test_health_does_not_require_database_connection(
    test_settings, tmp_path: Path
) -> None:
    settings = test_settings.model_copy(
        update={
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'missing' / 'db.sqlite'}"
        }
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider_mode": "demo"}


def test_live_provider_without_api_key_fails_at_startup(test_settings):
    live_without_key = test_settings.model_copy(
        update={"provider_mode": "live", "openai_api_key": None}
    )

    with pytest.raises(ValueError, match="PROVIDER_MODE=live requires OPENAI_API_KEY"):
        create_app(live_without_key)
