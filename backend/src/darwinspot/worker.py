"""Bounded worker entry point; external orchestration owns process lifetime."""

from __future__ import annotations

import asyncio

from darwinspot.agent.cycle import CycleUnavailable, run_cycle
from darwinspot.agent.runtime import AgentRuntime
from darwinspot.binance.client import AgentOSUnavailable, BinanceAgentOSClient
from darwinspot.config import get_settings
from darwinspot.storage.database import SessionLocal
from darwinspot.storage.repository import Repository


async def run_worker() -> None:
    while True:
        with SessionLocal() as db:
            repo = Repository(db)
            settings = get_settings()
            config = repo.claim_due_run(settings.agent_cycle_seconds)
            if config is not None:
                run = repo.start_run("SCHEDULED", settings.openai_model)
                connection_id: str | None = None
                try:
                    if not settings.openai_api_key:
                        raise ValueError("OPENAI_API_KEY is required for a scheduled run")
                    connection = repo.current_connection()
                    connection_id = connection.id if connection is not None else None
                    if connection is None or connection.state != "CONNECTED":
                        raise AgentOSUnavailable("Binance Agent OS is not connected")
                    if not settings.token_encryption_key:
                        raise AgentOSUnavailable(
                            "TOKEN_ENCRYPTION_KEY is required for Agent OS auth"
                        )
                    result = await asyncio.wait_for(
                        run_cycle(
                            repo,
                            BinanceAgentOSClient.with_oauth(
                                settings.binance_agent_os_mcp_url,
                                connection.id,
                                settings.token_encryption_key,
                                f"{settings.frontend_origin.rstrip('/')}/api/integrations/binance/callback",
                                f"{settings.frontend_origin.rstrip('/')}/.well-known/darwinspot-oauth-client.json",
                            ),
                            AgentRuntime(settings.openai_api_key, settings.openai_model),
                            run.id,
                        ),
                        timeout=60,
                    )
                except TimeoutError:
                    repo.complete_run(run.id, "FAILED", None, "agent cycle timed out")
                    config.state = "PAUSED_ERROR"
                except (AgentOSUnavailable, CycleUnavailable, ValueError) as exc:
                    if isinstance(exc, AgentOSUnavailable):
                        repo.mark_connection_unavailable(connection_id)
                    repo.complete_run(run.id, "FAILED", None, str(exc))
                    config.state = (
                        "PAUSED_CONNECTION"
                        if isinstance(exc, AgentOSUnavailable)
                        else "PAUSED_ERROR"
                    )
                else:
                    repo.complete_run(run.id, result, None, None)
                db.commit()
        await asyncio.sleep(get_settings().agent_cycle_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker())
