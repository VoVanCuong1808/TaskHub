"""Application settings from environment variables and the local .env file."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    EmailStr,
    Field,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    SMTP_DEFAULT_PORT,
    SMTP_MAX_TIMEOUT_SECONDS,
    SMTP_TIMEOUT_SECONDS,
)

ENV_PREFIX = "TASKHUB_"


class Settings(BaseSettings):
    """Runtime configuration, overridable through ``TASKHUB_*`` vars."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
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
    redis_url: RedisDsn | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int = Field(default=SMTP_DEFAULT_PORT, ge=1, le=65535)
    smtp_from_email: EmailStr = "no-reply@example.com"
    smtp_username: str | None = Field(default=None, min_length=1, max_length=320)
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    smtp_timeout_seconds: float = Field(
        default=SMTP_TIMEOUT_SECONDS, gt=0, le=SMTP_MAX_TIMEOUT_SECONDS
    )
    jwt_secret_key: SecretStr | None = None
    access_token_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_days: int = Field(default=30, ge=1, le=365)
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    frontend_origins: list[str] = Field(default_factory=list)

    @field_validator("redis_url", mode="before")
    @classmethod
    def empty_redis_url_disables_cache(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("smtp_host", mode="before")
    @classmethod
    def normalize_smtp_host(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        host = value.strip()
        if not host:
            return None
        if any(
            character.isspace() or ord(character) < 33 or character in "/@?#"
            for character in host
        ):
            raise ValueError("SMTP host must be a hostname or address")
        return host

    @field_validator("smtp_username", mode="before")
    @classmethod
    def normalize_smtp_username(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("smtp_password", mode="before")
    @classmethod
    def blank_smtp_password_disables_auth(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("refresh_cookie_samesite", mode="before")
    @classmethod
    def valid_samesite(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.lower()
        if value not in {"lax", "strict", "none"}:
            raise ValueError("must be lax, strict, or none")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def valid_jwt_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("must contain at least 32 bytes")
        return value

    @field_validator("frontend_origins")
    @classmethod
    def valid_origins(cls, values: list[str]) -> list[str]:
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
        if (self.smtp_username is None) != (self.smtp_password is None):
            raise ValueError("SMTP username and password must be configured together")
        if self.smtp_username is not None and self.smtp_host is None:
            raise ValueError("SMTP credentials require an SMTP host")
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
