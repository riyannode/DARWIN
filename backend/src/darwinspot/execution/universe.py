from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, cast

DEFAULT_SUPPORTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{1,16}USDT$")


@dataclass(frozen=True)
class EffectiveUniverse:
    eligible: frozenset[str]
    invalid_configured: frozenset[str]


def validate_supported_symbols(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError("supported_symbols must be a non-empty list")
    symbols = cast(list[Any], values)
    if len(symbols) > 100 or not all(isinstance(item, str) for item in symbols):
        raise ValueError("supported_symbols must contain at most 100 strings")
    parsed = tuple(cast(str, item) for item in symbols)
    if any(not _SYMBOL_PATTERN.fullmatch(item) for item in parsed):
        raise ValueError("supported_symbols must contain uppercase Spot/USDT symbols")
    if len(set(parsed)) != len(parsed):
        raise ValueError("supported_symbols must not contain duplicates")
    return parsed


def parse_supported_symbols(value: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("stored supported_symbols is invalid JSON") from exc
    return validate_supported_symbols(parsed)


def effective_symbols(
    configured: Iterable[str],
    mandate_allowed: Iterable[str],
    live_metadata: list[dict[str, Any]],
) -> EffectiveUniverse:
    configured_set = frozenset(configured)
    mandate_set = frozenset(mandate_allowed)
    valid_live: set[str] = set()
    for item in live_metadata:
        symbol = item.get("symbol")
        if (
            isinstance(symbol, str)
            and symbol in configured_set
            and item.get("quote_asset", item.get("quoteAsset")) == "USDT"
            and item.get("status") == "TRADING"
            and item.get(
                "spot_trading_allowed", item.get("isSpotTradingAllowed", True)
            ) is not False
        ):
            valid_live.add(symbol)
    invalid = configured_set - valid_live
    return EffectiveUniverse(
        eligible=frozenset(configured_set & mandate_set & valid_live),
        invalid_configured=frozenset(invalid),
    )
