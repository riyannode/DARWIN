from __future__ import annotations

from typing import Any

from darwinspot.binance.codex_transport import CodexAppServerTransport, CodexBinanceClient
from darwinspot.binance.spot_api import BinanceSpotApiClient
from darwinspot.config import Settings
from darwinspot.execution.modes import ExecutionMode
from darwinspot.storage.models import BinanceConnection


def build_binance_client(
    settings: Settings,
    connection: BinanceConnection | None = None,
    mode: str = ExecutionMode.HUMAN_APPROVAL,
) -> Any:
    if mode == ExecutionMode.AUTO_BOUNDED:
        return BinanceSpotApiClient(
            settings.binance_spot_api_base_url,
            settings.binance_api_key,
            settings.binance_api_secret,
            recv_window_ms=settings.binance_recv_window_ms,
        )
    return CodexBinanceClient(CodexAppServerTransport(settings))
