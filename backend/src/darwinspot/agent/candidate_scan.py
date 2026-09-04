from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, cast

from darwinspot.binance.schemas import (
    CANDIDATE_MARKET_INTERVALS,
    CandidateMarketHistorySnapshot,
)

CANDIDATE_SCAN_MAX_CONCURRENCY = 8


class CandidateHistoryClient(Protocol):
    async def candidate_history(
        self, symbol: str, interval: str
    ) -> CandidateMarketHistorySnapshot: ...


@dataclass(frozen=True)
class CandidateScanResult:
    histories: dict[str, dict[str, CandidateMarketHistorySnapshot]]
    failures: dict[str, str]


async def scan_candidate_history(
    client: CandidateHistoryClient,
    symbols: Iterable[str],
    *,
    max_concurrency: int = CANDIDATE_SCAN_MAX_CONCURRENCY,
) -> CandidateScanResult:
    """Fetch bounded 15m/1h candidate history for every supplied symbol."""
    if max_concurrency <= 0:
        raise ValueError("candidate scan concurrency must be positive")
    semaphore = asyncio.Semaphore(max_concurrency)

    async def fetch_one(symbol: str, interval: str) -> CandidateMarketHistorySnapshot:
        async with semaphore:
            return await client.candidate_history(symbol, interval)

    async def scan_one(
        symbol: str,
    ) -> tuple[str, dict[str, CandidateMarketHistorySnapshot] | None, str | None]:
        results: list[CandidateMarketHistorySnapshot | BaseException] = list(
            await asyncio.gather(
                *(fetch_one(symbol, interval) for interval in CANDIDATE_MARKET_INTERVALS),
                return_exceptions=True,
            )
        )
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                return symbol, None, type(result).__name__
        snapshots = cast(list[CandidateMarketHistorySnapshot], results)
        return symbol, {
            snapshot.interval: snapshot for snapshot in snapshots
        }, None

    scanned = await asyncio.gather(*(scan_one(symbol) for symbol in symbols))
    histories: dict[str, dict[str, CandidateMarketHistorySnapshot]] = {}
    failures: dict[str, str] = {}
    for symbol, candidate_history, error_code in scanned:
        if candidate_history is None or error_code is not None:
            failures[symbol] = error_code or "UnknownCandidateHistoryError"
        else:
            histories[symbol] = candidate_history
    return CandidateScanResult(histories=histories, failures=failures)
