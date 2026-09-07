from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncGenerator, Callable, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import httpx2
from jsonschema import Draft202012Validator, SchemaError
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, OAuthFlowError, OAuthTokenError, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl, TypeAdapter

from darwinspot.observability import log_event
from darwinspot.security.encryption import decrypt_connection_material, encrypt_connection_material
from darwinspot.storage.database import SessionLocal
from darwinspot.storage.models import BinanceConnection, TradeIntent


class AgentOSUnavailable(RuntimeError):
    pass


class UnsupportedCapability(AgentOSUnavailable):
    pass


class AgentOSAuthInvalid(AgentOSUnavailable):
    pass


def _is_auth_invalid(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OAuthTokenError):
            status_match = re.search(r"\((\d{3})\)", str(current))
            if status_match is not None and int(status_match.group(1)) >= 500:
                return False
            return True
        if isinstance(current, httpx2.HTTPStatusError):
            response = current.response
            if response.status_code == 401:
                return True
            if response.status_code == 403:
                challenge = response.headers.get("WWW-Authenticate", "").lower()
                if "invalid_token" in challenge or "revoked" in challenge:
                    return True
        if isinstance(current, OAuthFlowError):
            message = str(current).lower()
            if "no redirect handler" in message or "no authorization code" in message:
                return True
        message = str(current).lower()
        if "invalid_token" in message or "invalid_grant" in message or "revoked" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


@dataclass(frozen=True)
class ToolDescriptor:
    """The exact tool descriptor returned by MCP tools/list."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    tool: ToolDescriptor
    arguments: dict[str, Any]


class DatabaseOAuthStorage(TokenStorage):
    """Encrypted MCP OAuth token/client storage scoped to one connection."""

    def __init__(self, connection_id: str, encryption_key: str) -> None:
        self.connection_id = connection_id
        self.encryption_key = encryption_key

    def _read(self) -> dict[str, Any]:
        with SessionLocal() as db:
            connection = db.get(BinanceConnection, self.connection_id)
            if connection is None or connection.encrypted_material is None:
                return {}
            raw = decrypt_connection_material(connection.encrypted_material, self.encryption_key)
        return TypeAdapter(dict[str, object]).validate_json(raw)

    def _write(self, value: dict[str, Any]) -> None:
        encrypted = encrypt_connection_material(
            json.dumps(value, default=str, sort_keys=True), self.encryption_key
        )
        with SessionLocal() as db:
            connection = db.get(BinanceConnection, self.connection_id)
            if connection is None:
                raise ValueError("connection not found")
            connection.encrypted_material = encrypted
            db.commit()

    async def get_tokens(self) -> OAuthToken | None:
        stored = self._read()
        value = stored.get("tokens")
        if not isinstance(value, dict):
            return None
        tokens = OAuthToken.model_validate(value)
        stored_at = stored.get("tokens_stored_at")
        if (
            isinstance(stored_at, (int, float))
            and tokens.expires_in is not None
            and time.time() >= stored_at + tokens.expires_in
            and not tokens.refresh_token
        ):
            log_event("CONNECTION_EXPIRED", connection_id=self.connection_id)
        return tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        value = self._read()
        value["tokens"] = tokens.model_dump(mode="json")
        value["tokens_stored_at"] = time.time()
        self._write(value)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        value = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(value) if isinstance(value, dict) else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        value = self._read()
        value["client_info"] = client_info.model_dump(mode="json")
        self._write(value)


class ToolCatalog:
    """Resolve only capabilities actually returned by the connected MCP server."""

    _forbidden = (
        "withdraw",
        "transfer",
        "futures",
        "future",
        "margin",
        "option",
        "leverage",
    )
    _patterns = {
        "market_universe": (
            "exchange information",
            "exchange_info",
            "exchangeinfo",
            "all symbols",
            "ticker",
            "market data",
        ),
        "market": ("symbol price ticker", "ticker", "price", "market data", "kline"),
        "balances": ("account information", "balance", "account"),
        "open_orders": ("open order", "open_orders", "openorders"),
        "submit_order": (
            "new order",
            "new_order",
            "place order",
            "place_order",
            "order.place",
            "submit order",
            "send in a new order",
        ),
        "cancel_order": (
            "cancel an active order",
            "cancel order",
            "cancel_order",
            "order.cancel",
        ),
        "order_status": (
            "check an order's status",
            "query order",
            "query_order",
            "order.status",
            "order status",
        ),
        "symbol_filters": (
            "exchange information",
            "exchangeinfo",
            "exchange_info",
            "symbol filter",
            "relevant filters",
        ),
        "recent_activity": ("my trades", "mytrades", "trade history"),
    }
    _read_operations = {
        "market_universe",
        "market",
        "balances",
        "open_orders",
        "order_status",
        "symbol_filters",
        "recent_activity",
    }

    def __init__(self, tools: Sequence[ToolDescriptor | str]) -> None:
        self.tools = tuple(
            tool
            if isinstance(tool, ToolDescriptor)
            else ToolDescriptor(name=tool, description="", input_schema={})
            for tool in tools
        )

    @classmethod
    def is_permitted(cls, name: str, description: str = "") -> bool:
        lowered_name = name.lower()
        return lowered_name.startswith("spot.") and not any(
            part in lowered_name for part in cls._forbidden
        )

    @property
    def permitted_names(self) -> tuple[str, ...]:
        return tuple(
            tool.name for tool in self.tools if self.is_permitted(tool.name, tool.description)
        )

    def resolve(self, operation: str) -> ToolDescriptor:
        patterns = self._patterns.get(operation)
        if patterns is None:
            raise UnsupportedCapability(f"unsupported internal operation: {operation}")
        candidates: list[tuple[int, ToolDescriptor]] = []
        for tool in self.tools:
            if not self.is_permitted(tool.name, tool.description):
                continue
            if operation == "market_universe" and "symbol" in self._required(tool):
                continue
            if operation == "symbol_filters" and "symbol" not in self._properties(tool):
                continue
            text = f"{tool.name} {tool.description}".lower()
            if operation in self._read_operations and "(trade)" in text:
                continue
            if operation in {"submit_order", "cancel_order"} and "(trade)" not in text:
                continue
            if operation == "submit_order" and "test" in text:
                continue
            if operation == "market" and "order" in text:
                continue
            score = sum(2 if pattern in text else 0 for pattern in patterns)
            if score > 0:
                candidates.append((score, tool))
        if not candidates:
            raise UnsupportedCapability(f"Agent OS did not expose a permitted {operation} tool")
        highest = max(score for score, _ in candidates)
        best = [tool for score, tool in candidates if score == highest]
        if len(best) != 1:
            raise UnsupportedCapability(f"Agent OS exposed ambiguous tools for {operation}")
        return best[0]

    @staticmethod
    def _properties(tool: ToolDescriptor) -> dict[str, Any]:
        properties = tool.input_schema.get("properties")
        if not isinstance(properties, dict):
            raise UnsupportedCapability(f"MCP tool {tool.name} has no usable input schema")
        return cast(dict[str, Any], properties)

    @staticmethod
    def _required(tool: ToolDescriptor) -> set[str]:
        required = tool.input_schema.get("required", [])
        if not isinstance(required, list):
            raise UnsupportedCapability(f"MCP tool {tool.name} has an invalid required schema")
        required_items = cast(list[Any], required)
        if not all(isinstance(item, str) for item in required_items):
            raise UnsupportedCapability(f"MCP tool {tool.name} has an invalid required schema")
        return set(cast(list[str], required_items))

    def validate_arguments(self, tool: ToolDescriptor, arguments: dict[str, Any]) -> dict[str, Any]:
        properties = self._properties(tool)
        required = self._required(tool)
        if any(value is None for value in arguments.values()):
            raise UnsupportedCapability(f"MCP tool {tool.name} payload contains null")
        unknown = set(arguments) - set(properties)
        if unknown:
            raise UnsupportedCapability(
                f"MCP tool {tool.name} does not declare fields: {sorted(unknown)}"
            )
        missing = required - set(arguments)
        if missing:
            raise UnsupportedCapability(
                f"MCP tool {tool.name} requires unsupported fields: {sorted(missing)}"
            )
        try:
            Draft202012Validator.check_schema(tool.input_schema)
            validator = Draft202012Validator(tool.input_schema)
            iter_errors = cast(
                Callable[[Mapping[str, Any]], Iterator[Any]],
                validator.iter_errors,  # pyright: ignore[reportUnknownMemberType]
            )
            schema_errors = sorted(
                iter_errors(cast(Mapping[str, Any], arguments)),
                key=lambda error: list(error.path),
            )
        except SchemaError as exc:
            raise UnsupportedCapability(f"MCP tool {tool.name} has an invalid JSON schema") from exc
        if schema_errors:
            raise UnsupportedCapability(
                f"MCP tool {tool.name} arguments failed JSON schema validation: "
                f"{schema_errors[0].message}"
            )
        return arguments

    def _put(
        self,
        tool: ToolDescriptor,
        arguments: dict[str, Any],
        field: str,
        value: Any,
        *,
        required: bool = False,
    ) -> None:
        if value is None:
            if required:
                raise UnsupportedCapability(f"MCP tool {tool.name} requires {field}")
            return
        if field not in self._properties(tool):
            if required:
                raise UnsupportedCapability(f"MCP tool {tool.name} does not declare {field}")
            return
        arguments[field] = value

    def arguments(self, operation: str, values: Mapping[str, Any]) -> ToolCall:
        tool = self.resolve(operation)
        arguments: dict[str, Any] = {}
        if operation == "market_universe":
            self._put(tool, arguments, "symbols", values.get("symbols"), required=False)
        elif operation in {"market", "symbol_filters", "open_orders"}:
            self._put(
                tool,
                arguments,
                "symbol",
                values.get("symbol"),
                required=operation in {"market", "symbol_filters"},
            )
        elif operation == "balances":
            pass
        elif operation == "recent_activity":
            self._put(tool, arguments, "symbol", values.get("symbol"), required=True)
            self._put(tool, arguments, "startTime", values.get("startTime"), required=False)
            self._put(tool, arguments, "endTime", values.get("endTime"), required=False)
        elif operation == "order_status":
            self._put(tool, arguments, "symbol", values.get("symbol"), required=True)
            self._put_order_reference(
                tool,
                arguments,
                values.get("order_id"),
                values.get("client_order_id"),
            )
        elif operation == "cancel_order":
            self._put(tool, arguments, "symbol", values.get("symbol"), required=True)
            self._put_order_reference(
                tool,
                arguments,
                values.get("order_id"),
                values.get("client_order_id"),
            )
        elif operation == "submit_order":
            intent = values.get("intent")
            if not isinstance(intent, TradeIntent):
                raise ValueError("submit_order requires a TradeIntent")
            self._put(tool, arguments, "symbol", intent.pair, required=True)
            self._put(tool, arguments, "side", intent.side, required=True)
            self._put(tool, arguments, "type", intent.order_type, required=True)
            if intent.side == "BUY" and intent.order_type == "MARKET":
                self._put(
                    tool, arguments, "quoteOrderQty", intent.committed_notional, required=True
                )
            else:
                self._put(tool, arguments, "quantity", intent.quantity, required=True)
            if intent.order_type == "LIMIT":
                self._put(tool, arguments, "price", intent.price, required=True)
                self._put(tool, arguments, "timeInForce", "GTC", required=False)
            self._put(tool, arguments, "newClientOrderId", intent.idempotency_key, required=True)
            self._put(tool, arguments, "newOrderRespType", "FULL", required=False)
        else:
            raise UnsupportedCapability(f"unsupported internal operation: {operation}")
        return ToolCall(tool, self.validate_arguments(tool, arguments))

    def _put_order_reference(
        self,
        tool: ToolDescriptor,
        arguments: dict[str, Any],
        order_id: Any,
        client_order_id: Any,
    ) -> None:
        properties = self._properties(tool)
        if isinstance(order_id, str) and order_id.isdigit() and "orderId" in properties:
            arguments["orderId"] = int(order_id)
        elif (
            isinstance(client_order_id, str)
            and client_order_id
            and "origClientOrderId" in properties
        ):
            arguments["origClientOrderId"] = client_order_id
        else:
            raise UnsupportedCapability(f"MCP tool {tool.name} has no supported order identifier")


class BinanceAgentOSClient:
    """MCP client for Binance Agent OS over the official Streamable HTTP endpoint."""

    def __init__(self, endpoint: str, access_token: str | None = None) -> None:
        self.endpoint = endpoint
        self.access_token = access_token
        self.auth_provider: httpx2.Auth | None = None

    @classmethod
    def with_oauth(
        cls,
        endpoint: str,
        connection_id: str,
        encryption_key: str,
        callback_url: str,
        client_metadata_url: str,
    ) -> BinanceAgentOSClient:
        metadata = OAuthClientMetadata(
            response_types=["code"],
            client_name="DarwinSpot",
            redirect_uris=[TypeAdapter(AnyUrl).validate_python(callback_url)],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            application_type="web",
        )
        storage = DatabaseOAuthStorage(connection_id, encryption_key)
        client = cls(endpoint)
        client.auth_provider = OAuthClientProvider(
            endpoint,
            metadata,
            storage,
            client_metadata_url=client_metadata_url,
        )
        return client

    @classmethod
    def with_provider(cls, endpoint: str, provider: httpx2.Auth) -> BinanceAgentOSClient:
        client = cls(endpoint)
        client.auth_provider = provider
        return client

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[ClientSession]:
        headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else None
        try:
            async with httpx2.AsyncClient(
                headers=headers, timeout=30.0, auth=self.auth_provider
            ) as http_client:
                async with streamable_http_client(self.endpoint, http_client=http_client) as (
                    read,
                    write,
                ):
                    client = ClientSession(read, write)
                    async with client:
                        await client.initialize()
                        yield client
        except AgentOSAuthInvalid:
            raise
        except Exception as exc:
            if _is_auth_invalid(exc):
                raise AgentOSAuthInvalid(
                    "Binance Agent OS authorization is invalid or revoked"
                ) from exc
            raise AgentOSUnavailable("Binance Agent OS MCP session is unavailable") from exc

    async def discover_tools(self) -> list[ToolDescriptor]:
        async with self.session() as client:
            result = await client.list_tools()
            tools: list[ToolDescriptor] = []
            for tool in result.tools:
                schema = getattr(tool, "inputSchema", None)
                if not isinstance(schema, dict):
                    raise AgentOSUnavailable(f"MCP tool {tool.name} has no input schema")
                input_schema = cast(dict[str, Any], schema)
                tools.append(
                    ToolDescriptor(
                        name=tool.name,
                        description=getattr(tool, "description", "") or "",
                        input_schema=input_schema,
                    )
                )
            if not tools:
                raise AgentOSUnavailable("Binance Agent OS returned no MCP tools")
            return tools

    async def call_tool(self, call: ToolCall) -> Any:
        ToolCatalog((call.tool,)).validate_arguments(call.tool, call.arguments)
        async with self.session() as client:
            result = await client.call_tool(call.tool.name, call.arguments)
            if getattr(result, "isError", False) or getattr(result, "is_error", False):
                raise AgentOSUnavailable(
                    f"Binance Agent OS tool {call.tool.name} returned an error"
                )
            structured = getattr(result, "structuredContent", None)
            if structured is not None:
                return structured
            values: list[Any] = []
            for item in getattr(result, "content", []):
                text = getattr(item, "text", None)
                if text is not None:
                    try:
                        values.append(json.loads(text))
                    except json.JSONDecodeError as exc:
                        raise AgentOSUnavailable(
                            f"Binance Agent OS tool {call.tool.name} returned non-JSON content"
                        ) from exc
            if len(values) != 1:
                raise AgentOSUnavailable("Agent OS returned an unsupported tool response")
            return values[0]
