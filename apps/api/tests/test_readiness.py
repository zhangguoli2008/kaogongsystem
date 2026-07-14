from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_ready_checks_database_and_upload_storage(test_settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "provider_mode": "demo"}
    assert list(test_settings.upload_dir.glob(".readiness-*")) == []


def test_ready_returns_503_when_database_is_unavailable(
    test_settings, tmp_path: Path
) -> None:
    settings = test_settings.model_copy(
        update={
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'missing' / 'db.sqlite'}"
        }
    )

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_ready_returns_503_when_upload_path_is_not_a_directory(
    test_settings, tmp_path: Path
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    settings = test_settings.model_copy(update={"upload_dir": blocked})

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_explicit_allowed_hosts_rejects_unknown_host_with_cors(test_settings) -> None:
    settings = test_settings.model_copy(
        update={"allowed_hosts": ["api.railway.internal", "healthcheck.railway.app"]}
    )
    allowed_origin = settings.allowed_origins[0]

    with TestClient(create_app(settings)) as client:
        rejected = client.get(
            "/health",
            headers={"Host": "evil.example", "Origin": allowed_origin},
        )
        accepted = client.get("/health", headers={"Host": "healthcheck.railway.app"})

    assert rejected.status_code == 400
    assert rejected.headers.get("Access-Control-Allow-Origin") == allowed_origin
    assert rejected.headers.get("Access-Control-Allow-Credentials") == "true"
    assert accepted.status_code == 200
