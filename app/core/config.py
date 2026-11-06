"""Application settings.

Read from ``TASKHUB_*`` environment variables. Kept dependency-free (no
pydantic-settings) so the skeleton only needs FastAPI, Uvicorn and Pydantic.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field

ENV_PREFIX = "TASKHUB_"


def _env(name: str, default: str) -> str:
    return os.getenv(f"{ENV_PREFIX}{name.upper()}", default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(f"{ENV_PREFIX}{name.upper()}")
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(f"{ENV_PREFIX}{name.upper()}")
    if raw is None:
        return default
    return int(raw)


class Settings(BaseModel):
    """Runtime configuration, overridable through ``TASKHUB_*`` vars."""

    app_name: str = "TaskHub"
    version: str = "0.1.0"
    environment: str = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_name=_env("app_name", "TaskHub"),
            version=_env("version", "0.1.0"),
            environment=_env("environment", "local"),
            debug=_env_bool("debug", False),
            api_v1_prefix=_env("api_v1_prefix", "/api/v1"),
            host=_env("host", "127.0.0.1"),
            port=_env_int("port", 8000),
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (safe as a FastAPI dependency)."""
    return Settings.from_env()
