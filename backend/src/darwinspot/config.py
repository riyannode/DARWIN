from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./darwinspot.db"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    binance_agent_os_mcp_url: str = "https://agent.binance.com/mcp/agentic"
    token_encryption_key: str | None = None
    owner_password_hash: str | None = None
    frontend_origin: str = "http://localhost:3000"
    agent_cycle_seconds: int = Field(default=300, ge=5)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
