import re
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


AppEnvironment = Literal["development", "test", "production"]
DEFAULT_DATABASE_URL = "postgresql+psycopg://kaogong:kaogong@db:5432/kaogong"
DEFAULT_JWT_SECRET = "development-secret-change-in-production"


def _is_loopback_host(host: str) -> bool:
    normalized_host = host.rstrip(".").casefold()
    if normalized_host == "localhost":
        return True
    try:
        return ip_address(normalized_host).is_loopback
    except ValueError:
        return False


def _is_valid_production_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname
    if hostname is None:
        return False
    canonical_host = f"[{hostname}]" if ":" in hostname else hostname
    canonical_port = "" if port in {None, 443} else f":{port}"
    canonical_origin = f"https://{canonical_host}{canonical_port}"
    return (
        origin == canonical_origin
        and parsed.scheme == "https"
        and not _is_loopback_host(hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and "?" not in origin
        and "#" not in origin
    )


class Settings(BaseSettings):
    app_env: AppEnvironment = "development"
    database_url: str = DEFAULT_DATABASE_URL
    jwt_secret: str = DEFAULT_JWT_SECRET
    internal_proxy_secret: str | None = None
    provider_mode: Literal["auto", "live", "demo"] = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
    ocr_provider: Literal["mock", "tencent_question_split"] = "mock"
    tencentcloud_secret_id: str | None = None
    tencentcloud_secret_key: str | None = None
    tencentcloud_region: str = ""
    tencentcloud_ocr_endpoint: str = "ocr.tencentcloudapi.com"
    tencentcloud_ocr_timeout_seconds: int = 30
    tencentcloud_ocr_max_concurrency: int = 2
    tencentcloud_ocr_queue_timeout_seconds: int = 5
    tencentcloud_ocr_max_retries: int = 2
    ocr_rate_limit_per_minute: int = 5
    ocr_rate_limit_per_hour: int = 50
    tencentcloud_ocr_use_new_model: bool = False
    tencentcloud_ocr_enable_image_crop: bool = True
    upload_dir: Path = Path("/data/uploads")
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_origins: list[str] = ["http://localhost:3000"]
    allowed_hosts: list[str] = ["*"]
    cookie_secure: bool = False
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    @property
    def effective_provider_mode(self) -> Literal["live", "demo"]:
        if self.provider_mode == "live" and not self.openai_api_key:
            raise ValueError("PROVIDER_MODE=live requires OPENAI_API_KEY")
        if self.provider_mode == "demo":
            return "demo"
        return "live" if self.openai_api_key else "demo"

    def validate_for_startup(self) -> None:
        _ = self.effective_provider_mode
        if self.app_env != "production":
            return

        errors: list[str] = []
        if len(self.jwt_secret.encode("utf-8")) < 32 or self.jwt_secret == DEFAULT_JWT_SECRET:
            errors.append("JWT_SECRET must be a non-default value of at least 32 bytes")
        if self.internal_proxy_secret is None or not re.fullmatch(
            r"[0-9a-f]{64}", self.internal_proxy_secret
        ):
            errors.append(
                "INTERNAL_PROXY_SECRET must be a 64-character lowercase hex value"
            )
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true")
        if self.provider_mode == "auto":
            errors.append("PROVIDER_MODE must be explicit in production")
        if self.provider_mode == "demo" and self.openai_api_key:
            errors.append("OPENAI_API_KEY must be unset in demo production")

        try:
            database = make_url(self.database_url)
            database_host = database.host
            database_is_remote_postgres = (
                database.get_backend_name() in {"postgres", "postgresql"}
                and database_host is not None
                and database_host.rstrip(".").casefold() != "db"
                and not _is_loopback_host(database_host)
            )
        except (ArgumentError, ValueError):
            database_is_remote_postgres = False
        if not database_is_remote_postgres:
            errors.append("DATABASE_URL must use remote PostgreSQL")

        if len(self.allowed_origins) != 1 or any(
            not _is_valid_production_origin(origin) for origin in self.allowed_origins
        ):
            errors.append("ALLOWED_ORIGINS must contain only HTTPS non-local origins")
        if (
            not self.allowed_hosts
            or "*" in self.allowed_hosts
            or "healthcheck.railway.app" not in self.allowed_hosts
            or "api.railway.internal" not in self.allowed_hosts
        ):
            errors.append("ALLOWED_HOSTS must include API private and healthcheck hosts")
        if self.upload_dir != Path("/data/uploads"):
            errors.append("UPLOAD_DIR must be /data/uploads")

        if errors:
            raise ValueError("Invalid production configuration: " + "; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()
