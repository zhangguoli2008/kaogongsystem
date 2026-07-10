import asyncio
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.main import create_app
from app.models.base import Base


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-secret",
        provider_mode="demo",
        upload_dir=tmp_path / "uploads",
    )


@contextmanager
def _client_for(settings: Settings):
    engine = create_async_engine(settings.database_url)

    async def create_tables():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())
    try:
        with TestClient(create_app(settings)) as test_client:
            yield test_client
    finally:
        asyncio.run(engine.dispose())


@pytest.fixture
def client(test_settings: Settings):
    settings = test_settings.model_copy(
        update={"jwt_secret": "test-session-secret-at-least-32-bytes"}
    )
    with _client_for(settings) as test_client:
        yield test_client
