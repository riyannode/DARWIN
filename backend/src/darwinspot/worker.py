"""Bounded worker entry point; external orchestration owns process lifetime."""

from __future__ import annotations

import asyncio

import httpx2
import openai

from darwinspot.agent.cycle import CycleConfigurationError, CycleUnavailable, run_cycle
from darwinspot.agent.runtime import AgentRuntime
from darwinspot.binance.client import (
    AgentOSUnavailable,
    BinanceAgentOSClient,
    UnsupportedCapability,
)
from darwinspot.config import Settings, get_settings
from darwinspot.observability import log_event
from darwinspot.storage.database import SessionLocal
from darwinspot.storage.repository import Repository

_TRANSIENT_OPENAI_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_MAX_BACKOFF_SECONDS = 60


def _validate_worker_config(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("OPENAI_API_KEY", settings.openai_api_key),
            ("TOKEN_ENCRYPTION_KEY", settings.token_encryption_key),
            ("BINANCE_AGENT_OS_MCP_URL", settings.binance_agent_os_mcp_url),
            ("OPENAI_MODEL", settings.openai_model),
        )
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        raise RuntimeError(f"worker configuration is missing: {', '.join(missing)}")


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, (CycleConfigurationError, UnsupportedCapability)):
        return False
    if isinstance(
        exc,
        (
            AgentOSUnavailable,
            CycleUnavailable,
            TimeoutError,
            httpx2.RequestError,
            httpx2.TimeoutException,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
        ),
    ):
        return True
    return (
        isinstance(exc, openai.APIStatusError)
        and exc.status_code in _TRANSIENT_OPENAI_STATUS_CODES
    )


def _backoff_seconds(failure_streak: int) -> int:
    return min(2 ** max(0, failure_streak - 1), _MAX_BACKOFF_SECONDS)


async def run_worker() -> None:
    settings = get_settings()
    _validate_worker_config(settings)
    openai_api_key = settings.openai_api_key
    token_encryption_key = settings.token_encryption_key
    if openai_api_key is None or token_encryption_key is None:
        raise RuntimeError("worker configuration validation did not establish required secrets")
    failure_streak = 0
    while True:
        sleep_seconds = settings.agent_cycle_seconds
        with SessionLocal() as db:
            repo = Repository(db)
            config = repo.claim_due_run(settings.agent_cycle_seconds)
            if config is not None:
                run = repo.start_run("SCHEDULED", settings.openai_model)
                connection_id: str | None = None
                try:
                    connection = repo.current_connection()
                    connection_id = connection.id if connection is not None else None
                    if connection is None or connection.state != "CONNECTED":
                        raise AgentOSUnavailable("Binance Agent OS is not connected")
                    result = await asyncio.wait_for(
                        run_cycle(
                            repo,
                            BinanceAgentOSClient.with_oauth(
                                settings.binance_agent_os_mcp_url,
                                connection.id,
                                token_encryption_key,
                                f"{settings.frontend_origin.rstrip('/')}/api/integrations/binance/callback",
                                f"{settings.frontend_origin.rstrip('/')}/.well-known/darwinspot-oauth-client.json",
                            ),
                            AgentRuntime(openai_api_key, settings.openai_model),
                            run.id,
                        ),
                        timeout=60,
                    )
                except Exception as exc:
                    transient = _is_transient_error(exc)
                    if transient and isinstance(exc, AgentOSUnavailable):
                        repo.mark_connection_unavailable(connection_id)
                    repo.complete_run(run.id, "FAILED", None, str(exc))
                    if transient:
                        failure_streak += 1
                        sleep_seconds = _backoff_seconds(failure_streak)
                    else:
                        log_event(
                            "AGENT_CYCLE_FAILED",
                            run_id=run.id,
                            error_code=type(exc).__name__,
                            transient=False,
                        )
                        db.commit()
                        raise
                    log_event(
                        "AGENT_CYCLE_FAILED",
                        run_id=run.id,
                        error_code=type(exc).__name__,
                        transient=True,
                        backoff_seconds=sleep_seconds,
                    )
                else:
                    failure_streak = 0
                    repo.complete_run(run.id, result, None, None)
                db.commit()
        await asyncio.sleep(sleep_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker())
