from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx2

from darwinspot.binance.mapper import map_candidate_market_history, map_market_history
from darwinspot.binance.schemas import (
    CANDIDATE_CANDLE_COUNT,
    CANDIDATE_HISTORY_REQUEST_LIMIT,
    CANDIDATE_MARKET_INTERVALS,
    HISTORY_CANDLE_COUNT,
    HISTORY_REQUEST_LIMIT,
    SUPPORTED_MARKET_INTERVALS,
    CandidateMarketHistorySnapshot,
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
    def request_params(
        symbol: str,
        interval: str,
        *,
        limit: int = HISTORY_REQUEST_LIMIT,
    ) -> dict[str, str | int]:
        if not re.fullmatch(r"[A-Z0-9]{5,20}", symbol) or symbol != symbol.upper():
            raise ValueError("market-history symbol must be an exact uppercase Spot symbol")
        if interval not in SUPPORTED_MARKET_INTERVALS:
            raise ValueError("market-history interval is unsupported")
        if limit not in {HISTORY_REQUEST_LIMIT, CANDIDATE_HISTORY_REQUEST_LIMIT}:
            raise ValueError("market-history limit is outside the supported bounds")
        if limit == CANDIDATE_HISTORY_REQUEST_LIMIT and interval not in CANDIDATE_MARKET_INTERVALS:
            raise ValueError("candidate market-history interval is unsupported")
        return {"symbol": symbol, "interval": interval, "limit": limit}

    async def _request_klines(
        self,
        symbol: str,
        interval: str,
        *,
        limit: int,
    ) -> tuple[Any, datetime]:
        try:
            async with httpx2.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}{self.KLINES_PATH}",
                    params=self.request_params(symbol, interval, limit=limit),
                )
                response.raise_for_status()
                payload: Any = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise BinanceSpotApiError("Binance Spot market-history request failed") from exc
        return payload, datetime.now(UTC)

    async def market_history(
        self,
        symbol: str,
        interval: str,
    ) -> MarketHistorySnapshot:
        payload, observed_at = await self._request_klines(
            symbol, interval, limit=HISTORY_REQUEST_LIMIT
        )
        return map_market_history(
            payload,
            symbol=symbol,
            interval=interval,
            now=observed_at,
            observed_at=observed_at,
        )

    async def candidate_history(
        self,
        symbol: str,
        interval: str,
    ) -> CandidateMarketHistorySnapshot:
        if interval not in CANDIDATE_MARKET_INTERVALS:
            raise ValueError("candidate market-history interval is unsupported")
        payload, observed_at = await self._request_klines(
            symbol, interval, limit=CANDIDATE_HISTORY_REQUEST_LIMIT
        )
        return map_candidate_market_history(
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
    "CANDIDATE_CANDLE_COUNT",
    "CANDIDATE_HISTORY_REQUEST_LIMIT",
    "CANDIDATE_MARKET_INTERVALS",
    "CLOSED_CANDLE_COUNT",
    "HISTORY_CANDLE_COUNT",
    "HISTORY_REQUEST_LIMIT",
    "SUPPORTED_MARKET_INTERVALS",
]

CLOSED_CANDLE_COUNT = HISTORY_CANDLE_COUNT
