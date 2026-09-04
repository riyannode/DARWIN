from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx2

from darwinspot.binance.mapper import map_market_history
from darwinspot.binance.schemas import (
    HISTORY_CANDLE_COUNT,
    HISTORY_REQUEST_LIMIT,
    SUPPORTED_MARKET_INTERVALS,
    MarketHistorySnapshot,
)
from darwinspot.binance.spot_api import BinanceSpotApiError
from darwinspot.config import validate_binance_spot_base_url


class BinanceSpotMarketDataClient:
    """Credential-free read-only adapter for Binance Spot public market data."""

    KLINES_PATH = "/api/v3/klines"

    def __init__(self, base_url: str) -> None:
        self.base_url = validate_binance_spot_base_url(base_url).rstrip("/")

    @staticmethod
    def request_params(symbol: str, interval: str) -> dict[str, str | int]:
        if not re.fullmatch(r"[A-Z0-9]{5,20}", symbol) or symbol != symbol.upper():
            raise ValueError("market-history symbol must be an exact uppercase Spot symbol")
        if interval not in SUPPORTED_MARKET_INTERVALS:
            raise ValueError("market-history interval is unsupported")
        return {"symbol": symbol, "interval": interval, "limit": HISTORY_REQUEST_LIMIT}

    async def market_history(
        self,
        symbol: str,
        interval: str,
    ) -> MarketHistorySnapshot:
        payload: Any
        try:
            async with httpx2.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}{self.KLINES_PATH}",
                    params=self.request_params(symbol, interval),
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise BinanceSpotApiError("Binance Spot market-history request failed") from exc
        observed_at = datetime.now(UTC)
        return map_market_history(
            payload,
            symbol=symbol,
            interval=interval,
            now=observed_at,
            observed_at=observed_at,
        )

    async def close(self) -> None:
        return None


__all__ = [
    "BinanceSpotMarketDataClient",
    "CLOSED_CANDLE_COUNT",
    "HISTORY_CANDLE_COUNT",
    "HISTORY_REQUEST_LIMIT",
    "SUPPORTED_MARKET_INTERVALS",
]

CLOSED_CANDLE_COUNT = HISTORY_CANDLE_COUNT
