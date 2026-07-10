from pathlib import Path

import pytest

from app.core.config import Settings


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-secret",
        provider_mode="demo",
        upload_dir=tmp_path / "uploads",
    )
