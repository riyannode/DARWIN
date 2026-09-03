from __future__ import annotations

from typing import Any

from darwinspot.binance.client import BinanceAgentOSClient
from darwinspot.binance.codex_transport import CodexAppServerTransport, CodexBinanceClient
from darwinspot.config import Settings
from darwinspot.storage.models import BinanceConnection


def build_binance_client(
    settings: Settings,
    connection: BinanceConnection | None = None,
) -> Any:
    if settings.binance_agent_os_transport == "codex":
        return CodexBinanceClient(CodexAppServerTransport(settings))
    if connection is None or not settings.token_encryption_key:
        raise RuntimeError("direct OAuth transport requires a connected Binance connection")
    return BinanceAgentOSClient.with_oauth(
        settings.binance_agent_os_mcp_url,
        connection.id,
        settings.token_encryption_key,
        f"{settings.frontend_origin.rstrip('/')}/api/integrations/binance/callback",
        f"{settings.frontend_origin.rstrip('/')}/.well-known/darwinspot-oauth-client.json",
    )
