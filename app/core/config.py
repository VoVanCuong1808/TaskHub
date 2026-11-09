"""Application settings from environment variables and the local .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "TASKHUB_"


class Settings(BaseSettings):
    """Runtime configuration, overridable through ``TASKHUB_*`` vars."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TaskHub"
    version: str = "0.1.0"
    environment: str = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+asyncpg://postgres:taskhub@localhost:5432/taskhub"
    database_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (safe as a FastAPI dependency)."""
    return Settings()
