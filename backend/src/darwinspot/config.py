from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def validate_openai_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    if value != value.strip() or not value.strip():
        raise ValueError("OPENAI_BASE_URL must not be empty or contain surrounding whitespace")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("OPENAI_BASE_URL must be an absolute HTTP(S) URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("OPENAI_BASE_URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("OPENAI_BASE_URL must not contain credentials, query, or fragment")
    return value


def validate_binance_spot_base_url(value: str) -> str:
    if value != value.strip() or not value.strip():
        raise ValueError(
            "BINANCE_SPOT_API_BASE_URL must not be empty or contain surrounding whitespace"
        )
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("BINANCE_SPOT_API_BASE_URL must be an absolute HTTPS URL") from exc
    allowed_hosts = {
        "api.binance.com",
        "api1.binance.com",
        "api2.binance.com",
        "api3.binance.com",
        "api4.binance.com",
    }
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() not in allowed_hosts
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/")
    ):
        raise ValueError("BINANCE_SPOT_API_BASE_URL must be an approved Binance HTTPS host")
    return value


class Settings(BaseSettings):
    database_url: str = "sqlite:///./darwinspot.db"
    demo_mode: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_base_url: str | None = None
    binance_agent_os_mcp_url: str = "https://agent.binance.com/mcp/agentic"
    binance_api_key: str | None = None
    binance_api_secret: str | None = None
    binance_spot_api_base_url: str = "https://api.binance.com"
    binance_account_lock_key: str = "darwinspot-binance-account"
    binance_recv_window_ms: int = Field(default=5000, ge=1000, le=60000)
    token_encryption_key: str | None = None
    owner_password_hash: str | None = None
    frontend_origin: str = "http://localhost:3000"
    agent_cycle_seconds: int = Field(default=300, ge=5)
    signal_cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    approval_ttl_seconds: int = Field(default=90, ge=30, le=180)
    telegram_bot_token: str | None = None
    telegram_operator_chat_id: int | None = None
    telegram_operator_user_id: int | None = None
    telegram_webhook_secret: str | None = None
    binance_agent_os_transport: Literal["codex"] = "codex"
    codex_app_server_command: str = "codex app-server --stdio"
    codex_app_server_version: str = "0.153.0"
    codex_write_confirmation_verified: bool = False
    log_level: str = "INFO"

    @field_validator("openai_api_key")
    @classmethod
    def validate_api_key(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("OPENAI_API_KEY must not be empty")
        return value

    @field_validator("openai_model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("OPENAI_MODEL must not be empty")
        return value

    @field_validator("openai_base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        return validate_openai_base_url(value)

    @field_validator("binance_spot_api_base_url")
    @classmethod
    def validate_binance_url(cls, value: str) -> str:
        return validate_binance_spot_base_url(value)

    @model_validator(mode="after")
    def validate_telegram_configuration(self) -> Settings:
        configured = (
            self.telegram_bot_token,
            self.telegram_operator_chat_id,
            self.telegram_operator_user_id,
            self.telegram_webhook_secret,
        )
        if any(value is not None for value in configured) and not all(
            value is not None and (not isinstance(value, str) or bool(value.strip()))
            for value in configured
        ):
            raise ValueError(
                "TELEGRAM_BOT_TOKEN, TELEGRAM_OPERATOR_CHAT_ID, "
                "TELEGRAM_OPERATOR_USER_ID, and TELEGRAM_WEBHOOK_SECRET must be configured together"
            )
        if self.telegram_operator_user_id is not None and self.telegram_operator_user_id <= 0:
            raise ValueError("TELEGRAM_OPERATOR_USER_ID must be positive")
        if not self.codex_app_server_version.strip():
            raise ValueError("CODEX_APP_SERVER_VERSION must not be empty")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
