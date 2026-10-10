"""Validated environment configuration. Values and credentials never enter errors."""

import os
import re
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.engine import make_url

COOKIE_NAME = "triptab_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


class Settings(BaseModel):
    model_config = ConfigDict(
        frozen=True, populate_by_name=True, hide_input_in_errors=True
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development", alias="TRIPTAB_ENV"
    )
    database_url: SecretStr | None = Field(default=None, alias="DATABASE_URL")
    allowed_origins: tuple[str, ...] = Field(
        default=(), alias="TRIPTAB_ALLOWED_ORIGINS"
    )
    cookie_name: str = Field(default=COOKIE_NAME, alias="TRIPTAB_COOKIE_NAME")
    cookie_secure: bool = Field(default=True, alias="TRIPTAB_COOKIE_SECURE")
    session_seconds: int = Field(
        default=SESSION_SECONDS, ge=300, le=2592000, alias="TRIPTAB_SESSION_SECONDS"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="TRIPTAB_LOG_LEVEL"
    )
    debug: bool = Field(default=False, alias="TRIPTAB_DEBUG")
    auth_rate_limit: int = Field(
        default=10, ge=1, le=10000, alias="TRIPTAB_AUTH_RATE_LIMIT"
    )
    auth_global_limit: int = Field(
        default=100, ge=1, le=10000, alias="TRIPTAB_AUTH_GLOBAL_LIMIT"
    )
    auth_rate_window: int = Field(
        default=60, ge=1, le=3600, alias="TRIPTAB_AUTH_RATE_WINDOW"
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def provider_database_url(cls, value: object) -> object:
        # Render supplies the standard scheme; retain our installed psycopg driver.
        if isinstance(value, str) and value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def origins(cls, value: object) -> tuple[str, ...]:
        values = value.split(",") if isinstance(value, str) else value
        result = []
        for item in values:
            origin = item.strip().rstrip("/")
            if not origin:
                continue
            try:
                parsed = urlsplit(origin)
                valid = (
                    parsed.scheme in {"http", "https"}
                    and parsed.hostname
                    and parsed.username is None
                    and parsed.password is None
                    and not parsed.path
                    and not parsed.query
                    and not parsed.fragment
                    and "*" not in parsed.netloc
                    and not any(char.isspace() for char in origin)
                )
                _ = parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("allowed origins must be explicit HTTP(S) origins")
            result.append(origin)
        return tuple(dict.fromkeys(result))

    @field_validator("cookie_name")
    @classmethod
    def cookie(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) or value.startswith(
            "__Host-"
        ):
            raise ValueError("cookie name must be valid for the /api/v1 cookie path")
        return value

    @field_validator("cookie_secure", "debug", mode="before")
    @classmethod
    def boolean(cls, value: object) -> object:
        if isinstance(value, str):
            if value.lower() not in {"true", "false"}:
                raise ValueError("boolean configuration must be true or false")
            return value.lower() == "true"
        return value

    @model_validator(mode="after")
    def safety(self) -> Self:
        parsed = None
        if self.database_url is not None:
            try:
                parsed = make_url(self.database_url.get_secret_value())
            except Exception:
                raise ValueError("invalid DATABASE_URL") from None
            if parsed.drivername != "postgresql+psycopg" or not parsed.database:
                raise ValueError("DATABASE_URL must name a PostgreSQL psycopg database")
        if self.cookie_name.startswith("__Secure-") and not self.cookie_secure:
            raise ValueError("__Secure- cookies require Secure")
        if self.environment == "production":
            if not self.cookie_secure or self.debug or self.log_level == "DEBUG":
                raise ValueError(
                    "production requires Secure cookies and debug disabled"
                )
            if not self.allowed_origins or any(
                not origin.startswith("https://") for origin in self.allowed_origins
            ):
                raise ValueError("production requires explicit HTTPS allowed origins")
            # Keep legacy examples rejected as well as the current TripTab examples.
            unsafe = {
                "splitwise_local_only",
                "triptab_local_only",
                "triptab_ci_only",
                "splitwise_ci_only",
                "password",
                "postgres",
                "changeme",
                "change-me",
            }
            if (
                parsed is None
                or not parsed.host
                or not parsed.username
                or not parsed.password
                or parsed.password.lower() in unsafe
                or "replace" in parsed.password.lower()
                or "example" in parsed.password.lower()
            ):
                raise ValueError("production requires non-example database credentials")
        return self

    @classmethod
    def from_environment(cls) -> Self:
        values = {
            field.alias: os.environ[field.alias]
            for field in cls.model_fields.values()
            if field.alias in os.environ
        }
        try:
            return cls.model_validate(values)
        except ValidationError as error:
            fields = sorted(
                {
                    str(item["loc"][0]) if item["loc"] else "safety"
                    for item in error.errors()
                }
            )
            raise RuntimeError(
                "invalid TripTab configuration: " + ", ".join(fields)
            ) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_environment()
