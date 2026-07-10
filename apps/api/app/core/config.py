from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://kaogong:kaogong@db:5432/kaogong"
    jwt_secret: str = "development-secret-change-in-production"
    provider_mode: Literal["auto", "live", "demo"] = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.5"
    upload_dir: Path = Path("/data/uploads")
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_origins: list[str] = ["http://localhost:3000"]
    cookie_secure: bool = False
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    @property
    def effective_provider_mode(self) -> Literal["live", "demo"]:
        if self.provider_mode == "live" and not self.openai_api_key:
            raise ValueError("PROVIDER_MODE=live requires OPENAI_API_KEY")
        if self.provider_mode == "demo":
            return "demo"
        return "live" if self.openai_api_key else "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
