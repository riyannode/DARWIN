from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator
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


class Settings(BaseSettings):
    database_url: str = "sqlite:///./darwinspot.db"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_base_url: str | None = None
    binance_agent_os_mcp_url: str = "https://agent.binance.com/mcp/agentic"
    token_encryption_key: str | None = None
    owner_password_hash: str | None = None
    frontend_origin: str = "http://localhost:3000"
    agent_cycle_seconds: int = Field(default=300, ge=5)
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
