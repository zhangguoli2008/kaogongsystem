from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


AppEnvironment = Literal["development", "test", "production"]
DEFAULT_DATABASE_URL = "postgresql+psycopg://kaogong:kaogong@db:5432/kaogong"
DEFAULT_JWT_SECRET = "development-secret-change-in-production"


class Settings(BaseSettings):
    app_env: AppEnvironment = "development"
    database_url: str = DEFAULT_DATABASE_URL
    jwt_secret: str = DEFAULT_JWT_SECRET
    provider_mode: Literal["auto", "live", "demo"] = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
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
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true")
        if self.provider_mode == "auto":
            errors.append("PROVIDER_MODE must be explicit in production")
        if self.provider_mode == "demo" and self.openai_api_key:
            errors.append("OPENAI_API_KEY must be unset in demo production")

        try:
            database = make_url(self.database_url)
            database_is_remote_postgres = (
                database.get_backend_name() in {"postgres", "postgresql"}
                and database.host not in {None, "localhost", "127.0.0.1", "db"}
            )
        except ValueError:
            database_is_remote_postgres = False
        if not database_is_remote_postgres:
            errors.append("DATABASE_URL must use remote PostgreSQL")

        if len(self.allowed_origins) != 1 or any(
            urlsplit(origin).scheme != "https"
            or urlsplit(origin).hostname in {None, "localhost", "127.0.0.1"}
            for origin in self.allowed_origins
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
