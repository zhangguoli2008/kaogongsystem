import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.database import create_session_factory, normalize_database_url
from app.main import create_app


API_ROOT = Path(__file__).parents[1]


def production_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql://user:pass@postgres.railway.internal:5432/kaogong",
        "jwt_secret": "a" * 64,
        "provider_mode": "demo",
        "openai_api_key": None,
        "upload_dir": Path("/data/uploads"),
        "allowed_origins": ["https://web-production.example.up.railway.app"],
        "allowed_hosts": [
            "api-production.example.up.railway.app",
            "api.railway.internal",
            "healthcheck.railway.app",
        ],
        "cookie_secure": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_explicit_demo_production_configuration_is_accepted(tmp_path: Path) -> None:
    app = create_app(production_settings(tmp_path))
    assert app.state.settings.effective_provider_mode == "demo"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"provider_mode": "auto"}, "PROVIDER_MODE"),
        ({"openai_api_key": "must-not-be-stored"}, "OPENAI_API_KEY"),
        ({"database_url": "sqlite+aiosqlite:///tmp/prod.db"}, "DATABASE_URL"),
        ({"database_url": "postgresql://user:pass@localhost/db"}, "DATABASE_URL"),
        ({"allowed_origins": ["http://localhost:3000"]}, "ALLOWED_ORIGINS"),
        ({"allowed_hosts": ["*"]}, "ALLOWED_HOSTS"),
        ({"upload_dir": Path("/tmp/uploads")}, "UPLOAD_DIR"),
    ],
)
def test_production_configuration_rejects_unsafe_values(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        create_app(production_settings(tmp_path, **overrides))


@pytest.mark.parametrize(
    "host",
    [
        "LOCALHOST",
        "LOCALHOST.",
        "127.0.0.2",
        "127.255.255.254",
        "[::1]",
        "[::ffff:127.0.0.1]",
    ],
)
def test_production_configuration_rejects_loopback_database_hosts(
    tmp_path: Path, host: str
) -> None:
    database_url = f"postgresql://user:pass@{host}/kaogong"

    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_app(production_settings(tmp_path, database_url=database_url))


def test_production_configuration_reports_malformed_database_url(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_app(
            production_settings(tmp_path, database_url="not a valid database URL")
        )


@pytest.mark.parametrize(
    "origin",
    [
        "https://[::1]",
        "https://127.0.0.2",
        "https://user@example.com",
        "https://example.com/path",
        "https://example.com?query=value",
        "https://example.com#fragment",
        "https://example.com?",
        "https://example.com#",
        "https://example.com:invalid",
        "https://[::1",
    ],
)
def test_production_configuration_rejects_non_origin_urls(
    tmp_path: Path, origin: str
) -> None:
    with pytest.raises(ValueError, match="ALLOWED_ORIGINS"):
        create_app(production_settings(tmp_path, allowed_origins=[origin]))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "postgresql://user:pass@postgres.railway.internal:5432/kaogong",
            "postgresql+psycopg://user:pass@postgres.railway.internal:5432/kaogong",
        ),
        (
            "postgres://user:pass@postgres.railway.internal:5432/kaogong",
            "postgresql+psycopg://user:pass@postgres.railway.internal:5432/kaogong",
        ),
        (
            "postgresql+psycopg://user:pass@postgres.railway.internal:5432/kaogong",
            "postgresql+psycopg://user:pass@postgres.railway.internal:5432/kaogong",
        ),
        ("sqlite+aiosqlite:///tmp/test.db", "sqlite+aiosqlite:///tmp/test.db"),
        (
            "postgresql://us%40er:p%40ss%25word@postgres.railway.internal:5432/kaogong",
            "postgresql+psycopg://us%40er:p%40ss%25word@postgres.railway.internal:5432/kaogong",
        ),
    ],
)
def test_database_url_normalization(source: str, expected: str) -> None:
    assert normalize_database_url(source) == expected


def test_session_factory_normalizes_railway_database_url() -> None:
    source = (
        "postgres://us%40er:p%40ss%25word@"
        "postgres.railway.internal:5432/kaogong"
    )
    expected = (
        "postgresql+psycopg://us%40er:p%40ss%25word@"
        "postgres.railway.internal:5432/kaogong"
    )

    session_factory = create_session_factory(source)

    engine = session_factory.kw["bind"]
    assert engine.url.render_as_string(hide_password=False) == expected


def test_alembic_accepts_url_encoded_credentials() -> None:
    database_url = (
        "postgresql://us%40er:p%40ss%25word@"
        "postgres.railway.internal:5432/kaogong"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=API_ROOT,
        env={
            **os.environ,
            "DATABASE_URL": database_url,
            "PYTHONPATH": str(API_ROOT),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
