from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from darwinspot.binance.schemas import (
    BalanceSnapshot,
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
        "timestamp": _upstream_timestamp(value),
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
