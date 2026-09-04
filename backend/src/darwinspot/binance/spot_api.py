from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from decimal import Decimal
from time import time
from typing import Any, cast
from urllib.parse import urlencode

import httpx2

from darwinspot.binance.client import AgentOSUnavailable, ToolCall, ToolDescriptor
from darwinspot.execution.demo_guard import ensure_financial_write_allowed


class BinanceSpotApiNotConfigured(AgentOSUnavailable):
    pass


class BinanceSpotApiError(AgentOSUnavailable):
    pass


def build_signed_query(params: Mapping[str, Any], api_secret: str) -> tuple[str, str]:
    query_values = {
        key: format(value, "f") if isinstance(value, Decimal) else value
        for key, value in params.items()
    }
    query = urlencode(query_values)
    signature = hmac.new(
        api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return query, signature


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


class BinanceSpotApiClient:
    """Small Binance Spot REST adapter for DARWIN's required operations only."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        api_secret: str | None,
        *,
        recv_window_ms: int = 5000,
    ) -> None:
        if not api_key or not api_secret or not api_key.strip() or not api_secret.strip():
            raise BinanceSpotApiNotConfigured("Binance Spot API credentials are not configured")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self._recv_window_ms = recv_window_ms

    @property
    def credentials_configured(self) -> bool:
        return bool(self._api_key and self._api_secret)

    @staticmethod
    def tool_descriptors() -> tuple[ToolDescriptor, ...]:
        symbol_property = {"type": "string", "pattern": "^[A-Z0-9]{5,20}$"}
        return (
            ToolDescriptor(
                "get_exchange_info",
                "exchange information for all symbols",
                _schema({}),
            ),
            ToolDescriptor(
                "get_ticker",
                "current ticker price",
                _schema({"symbol": symbol_property}, ["symbol"]),
            ),
            ToolDescriptor("get_account", "account balances", _schema({})),
            ToolDescriptor(
                "get_open_orders",
                "open orders",
                _schema({"symbol": symbol_property}),
            ),
            ToolDescriptor(
                "get_my_trades",
                "my trades",
                _schema(
                    {
                        "symbol": symbol_property,
                        "startTime": {"type": "integer"},
                        "endTime": {"type": "integer"},
                    },
                    ["symbol"],
                ),
            ),
            ToolDescriptor(
                "get_symbol_filters",
                "symbol filter",
                _schema({"symbol": symbol_property}, ["symbol"]),
            ),
            ToolDescriptor(
                "post_order",
                "new order",
                _schema(
                    {
                        "symbol": symbol_property,
                        "side": {"type": "string", "enum": ["BUY", "SELL"]},
                        "type": {"type": "string", "enum": ["MARKET", "LIMIT"]},
                        "quantity": {"type": ["string", "number"]},
                        "quoteOrderQty": {"type": ["string", "number"]},
                        "price": {"type": ["string", "number"]},
                        "timeInForce": {"type": "string"},
                        "newClientOrderId": {"type": "string"},
                        "newOrderRespType": {"type": "string"},
                    },
                    ["symbol", "side", "type", "newClientOrderId"],
                ),
            ),
            ToolDescriptor(
                "get_order",
                "query order",
                _schema(
                    {
                        "symbol": symbol_property,
                        "orderId": {"type": "integer"},
                        "origClientOrderId": {"type": "string"},
                    },
                    ["symbol"],
                ),
            ),
            ToolDescriptor(
                "delete_order",
                "cancel order",
                _schema(
                    {
                        "symbol": symbol_property,
                        "orderId": {"type": "integer"},
                        "origClientOrderId": {"type": "string"},
                    },
                    ["symbol"],
                ),
            ),
        )

    async def discover_tools(self) -> list[ToolDescriptor]:
        return list(self.tool_descriptors())

    async def close(self) -> None:
        return None

    async def call_tool(self, call: ToolCall) -> Any:
        name = call.tool.name
        if name in {"post_order", "delete_order"}:
            ensure_financial_write_allowed()
        if name == "get_exchange_info":
            return await self._request("GET", "/api/v3/exchangeInfo", {}, signed=False)
        if name == "get_ticker":
            return await self._request(
                "GET", "/api/v3/ticker/price", {"symbol": call.arguments["symbol"]}, signed=False
            )
        if name == "get_account":
            return await self._request("GET", "/api/v3/account", {}, signed=True)
        if name == "get_open_orders":
            return await self._request("GET", "/api/v3/openOrders", call.arguments, signed=True)
        if name == "get_my_trades":
            return await self._request("GET", "/api/v3/myTrades", call.arguments, signed=True)
        if name == "get_symbol_filters":
            payload = await self._request(
                "GET", "/api/v3/exchangeInfo", {"symbol": call.arguments["symbol"]}, signed=False
            )
            return self._single_symbol(payload)
        if name == "post_order":
            return await self._request("POST", "/api/v3/order", call.arguments, signed=True)
        if name == "get_order":
            return await self._request("GET", "/api/v3/order", call.arguments, signed=True)
        if name == "delete_order":
            return await self._request("DELETE", "/api/v3/order", call.arguments, signed=True)
        raise BinanceSpotApiError(f"unsupported direct Spot operation: {name}")

    async def _request(
        self, method: str, path: str, params: Mapping[str, Any], *, signed: bool
    ) -> Any:
        values = {
            key: format(value, "f") if isinstance(value, Decimal) else value
            for key, value in params.items()
            if value is not None
        }
        headers: dict[str, str] = {"X-MBX-APIKEY": self._api_key}
        if signed:
            values["timestamp"] = int(time() * 1000)
            values["recvWindow"] = self._recv_window_ms
            query, signature = build_signed_query(values, self._api_secret)
            values["signature"] = signature
            request_params: Mapping[str, Any] = dict(values)
            _ = query
        else:
            request_params = values
        try:
            async with httpx2.AsyncClient(timeout=15.0) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", params=request_params, headers=headers
                )
                response.raise_for_status()
                return response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise BinanceSpotApiError("Binance Spot API request failed") from exc

    @staticmethod
    def _single_symbol(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise BinanceSpotApiError("Binance exchangeInfo response is invalid")
        value = cast(dict[str, Any], payload)
        raw_symbols = value.get("symbols")
        symbols = cast(list[Any], raw_symbols) if isinstance(raw_symbols, list) else []
        if len(symbols) != 1 or not isinstance(symbols[0], dict):
            raise BinanceSpotApiError("Binance exchangeInfo symbol response is invalid")
        return cast(dict[str, Any], symbols[0])
