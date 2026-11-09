"""Application settings from environment variables and the local .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
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
    jwt_secret_key: SecretStr | None = None
    access_token_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_days: int = Field(default=30, ge=1, le=365)
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: str = "lax"
    frontend_origins: list[str] = Field(default_factory=list)

    @field_validator("refresh_cookie_samesite")
    @classmethod
    def valid_samesite(cls, value: str) -> str:
        value = value.lower()
        if value not in {"lax", "strict", "none"}:
            raise ValueError("must be lax, strict, or none")
        return value

    @field_validator("frontend_origins")
    @classmethod
    def valid_origins(cls, values: list[str]) -> list[str]:
        from urllib.parse import urlsplit

        for origin in values:
            parsed = urlsplit(origin)
            try:
                _port = parsed.port
            except ValueError:
                raise ValueError(
                    "frontend origins must be exact http(s) origins"
                ) from None
            if (
                "*" in origin
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or origin != f"{parsed.scheme}://{parsed.netloc}"
            ):
                raise ValueError("frontend origins must be exact http(s) origins")
        return values

    @model_validator(mode="after")
    def secure_cookie_policy(self) -> Settings:
        if self.refresh_cookie_samesite == "none" and not self.refresh_cookie_secure:
            raise ValueError("SameSite=None requires a Secure refresh cookie")
        if (
            self.environment.lower() in {"production", "prod"}
            and not self.refresh_cookie_secure
        ):
            raise ValueError("production requires Secure refresh cookies")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (safe as a FastAPI dependency)."""
    return Settings()
