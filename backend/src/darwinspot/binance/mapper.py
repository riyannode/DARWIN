from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from darwinspot.binance.schemas import (
    CANDIDATE_CANDLE_COUNT,
    CANDIDATE_HISTORY_REQUEST_LIMIT,
    CANDIDATE_MARKET_INTERVALS,
    HISTORY_CANDLE_COUNT,
    HISTORY_REQUEST_LIMIT,
    MARKET_HISTORY_MAX_STALENESS_PERIODS,
    MARKET_INTERVAL_SECONDS,
    SUPPORTED_MARKET_INTERVALS,
    BalanceSnapshot,
    CandidateMarketHistorySnapshot,
    MarketCandle,
    MarketHistorySnapshot,
    MarketSnapshot,
    OpenOrdersSnapshot,
    OrderSubmission,
    RecentActivitySnapshot,
    SymbolFilters,
)


class BinanceMappingError(ValueError):
    pass


class OrderCorrelationError(BinanceMappingError):
    pass


def _as_datetime(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000 if abs(value) >= 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, UTC)
    if isinstance(value, str) and value.isdigit():
        numeric = int(value)
        seconds = numeric / 1000 if abs(numeric) >= 10_000_000_000 else numeric
        return datetime.fromtimestamp(seconds, UTC)
    return value


def _normalise_timestamps(value: Any) -> Any:
    if isinstance(value, dict):
        raw_items = cast(dict[Any, Any], value).items()
        source: dict[str, Any] = {str(key): item for key, item in raw_items}
        time_keys = {
            "timestamp",
            "closeTime",
            "updateTime",
            "transactTime",
            "workingTime",
            "time",
            "serverTime",
        }
        return {
            key: _as_datetime(item) if key in time_keys else _normalise_timestamps(item)
            for key, item in source.items()
        }
    if isinstance(value, list):
        list_value = cast(list[Any], value)
        return [_normalise_timestamps(item) for item in list_value]
    return value


def _object_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BinanceMappingError("Agent OS response was not an object")
    return cast(dict[str, Any], _normalise_timestamps(payload))


def _validate(model: type[Any], payload: Any, message: str) -> Any:
    try:
        return model.model_validate(payload)
    except Exception as exc:
        raise BinanceMappingError(message) from exc


def _upstream_timestamp(value: dict[str, Any]) -> datetime | None:
    return next(
        (
            value[key]
            for key in ("timestamp", "closeTime", "updateTime", "transactTime", "serverTime")
            if isinstance(value.get(key), datetime)
        ),
        None,
    )


def _account_snapshot_timestamp(value: dict[str, Any]) -> datetime | None:
    return next(
        (
            value[key]
            for key in ("timestamp", "serverTime")
            if isinstance(value.get(key), datetime)
        ),
        None,
    )


def _order_projection(payload: dict[str, Any], *, require_timestamp: bool) -> dict[str, Any]:
    value: dict[str, Any] = cast(dict[str, Any], _normalise_timestamps(payload))
    order_id = value.get("orderId", value.get("order_id"))
    status = value.get("status")
    symbol = value.get("symbol")
    updated_at = next(
        (
            value[key]
            for key in ("updateTime", "transactTime", "workingTime", "time", "updated_at")
            if isinstance(value.get(key), datetime)
        ),
        None,
    )
    if order_id is None or status is None or symbol is None:
        raise BinanceMappingError("Agent OS order response omitted required Binance Spot fields")
    if require_timestamp and updated_at is None:
        raise BinanceMappingError("Agent OS order response omitted an upstream timestamp")
    quote_fields = (
        "cummulativeQuoteQty",
        "cumulativeQuoteQty",
        "quoteNotional",
        "quote_notional",
    )
    quote_value = next(
        (value[key] for key in quote_fields if value.get(key) is not None),
        "0",
    )
    executed_value = value.get("executedQty", value.get("executed_quantity", "0"))
    try:
        executed_decimal = Decimal(str(executed_value))
    except Exception as exc:
        raise BinanceMappingError(
            "Agent OS order response had an invalid executed quantity"
        ) from exc
    if status in {"PARTIALLY_FILLED", "FILLED"} and executed_decimal > 0:
        if not any(value.get(key) is not None for key in quote_fields):
            raise BinanceMappingError(
                "Agent OS filled order response omitted cumulative quote quantity"
            )
    return {
        "orderId": order_id,
        "symbol": symbol,
        "status": status,
        "executedQty": value.get("executedQty", value.get("executed_quantity", "0")),
        "cummulativeQuoteQty": quote_value,
        "updated_at": updated_at,
    }


def map_mcp_result(
    operation: str, payload: Any, observed_at: datetime | None = None
) -> MarketSnapshot:
    if operation != "get_ticker":
        raise BinanceMappingError(f"unsupported Agent OS operation: {operation}")
    value = _object_payload(payload)
    projected: dict[str, Any] = {
        "symbol": value.get("symbol"),
        "price": value.get("price"),
        "timestamp": _upstream_timestamp(value),
        "observed_at": observed_at or datetime.now(UTC),
    }
    return _validate(
        MarketSnapshot,
        projected,
        "Agent OS ticker response did not match Binance Spot schema",
    )


def map_order_submission(payload: Any) -> OrderSubmission:
    value = _object_payload(payload)
    projected = _order_projection(value, require_timestamp=False)
    return _validate(
        OrderSubmission,
        projected,
        "Agent OS order response did not match Binance Spot schema",
    )


def validate_order_submission_correlation(
    payload: Any,
    *,
    submission: OrderSubmission,
    expected_symbol: str,
    expected_client_order_id: str,
    expected_side: str,
) -> None:
    """Reject an upstream order response that does not belong to this intent."""
    if submission.symbol != expected_symbol:
        raise OrderCorrelationError("Agent OS order response symbol did not match the intent")
    value = _object_payload(payload)
    returned_client_order_id = value.get("clientOrderId", value.get("client_order_id"))
    if (
        returned_client_order_id is not None
        and returned_client_order_id != expected_client_order_id
    ):
        raise OrderCorrelationError(
            "Agent OS order response client order ID did not match the intent"
        )
    returned_side = value.get("side")
    if returned_side is not None and returned_side != expected_side:
        raise OrderCorrelationError("Agent OS order response side did not match the intent")


def map_balances(payload: Any, observed_at: datetime | None = None) -> BalanceSnapshot:
    value = _object_payload(payload)
    balances = value.get("balances")
    if not isinstance(balances, list):
        raise BinanceMappingError("Agent OS account response omitted balances")
    projected: dict[str, Any] = {
        "timestamp": _account_snapshot_timestamp(value),
        "observed_at": observed_at or datetime.now(UTC),
        "balances": balances,
    }
    return _validate(
        BalanceSnapshot,
        projected,
        "Agent OS account response did not match Binance Spot schema",
    )


def map_open_orders(payload: Any, observed_at: datetime | None = None) -> OpenOrdersSnapshot:
    observed = observed_at or datetime.now(UTC)
    if isinstance(payload, list):
        raw_orders: list[Any] = cast(list[Any], payload)
        top_timestamp: datetime | None = None
    else:
        value = _object_payload(payload)
        raw_orders_value = value.get("orders")
        if not isinstance(raw_orders_value, list):
            raise BinanceMappingError(
                "Agent OS open-orders response did not match Binance Spot schema"
            )
        raw_orders = cast(list[Any], raw_orders_value)
        top_timestamp = _upstream_timestamp(value)
    if not all(isinstance(item, dict) for item in raw_orders):
        raise BinanceMappingError("Agent OS open-orders response did not match Binance Spot schema")
    order_dicts = cast(list[dict[str, Any]], raw_orders)
    projected_orders = [_order_projection(item, require_timestamp=True) for item in order_dicts]
    order_timestamps = [
        item["updated_at"] for item in projected_orders if isinstance(item["updated_at"], datetime)
    ]
    timestamp = top_timestamp or (max(order_timestamps) if order_timestamps else None)
    return _validate(
        OpenOrdersSnapshot,
        {"timestamp": timestamp, "observed_at": observed, "orders": projected_orders},
        "Agent OS open-orders response did not match Binance Spot schema",
    )


def map_recent_activity(
    payload: Any, observed_at: datetime | None = None
) -> RecentActivitySnapshot:
    observed = observed_at or datetime.now(UTC)
    if isinstance(payload, list):
        raw_items: list[Any] = cast(list[Any], payload)
    elif isinstance(payload, dict):
        trade_items = cast(dict[str, Any], payload).get("trades")
        if not isinstance(trade_items, list):
            raise BinanceMappingError(
                "Agent OS trade-history response did not match Binance Spot schema"
            )
        raw_items = cast(list[Any], trade_items)
    else:
        raise BinanceMappingError(
            "Agent OS trade-history response did not match Binance Spot schema"
        )
    if not all(isinstance(item, dict) for item in raw_items):
        raise BinanceMappingError("Agent OS trade-history entries were not objects")
    items = cast(list[dict[str, Any]], raw_items)
    normalised_items = cast(list[dict[str, Any]], _normalise_timestamps(items))
    item_timestamps = [
        timestamp
        for item in normalised_items
        for timestamp in (
            item.get("time"),
            item.get("updateTime"),
            item.get("transactTime"),
        )
        if isinstance(timestamp, datetime)
    ]
    return _validate(
        RecentActivitySnapshot,
        {
            "timestamp": max(item_timestamps) if item_timestamps else None,
            "observed_at": observed,
            "items": items,
        },
        "Agent OS trade-history response did not match Binance Spot schema",
    )


def map_symbol_filters(payload: Any, observed_at: datetime | None = None) -> SymbolFilters:
    value = _object_payload(payload)
    symbol = value.get("symbol")
    filters = value.get("filters")
    if not isinstance(symbol, str) or not isinstance(filters, list):
        raise BinanceMappingError(
            "Agent OS exchange-info response did not match Binance Spot schema"
        )
    filter_values = cast(list[Any], filters)
    filter_dicts = cast(
        list[dict[str, Any]], [item for item in filter_values if isinstance(item, dict)]
    )
    by_type: dict[str, dict[str, Any]] = {
        filter_type: item
        for item in filter_dicts
        if isinstance(filter_type := item.get("filterType"), str)
    }
    lot_size = by_type.get("LOT_SIZE")
    price_filter = by_type.get("PRICE_FILTER")
    notional = by_type.get("NOTIONAL") or by_type.get("MIN_NOTIONAL")
    if (
        not isinstance(lot_size, dict)
        or not isinstance(price_filter, dict)
        or not isinstance(notional, dict)
    ):
        raise BinanceMappingError("Agent OS exchange-info response omitted required Spot filters")
    normalised: dict[str, Any] = {
        "symbol": symbol,
        "quoteAsset": value.get("quoteAsset"),
        "minQty": lot_size.get("minQty"),
        "stepSize": lot_size.get("stepSize"),
        "tickSize": price_filter.get("tickSize"),
        "minNotional": notional.get("minNotional"),
        "timestamp": _upstream_timestamp(value),
        "observed_at": observed_at or datetime.now(UTC),
    }
    return _validate(
        SymbolFilters,
        normalised,
        "Agent OS symbol filters did not match Binance Spot schema",
    )


def order_submission_evidence(
    payload: Any,
    *,
    intent_id: str,
    client_order_id: str,
    error: BaseException | None = None,
    submission: OrderSubmission | None = None,
) -> dict[str, Any]:
    """Return only allowlisted, sanitized fields retained for an order submission."""
    value = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
    evidence: dict[str, Any] = {
        "intent_id": intent_id,
        "client_order_id": value.get(
            "clientOrderId", value.get("client_order_id", client_order_id)
        ),
    }
    fields = {
        "binance_order_id": ("orderId", "order_id"),
        "symbol": ("symbol",),
        "side": ("side",),
        "status": ("status",),
        "executed_quantity": ("executedQty", "executed_quantity"),
        "quote_quantity": (
            "cummulativeQuoteQty",
            "cumulativeQuoteQty",
            "quoteNotional",
            "quote_notional",
        ),
        "timestamp": ("updateTime", "transactTime", "workingTime", "time", "updated_at"),
    }
    mapped_values = (
        {
            "binance_order_id": submission.order_id,
            "symbol": submission.symbol,
            "status": submission.status,
            "executed_quantity": submission.executed_quantity,
            "quote_quantity": submission.quote_notional,
            "timestamp": submission.updated_at,
        }
        if submission is not None
        else {}
    )
    for name, keys in fields.items():
        candidate = next((value[key] for key in keys if value.get(key) is not None), None)
        if candidate is None:
            candidate = mapped_values.get(name)
        if candidate is not None:
            evidence[name] = candidate
    if error is not None:
        message = re.sub(
            r"(?i)(authorization|token|secret|password|api[_-]?key)\s*[:=]\s*\S+",
            r"\1=[redacted]",
            str(error),
        )
        evidence["error_code"] = type(error).__name__
        evidence["error_message"] = message[:512]
    return evidence


def _kline_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, bool):
        raise BinanceMappingError(f"Binance kline {field} timestamp is invalid")
    if isinstance(value, int):
        milliseconds = value
    elif isinstance(value, str) and value.isdigit():
        milliseconds = int(value)
    else:
        raise BinanceMappingError(f"Binance kline {field} timestamp is invalid")
    try:
        return datetime.fromtimestamp(milliseconds / 1000, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise BinanceMappingError(f"Binance kline {field} timestamp is invalid") from exc


def _kline_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise BinanceMappingError(f"Binance kline {field} value is invalid")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BinanceMappingError(f"Binance kline {field} value is invalid") from exc
    if not parsed.is_finite():
        raise BinanceMappingError(f"Binance kline {field} value is invalid")
    return parsed


def _kline_trade_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise BinanceMappingError("Binance kline trade count is invalid")
    if isinstance(value, int):
        count = value
    elif isinstance(value, str) and value.isdigit():
        count = int(value)
    else:
        raise BinanceMappingError("Binance kline trade count is invalid")
    if count < 0:
        raise BinanceMappingError("Binance kline trade count is invalid")
    return count


def _map_market_history_payload(
    payload: Any,
    *,
    symbol: str,
    interval: str,
    candle_count: int,
    request_limit: int,
    now: datetime | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Map and validate the bounded closed-candle response from Spot /api/v3/klines."""
    if (
        not re.fullmatch(r"[A-Z0-9]{5,20}", symbol)
        or symbol != symbol.upper()
    ):
        raise BinanceMappingError("selected market-history symbol is invalid")
    if interval not in SUPPORTED_MARKET_INTERVALS:
        raise BinanceMappingError("requested market-history interval is unsupported")
    interval_key = interval
    current_time = now or datetime.now(UTC)
    observed = observed_at or current_time
    if current_time.tzinfo is None or observed.tzinfo is None:
        raise BinanceMappingError("market-history timestamps must be timezone-aware")
    if not isinstance(payload, list) or not payload:
        raise BinanceMappingError("Binance kline response is outside the bounded array shape")

    raw_klines = cast(list[Any], payload)
    if len(raw_klines) > request_limit:
        raise BinanceMappingError("Binance kline response is outside the bounded array shape")
    closed: list[MarketCandle] = []
    previous_open_time: datetime | None = None
    previous_close_time: datetime | None = None
    unfinished_count = 0
    for raw_kline in raw_klines:
        if not isinstance(raw_kline, list):
            raise BinanceMappingError("Binance kline entry does not match the official array shape")
        values = cast(list[Any], raw_kline)
        if len(values) != 12:
            raise BinanceMappingError("Binance kline entry does not match the official array shape")
        open_time = _kline_datetime(values[0], "open")
        close_time = _kline_datetime(values[6], "close")
        if previous_open_time is not None and open_time <= previous_open_time:
            raise BinanceMappingError("Binance kline open timestamps are not strictly ordered")
        if previous_close_time is not None and close_time <= previous_close_time:
            raise BinanceMappingError("Binance kline close timestamps are not strictly ordered")
        previous_open_time = open_time
        previous_close_time = close_time
        if open_time >= current_time or close_time <= open_time:
            raise BinanceMappingError("Binance kline timestamps are invalid or in the future")
        open_value = _kline_decimal(values[1], "open")
        high = _kline_decimal(values[2], "high")
        low = _kline_decimal(values[3], "low")
        close = _kline_decimal(values[4], "close")
        volume = _kline_decimal(values[5], "volume")
        quote_volume = _kline_decimal(values[7], "quote volume")
        trade_count = _kline_trade_count(values[8])
        if (
            open_value <= 0
            or high <= 0
            or low <= 0
            or close <= 0
            or volume < 0
            or quote_volume < 0
            or high < open_value
            or high < close
            or low > open_value
            or low > close
            or high < low
        ):
            raise BinanceMappingError("Binance kline OHLCV values failed validation")
        candle = MarketCandle(
            open_time=open_time,
            close_time=close_time,
            open=open_value,
            high=high,
            low=low,
            close=close,
            volume=volume,
            quote_volume=quote_volume,
            trade_count=trade_count,
        )
        if close_time < current_time:
            closed.append(candle)
        else:
            unfinished_count += 1

    if unfinished_count > 1:
        raise BinanceMappingError("Binance kline response contains multiple unfinished candles")
    if len(closed) < candle_count:
        raise BinanceMappingError("Binance kline response contains too few closed candles")
    closed = closed[-candle_count:]
    interval_seconds = MARKET_INTERVAL_SECONDS[interval_key]
    newest_staleness = current_time - closed[-1].close_time
    max_staleness = timedelta(seconds=interval_seconds * MARKET_HISTORY_MAX_STALENESS_PERIODS)
    if newest_staleness < timedelta(0) or newest_staleness > max_staleness:
        raise BinanceMappingError("Binance market history is stale")
    return {
        "symbol": symbol,
        "interval": interval_key,
        "candles": closed,
        "observed_at": observed,
    }


def map_market_history(
    payload: Any,
    *,
    symbol: str,
    interval: str,
    now: datetime | None = None,
    observed_at: datetime | None = None,
) -> MarketHistorySnapshot:
    return MarketHistorySnapshot.model_validate(
        _map_market_history_payload(
            payload,
            symbol=symbol,
            interval=interval,
            candle_count=HISTORY_CANDLE_COUNT,
            request_limit=HISTORY_REQUEST_LIMIT,
            now=now,
            observed_at=observed_at,
        )
    )


def map_candidate_market_history(
    payload: Any,
    *,
    symbol: str,
    interval: str,
    now: datetime | None = None,
    observed_at: datetime | None = None,
) -> CandidateMarketHistorySnapshot:
    if interval not in CANDIDATE_MARKET_INTERVALS:
        raise BinanceMappingError("candidate market-history interval is unsupported")
    return CandidateMarketHistorySnapshot.model_validate(
        _map_market_history_payload(
            payload,
            symbol=symbol,
            interval=interval,
            candle_count=CANDIDATE_CANDLE_COUNT,
            request_limit=CANDIDATE_HISTORY_REQUEST_LIMIT,
            now=now,
            observed_at=observed_at,
        )
    )


def map_spot_market_universe(payload: Any) -> list[dict[str, Any]]:
    """Map live Agent OS metadata to tradable SPOT/USDT symbols only."""
    raw_items: list[object] | None
    if isinstance(payload, list):
        raw_items = cast(list[object], payload)
    elif isinstance(payload, dict):
        value = cast(dict[str, Any], payload)
        candidate = value.get("symbols", value.get("tickers", value.get("data")))
        raw_items = cast(list[object], candidate) if isinstance(candidate, list) else None
    else:
        raw_items = None
    if raw_items is None or not all(isinstance(item, dict) for item in raw_items):
        raise BinanceMappingError("Agent OS market universe response did not match Spot schema")

    universe: list[dict[str, Any]] = []
    for raw_item in raw_items:
        item = cast(dict[str, Any], raw_item)
        symbol = item.get("symbol")
        status = item.get("status")
        quote_asset = item.get("quoteAsset", item.get("quote_asset"))
        permissions = item.get("permissions")
        spot_allowed = item.get("isSpotTradingAllowed")
        has_spot_permission = isinstance(permissions, list) and "SPOT" in permissions
        if (
            not isinstance(symbol, str)
            or not re.fullmatch(r"[A-Z0-9]{5,20}", symbol)
            or status != "TRADING"
            or quote_asset != "USDT"
            or spot_allowed is False
            or (spot_allowed is not True and not has_spot_permission)
        ):
            continue
        entry: dict[str, Any] = {
            "symbol": symbol,
            "status": status,
            "quote_asset": quote_asset,
            "spot_trading_allowed": True,
        }
        for output, keys in {
            "price": ("price", "lastPrice"),
            "price_change_percent": ("priceChangePercent",),
            "volume": ("volume",),
            "quote_volume": ("quoteVolume",),
            "timestamp": ("timestamp", "closeTime", "updateTime"),
        }.items():
            candidate = next((item[key] for key in keys if item.get(key) is not None), None)
            if candidate is not None:
                entry[output] = candidate
        universe.append(entry)
    if not universe:
        raise BinanceMappingError(
            "Agent OS market universe contains no live SPOT TRADING USDT symbols"
        )
    return universe
