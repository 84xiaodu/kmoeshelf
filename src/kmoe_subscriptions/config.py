from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="KMOE_",
        extra="ignore",
    )

    app_secret_key: SecretStr = Field(min_length=32)
    database_url: str = "sqlite+aiosqlite:////data/app.db"
    download_dir: Path = Path("/storage")
    cookie_secure: bool = False
    session_hours: int = Field(default=24 * 14, ge=1, le=24 * 90)
    bangumi_recommendations: bool = False
    bangumi_api_base_url: str = "https://api.bgm.tv"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
