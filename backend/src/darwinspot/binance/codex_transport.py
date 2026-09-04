from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

from darwinspot.binance.client import ToolCall, ToolDescriptor
from darwinspot.config import Settings


class CodexTransportError(RuntimeError):
    pass


class CodexAuthRequired(CodexTransportError):
    pass


class CodexConfirmationRequired(CodexTransportError):
    def __init__(self, request_id: int | str, expires_at: str | None = None) -> None:
        self.request_id = request_id
        self.expires_at = expires_at
        super().__init__(f"Codex elicitation {request_id} requires explicit operator resolution")


class CodexAuthState(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    CONNECTED = "CONNECTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class CodexMcpStatus:
    name: str
    auth_state: CodexAuthState
    runtime_status: str | None
    tools: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class CodexToolResult:
    content: list[Any]
    structured_content: Any
    is_error: bool


@dataclass(frozen=True)
class CodexElicitation:
    request_id: int | str
    params: dict[str, Any]

    def require_explicit_resolution(self) -> None:
        expires_at = self.params.get("expiresAt")
        raise CodexConfirmationRequired(
            self.request_id, expires_at if isinstance(expires_at, str) else None
        )


ElicitationAction = Literal["accept", "decline", "cancel"]
_pending_confirmations: dict[str, tuple[CodexAppServerTransport, int | str]] = {}


def remember_pending_confirmation(
    intent_id: str, transport: CodexAppServerTransport, request_id: int | str
) -> None:
    _pending_confirmations[intent_id] = (transport, request_id)


async def resolve_pending_confirmation(
    intent_id: str, action: ElicitationAction
) -> bool:
    pending = _pending_confirmations.get(intent_id)
    if pending is None:
        return False
    transport, request_id = pending
    try:
        await transport.resolve_elicitation(request_id, action)
    except CodexTransportError:
        return False
    _pending_confirmations.pop(intent_id, None)
    return True


def _as_object(value: Any, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CodexTransportError(message)
    return cast(dict[str, Any], value)


class CodexAppServerTransport:
    """Exact 0.153.0 Codex App Server JSONL transport for Binance MCP."""

    def __init__(
        self,
        settings: Settings,
        *,
        server_name: str = "binance",
        cwd: str = "/tmp",
    ) -> None:
        self.settings = settings
        self.server_name = server_name
        self.cwd = cwd
        self.auth_state = CodexAuthState.NOT_AUTHENTICATED
        self._process: asyncio.subprocess.Process | None = None
        self._request_lock = asyncio.Lock()
        self._next_id = 1
        self._thread_id: str | None = None
        self._pending_elicitations: dict[int | str, CodexElicitation] = {}

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        try:
            command = shlex.split(self.settings.codex_app_server_command)
            if not command:
                raise CodexTransportError("CODEX_APP_SERVER_COMMAND is empty")
            await self._verify_version(command)
            if "app-server" in command:
                command.extend(
                    [
                        "-c",
                        f"mcp_servers.{self.server_name}.url={json.dumps(self.settings.binance_agent_os_mcp_url)}",
                    ]
                )
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
            )
            await self.initialize()
            await self._send_message({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        except FileNotFoundError as exc:
            self.auth_state = CodexAuthState.UNAVAILABLE
            raise CodexTransportError("Codex App Server command is unavailable") from exc
        except (TimeoutError, OSError) as exc:
            self.auth_state = CodexAuthState.UNAVAILABLE
            raise CodexTransportError("Codex App Server could not start") from exc

    async def _verify_version(self, command: list[str]) -> None:
        if Path(command[0]).name != "codex":
            return
        try:
            version_process = await asyncio.create_subprocess_exec(
                command[0],
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await asyncio.wait_for(version_process.communicate(), timeout=10)
        except (OSError, TimeoutError) as exc:
            raise CodexTransportError("Codex version could not be verified") from exc
        output_text = output.decode("utf-8", errors="replace")
        if (
            version_process.returncode != 0
            or self.settings.codex_app_server_version not in output_text
        ):
            raise CodexTransportError("Codex App Server version does not match configuration")

    async def close(self) -> None:
        process = self._process
        self._process = None
        self._thread_id = None
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def initialize(self) -> dict[str, Any]:
        result = await self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "darwinspot",
                    "title": "DARWIN Binance transport",
                    "version": "0.1.0",
                }
            },
        )
        return _as_object(result, "Codex initialize response was not an object")

    async def status(
        self, *, detail: Literal["full", "toolsAndAuthOnly"] = "full"
    ) -> CodexMcpStatus:
        if self._process is None or self._process.returncode is not None:
            await self.start()
        result = await self._request("mcpServerStatus/list", {"detail": detail})
        status = self.parse_status(result, self.server_name)
        self.auth_state = status.auth_state
        return status

    async def oauth_login(self, *, scopes: list[str] | None = None) -> str:
        if self._process is None or self._process.returncode is not None:
            await self.start()
        params: dict[str, Any] = {"name": self.server_name}
        if scopes is not None:
            params["scopes"] = scopes
        result = _as_object(
            await self._request("mcpServer/oauth/login", params), "invalid OAuth response"
        )
        authorization_url = result.get("authorizationUrl")
        if not isinstance(authorization_url, str) or not authorization_url:
            raise CodexTransportError("Codex OAuth response omitted authorizationUrl")
        return authorization_url

    async def call_tool(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        thread_id: str | None = None,
    ) -> CodexToolResult:
        status = await self.status(detail="toolsAndAuthOnly")
        if status.auth_state != CodexAuthState.CONNECTED:
            raise CodexAuthRequired("Binance Agent OS authentication is required")
        active_thread = thread_id or self._thread_id
        if active_thread is None:
            active_thread = await self._start_read_only_thread()
        result = await self._request(
            "mcpServer/tool/call",
            {
                "server": self.server_name,
                "threadId": active_thread,
                "tool": tool,
                "arguments": arguments,
            },
        )
        return self.parse_tool_result(result)

    async def resolve_elicitation(
        self,
        request_id: int | str,
        action: ElicitationAction,
        content: Any = None,
    ) -> None:
        if action not in {"accept", "decline", "cancel"}:
            raise ValueError("elicitation action must be accept, decline, or cancel")
        result: dict[str, Any] = {"action": action}
        if content is not None:
            result["content"] = content
        await self._send_response(request_id, result)
        self._pending_elicitations.pop(request_id, None)

    async def _start_read_only_thread(self) -> str:
        result = _as_object(
            await self._request(
                "thread/start",
                {
                    "ephemeral": True,
                    "cwd": self.cwd,
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                },
            ),
            "Codex thread/start response was not an object",
        )
        thread = _as_object(result.get("thread"), "Codex thread/start omitted thread")
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise CodexTransportError("Codex thread/start omitted thread id")
        self._thread_id = thread_id
        return thread_id

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        async with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            await self._send_message(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            while True:
                message = await self._read_message()
                if message.get("id") == request_id:
                    if "error" in message:
                        raise CodexTransportError(f"Codex {method} request failed")
                    return message.get("result")
                await self._handle_message(message)

    async def _send_response(self, request_id: int | str, result: dict[str, Any]) -> None:
        async with self._request_lock:
            await self._send_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def _send_message(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            self.auth_state = CodexAuthState.UNAVAILABLE
            raise CodexTransportError("Codex App Server is not running")
        self._process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
        await self._process.stdin.drain()

    async def _read_message(self) -> dict[str, Any]:
        if self._process is None or self._process.stdout is None:
            self.auth_state = CodexAuthState.UNAVAILABLE
            raise CodexTransportError("Codex App Server is not running")
        raw = await asyncio.wait_for(self._process.stdout.readline(), timeout=60)
        if not raw:
            self.auth_state = CodexAuthState.UNAVAILABLE
            raise CodexTransportError("Codex App Server closed its output")
        try:
            return _as_object(json.loads(raw), "Codex App Server returned invalid JSON")
        except json.JSONDecodeError as exc:
            raise CodexTransportError("Codex App Server returned invalid JSON") from exc

    async def _handle_message(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method == "mcpServer/elicitation/request" and "id" in message:
            request_id = message["id"]
            if not isinstance(request_id, (str, int)):
                raise CodexTransportError("Codex elicitation request id is invalid")
            params = _as_object(message.get("params"), "Codex elicitation params are invalid")
            elicitation = self.parse_elicitation(request_id, params)
            self._pending_elicitations[request_id] = elicitation
            elicitation.require_explicit_resolution()
        elif method == "mcpServer/oauthLogin/completed":
            params = message.get("params")
            params = cast(dict[str, Any], params) if isinstance(params, dict) else {}
            if params.get("success") is True:
                self.auth_state = CodexAuthState.CONNECTED

    @staticmethod
    def parse_status(payload: Any, server_name: str) -> CodexMcpStatus:
        value = _as_object(payload, "Codex MCP status response is invalid")
        raw_data = value.get("data")
        if not isinstance(raw_data, list):
            raise CodexTransportError("Codex MCP status response omitted data")
        data = cast(list[Any], raw_data)
        entry: dict[str, Any] | None = None
        for item in data:
            if isinstance(item, dict):
                candidate = cast(dict[str, Any], item)
                if candidate.get("name") == server_name:
                    entry = candidate
                    break
        if entry is None:
            return CodexMcpStatus(server_name, CodexAuthState.UNAVAILABLE, None, {}, {})
        auth_status = entry.get("authStatus")
        if auth_status in {"oAuth", "bearerToken"}:
            auth_state = CodexAuthState.CONNECTED
        elif auth_status == "notLoggedIn":
            auth_state = CodexAuthState.AUTH_REQUIRED
        else:
            auth_state = CodexAuthState.NOT_AUTHENTICATED
        raw_tools = entry.get("tools")
        tools = cast(dict[str, Any], raw_tools) if isinstance(raw_tools, dict) else {}
        raw_runtime_status = entry.get("runtimeStatus")
        return CodexMcpStatus(
            name=server_name,
            auth_state=auth_state,
            runtime_status=raw_runtime_status if isinstance(raw_runtime_status, str) else None,
            tools=tools,
            raw=entry,
        )

    @staticmethod
    def parse_tool_result(payload: Any) -> CodexToolResult:
        value = _as_object(payload, "Codex MCP tool response is invalid")
        raw_content = value.get("content")
        if not isinstance(raw_content, list):
            raise CodexTransportError("Codex MCP tool response omitted content")
        content = cast(list[Any], raw_content)
        return CodexToolResult(
            content=content,
            structured_content=value.get("structuredContent"),
            is_error=value.get("isError") is True,
        )

    @staticmethod
    def parse_elicitation(request_id: int | str, payload: Any) -> CodexElicitation:
        value = _as_object(payload, "Codex elicitation payload is invalid")
        if not isinstance(value.get("serverName"), str) or not isinstance(
            value.get("threadId"), str
        ):
            raise CodexTransportError("Codex elicitation omitted serverName or threadId")
        return CodexElicitation(request_id=request_id, params=value)


class CodexBinanceClient:
    """Binance client facade preserving DARWIN's discovered-tool interface."""

    def __init__(self, transport: CodexAppServerTransport) -> None:
        self.transport = transport

    async def discover_tools(self) -> list[ToolDescriptor]:
        status = await self.transport.status(detail="full")
        if status.auth_state != CodexAuthState.CONNECTED:
            raise CodexAuthRequired("Binance Agent OS authentication is required")
        descriptors: list[ToolDescriptor] = []
        for name, raw in status.tools.items():
            tool = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
            raw_schema = tool.get("inputSchema")
            schema = cast(dict[str, Any], raw_schema) if isinstance(raw_schema, dict) else {}
            descriptors.append(
                ToolDescriptor(
                    name=name,
                    description=str(tool.get("description") or ""),
                    input_schema=schema,
                )
            )
        if not descriptors:
            raise CodexTransportError("Codex reported no authenticated Binance tools")
        return descriptors

    async def call_tool(self, call: ToolCall) -> Any:
        if self._is_write(call.tool):
            if not self.transport.settings.codex_write_confirmation_verified:
                raise CodexTransportError(
                    "Binance write confirmation capability is unverified; write blocked"
                )
        result = await self.transport.call_tool(tool=call.tool.name, arguments=call.arguments)
        if result.is_error:
            raise CodexTransportError(f"Codex Binance tool {call.tool.name} returned an error")
        if result.structured_content is not None:
            return result.structured_content
        values: list[Any] = []
        for item in result.content:
            if not isinstance(item, dict):
                continue
            item_value = cast(dict[str, Any], item)
            if not isinstance(item_value.get("text"), str):
                continue
            try:
                values.append(json.loads(item_value["text"]))
            except json.JSONDecodeError as exc:
                raise CodexTransportError("Codex Binance tool returned non-JSON content") from exc
        if len(values) != 1:
            raise CodexTransportError("Codex Binance tool returned unsupported content")
        return values[0]

    @staticmethod
    def _is_write(tool: ToolDescriptor) -> bool:
        text = f"{tool.name} {tool.description}".lower()
        return any(
            marker in text
            for marker in (
                "order.place",
                "place_order",
                "new_order",
                "cancel_order",
                "order.cancel",
                "withdraw",
                "transfer",
            )
        )
