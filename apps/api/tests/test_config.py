import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import create_session_factory, normalize_database_url
from app.main import create_app
from app.services.ocr_contract import (
    ACTION,
    API_NAME,
    API_VERSION,
    ENABLE_IMAGE_CROP,
    ENABLE_ONLY_DETECT_BORDER,
    ENDPOINT,
    USE_NEW_MODEL,
)


API_ROOT = Path(__file__).parents[1]


def production_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql://user:pass@postgres.railway.internal:5432/kaogong",
        "jwt_secret": "a" * 64,
        "internal_proxy_secret": "b" * 64,
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


def test_ocr_configuration_defaults_are_server_controlled() -> None:
    settings = Settings()

    assert settings.ocr_provider == "mock"
    assert settings.tencentcloud_secret_id is None
    assert settings.tencentcloud_secret_key is None
    assert settings.tencentcloud_region == ""
    assert settings.tencentcloud_ocr_timeout_seconds == 30
    assert settings.tencentcloud_ocr_max_concurrency == 2
    assert settings.tencentcloud_ocr_queue_timeout_seconds == 5
    assert settings.tencentcloud_ocr_max_retries == 2
    assert settings.ocr_processing_lease_seconds == 180
    assert settings.ocr_rate_limit_per_minute == 5
    assert settings.ocr_rate_limit_per_hour == 50


def test_upload_resource_limit_defaults_are_server_controlled() -> None:
    settings = Settings()

    assert settings.upload_max_concurrency == 2
    assert settings.upload_queue_timeout_seconds == 5.0
    assert settings.upload_rate_limit_per_minute == 10
    assert settings.upload_rate_limit_per_hour == 100
    assert settings.max_upload_bytes == 10 * 1024 * 1024


UPLOAD_NUMERIC_BOUNDARIES = [
    ("upload_max_concurrency", 1, 10),
    ("upload_queue_timeout_seconds", 0.1, 60.0),
    ("upload_rate_limit_per_minute", 1, 60),
    ("upload_rate_limit_per_hour", 1, 1000),
    ("max_upload_bytes", 1024 * 1024, 10 * 1024 * 1024),
]


@pytest.mark.parametrize(
    ("field_name", "lower", "upper"),
    UPLOAD_NUMERIC_BOUNDARIES,
)
def test_upload_numeric_configuration_accepts_documented_boundaries(
    field_name: str,
    lower: int | float,
    upper: int | float,
) -> None:
    lower_overrides: dict[str, int | float] = {field_name: lower}
    if field_name == "upload_rate_limit_per_hour":
        lower_overrides["upload_rate_limit_per_minute"] = 1
    lower_settings = Settings(_env_file=None, **lower_overrides)
    upper_settings = Settings(_env_file=None, **{field_name: upper})

    assert getattr(lower_settings, field_name) == lower
    assert getattr(upper_settings, field_name) == upper


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        *[(field_name, 0) for field_name, _, _ in UPLOAD_NUMERIC_BOUNDARIES],
        *[
            (field_name, upper + 1)
            for field_name, _, upper in UPLOAD_NUMERIC_BOUNDARIES
        ],
        ("upload_queue_timeout_seconds", 0.09),
        ("max_upload_bytes", 1024 * 1024 - 1),
    ],
)
def test_upload_numeric_configuration_rejects_unsafe_values(
    field_name: str,
    invalid_value: int | float,
) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field_name: invalid_value})


def test_upload_minute_rate_limit_cannot_exceed_hour_limit() -> None:
    with pytest.raises(ValueError, match="UPLOAD_RATE_LIMIT_PER_MINUTE"):
        Settings(
            _env_file=None,
            upload_rate_limit_per_minute=11,
            upload_rate_limit_per_hour=10,
        )


OCR_NUMERIC_BOUNDARIES = [
    ("tencentcloud_ocr_timeout_seconds", 1, 60),
    ("tencentcloud_ocr_max_concurrency", 1, 10),
    ("tencentcloud_ocr_queue_timeout_seconds", 1, 60),
    ("tencentcloud_ocr_max_retries", 0, 2),
    ("ocr_processing_lease_seconds", 60, 3600),
    ("ocr_rate_limit_per_minute", 1, 60),
    ("ocr_rate_limit_per_hour", 1, 1000),
    ("ocr_corrected_image_max_bytes", 1, 10 * 1024 * 1024),
    ("ocr_corrected_images_max_total_bytes", 1, 10 * 1024 * 1024),
    ("ocr_crop_max_artifacts", 1, 100),
    ("ocr_crop_max_total_png_bytes", 1, 10 * 1024 * 1024),
]


@pytest.mark.parametrize(
    ("field_name", "lower", "upper"),
    OCR_NUMERIC_BOUNDARIES,
)
def test_ocr_numeric_configuration_accepts_documented_boundaries(
    field_name: str,
    lower: int,
    upper: int,
) -> None:
    lower_overrides = {field_name: lower}
    upper_overrides = {field_name: upper}
    if field_name == "ocr_processing_lease_seconds":
        lower_overrides.update(
            {
                "tencentcloud_ocr_timeout_seconds": 1,
                "tencentcloud_ocr_queue_timeout_seconds": 1,
                "tencentcloud_ocr_max_retries": 0,
            }
        )
    elif field_name == "tencentcloud_ocr_timeout_seconds":
        upper_overrides["ocr_processing_lease_seconds"] = 300
    elif field_name == "ocr_rate_limit_per_minute":
        upper_overrides["ocr_rate_limit_per_hour"] = upper
    elif field_name == "ocr_rate_limit_per_hour":
        lower_overrides["ocr_rate_limit_per_minute"] = lower

    lower_settings = Settings(_env_file=None, **lower_overrides)
    upper_settings = Settings(_env_file=None, **upper_overrides)

    assert getattr(lower_settings, field_name) == lower
    assert getattr(upper_settings, field_name) == upper


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        *[
            (field_name, 0)
            for field_name, lower, _ in OCR_NUMERIC_BOUNDARIES
            if lower > 0
        ],
        ("tencentcloud_ocr_timeout_seconds", -1),
        ("tencentcloud_ocr_max_retries", -1),
        *[(field_name, upper + 1) for field_name, _, upper in OCR_NUMERIC_BOUNDARIES],
    ],
)
def test_ocr_numeric_configuration_rejects_unsafe_values(
    field_name: str,
    invalid_value: int,
) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field_name: invalid_value})


def test_ocr_processing_lease_must_cover_the_longest_normal_processing_window() -> None:
    required_lease = 5 + 30 * (2 + 1) + 30

    settings = Settings(
        _env_file=None,
        ocr_processing_lease_seconds=required_lease,
    )
    assert settings.ocr_processing_lease_seconds == required_lease

    with pytest.raises(ValueError, match="OCR_PROCESSING_LEASE_SECONDS"):
        Settings(
            _env_file=None,
            ocr_processing_lease_seconds=required_lease - 1,
        )


def test_ocr_minute_rate_limit_cannot_exceed_hour_limit() -> None:
    with pytest.raises(ValueError, match="OCR_RATE_LIMIT_PER_MINUTE"):
        Settings(
            _env_file=None,
            ocr_rate_limit_per_minute=11,
            ocr_rate_limit_per_hour=10,
        )


def test_tencent_ocr_invocation_contract_is_fixed() -> None:
    assert API_NAME == "QuestionSplitOCR"
    assert ACTION == "QuestionSplitOCR"
    assert API_VERSION == "2018-11-19"
    assert ENDPOINT == "ocr.tencentcloudapi.com"
    assert USE_NEW_MODEL is False
    assert ENABLE_IMAGE_CROP is True
    assert ENABLE_ONLY_DETECT_BORDER is False


def test_fixed_tencent_ocr_contract_ignores_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TENCENTCLOUD_OCR_ENDPOINT", "attacker.example")
    monkeypatch.setenv("TENCENTCLOUD_OCR_USE_NEW_MODEL", "true")
    monkeypatch.setenv("TENCENTCLOUD_OCR_ENABLE_IMAGE_CROP", "false")

    settings = Settings(_env_file=None)
    fixed_field_names = {
        "tencentcloud_ocr_endpoint",
        "tencentcloud_ocr_use_new_model",
        "tencentcloud_ocr_enable_image_crop",
    }

    assert fixed_field_names.isdisjoint(Settings.model_fields)
    assert fixed_field_names.isdisjoint(settings.model_dump())


def test_missing_tencent_credentials_do_not_prevent_startup(tmp_path: Path) -> None:
    settings = production_settings(
        tmp_path,
        ocr_provider="tencent_question_split",
        tencentcloud_secret_id=None,
        tencentcloud_secret_key=None,
    )

    app = create_app(settings)

    assert app.state.settings.ocr_provider == "tencent_question_split"


def test_ocr_provider_is_independent_from_analysis_provider_mode() -> None:
    settings = Settings(
        provider_mode="demo",
        openai_api_key=None,
        ocr_provider="tencent_question_split",
    )

    assert settings.effective_provider_mode == "demo"
    assert settings.ocr_provider == "tencent_question_split"


def test_explicit_demo_production_configuration_is_accepted(tmp_path: Path) -> None:
    app = create_app(production_settings(tmp_path))
    assert app.state.settings.effective_provider_mode == "demo"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"internal_proxy_secret": None}, "INTERNAL_PROXY_SECRET"),
        ({"internal_proxy_secret": "short"}, "INTERNAL_PROXY_SECRET"),
        ({"internal_proxy_secret": "A" * 64}, "INTERNAL_PROXY_SECRET"),
        ({"internal_proxy_secret": "G" * 64}, "INTERNAL_PROXY_SECRET"),
        ({"internal_proxy_secret": "b" * 64 + "\n"}, "INTERNAL_PROXY_SECRET"),
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
    "origin",
    [
        "https://example.com/",
        "HTTPS://EXAMPLE.COM",
        "https://example.com:443",
    ],
)
def test_production_configuration_rejects_noncanonical_browser_origins(
    tmp_path: Path, origin: str
) -> None:
    with pytest.raises(ValueError, match="ALLOWED_ORIGINS"):
        create_app(production_settings(tmp_path, allowed_origins=[origin]))


def test_canonical_production_origin_matches_cors_exactly(tmp_path: Path) -> None:
    origin = "https://example.com"

    with TestClient(
        create_app(production_settings(tmp_path, allowed_origins=[origin]))
    ) as client:
        response = client.get(
            "/health",
            headers={"Origin": origin, "Host": "healthcheck.railway.app"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


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
    source = "postgres://us%40er:p%40ss%25word@postgres.railway.internal:5432/kaogong"
    expected = (
        "postgresql+psycopg://us%40er:p%40ss%25word@"
        "postgres.railway.internal:5432/kaogong"
    )

    session_factory = create_session_factory(source)

    engine = session_factory.kw["bind"]
    assert engine.url.render_as_string(hide_password=False) == expected


def test_alembic_accepts_url_encoded_credentials() -> None:
    database_url = (
        "postgresql://us%40er:p%40ss%25word@postgres.railway.internal:5432/kaogong"
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
