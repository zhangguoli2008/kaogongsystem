import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import create_app
from app.models.base import Base
from app.models.review import UserSettings
from app.models.user import User  # noqa: F401


@pytest.fixture
def client(test_settings):
    settings = test_settings.model_copy(
        update={"jwt_secret": "test-session-secret-at-least-32-bytes"}
    )
    engine = create_async_engine(settings.database_url)

    async def create_tables():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())
    with TestClient(create_app(settings)) as test_client:
        yield test_client
    asyncio.run(engine.dispose())


def test_register_sets_http_only_cookie(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "learner@example.com", "password": "strong-pass-123"},
    )
    assert response.status_code == 201
    assert response.json()["email"] == "learner@example.com"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


def test_duplicate_email_is_rejected(client):
    payload = {"email": "same@example.com", "password": "strong-pass-123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "email_already_registered"


def test_registration_normalizes_email_and_creates_default_settings(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "  Learner@Example.COM ", "password": "strong-pass-123"},
    )
    assert response.status_code == 201
    assert response.json()["email"] == "learner@example.com"

    async def get_daily_review_limit():
        async with client.app.state.session_factory() as session:
            return await session.scalar(select(UserSettings.daily_review_limit))

    assert asyncio.run(get_daily_review_limit()) == 20


def test_login_sets_session_and_me_returns_current_user(client):
    payload = {"email": "login@example.com", "password": "strong-pass-123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    client.cookies.clear()

    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]

    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "login@example.com"


def test_invalid_login_uses_standard_error_shape(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "strong-pass-123"},
    )
    assert response.status_code == 401
    assert response.json().keys() == {
        "code",
        "message",
        "field_errors",
        "request_id",
    }
    assert response.json()["code"] == "invalid_credentials"


def test_invalid_session_token_is_rejected(client):
    client.cookies.set("kaogong_session", "not-a-token")
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_session"


def test_logout_clears_session_cookie(client):
    payload = {"email": "logout@example.com", "password": "strong-pass-123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201

    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert "kaogong_session=" in response.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").status_code == 401


def test_auth_rate_limit_allows_ten_attempts_per_ip(client):
    payload = {"email": "missing@example.com", "password": "strong-pass-123"}
    for _ in range(10):
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401

    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 429
    assert response.json()["code"] == "auth_rate_limit_exceeded"


def test_validation_errors_use_standard_error_shape(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "invalid", "password": "short"},
        headers={"X-Request-ID": "test-request-id"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["request_id"] == "test-request-id"
    assert response.json()["field_errors"] == {
        "email": ["Value error, must be a valid email address"],
        "password": ["String should have at least 8 characters"],
    }
