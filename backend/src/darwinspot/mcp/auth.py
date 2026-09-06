from __future__ import annotations

import hmac
import threading
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from darwinspot.config import Settings


@dataclass(frozen=True)
class McpPrincipal:
    """Authenticated owner principal for the private MCP control plane."""

    subject: str = "mcp-owner"
    auth_method: str = "bearer"


def parse_bearer_token(authorization: str | None) -> str | None:
    """Return the exact bearer token from an Authorization header, if valid."""
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme != "Bearer" or not token or any(char.isspace() for char in token):
        return None
    return token


def authorization_header(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name.lower() == b"authorization":
            return value.decode("latin-1")
    return None


def authenticate_request(
    headers: list[tuple[bytes, bytes]], settings: Settings
) -> McpPrincipal | None:
    configured = settings.darwin_mcp_bearer_token
    supplied = parse_bearer_token(authorization_header(headers))
    if configured is None or supplied is None:
        return None
    if not hmac.compare_digest(supplied, configured):
        return None
    return McpPrincipal()


class FixedWindowLimiter:
    """Bound private single-instance MCP traffic without persisting credentials."""

    def __init__(self, *, max_requests: int = 120, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._window_started = time.monotonic()
        self._requests = 0

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._window_started >= self.window_seconds:
                self._window_started = now
                self._requests = 0
            if self._requests >= self.max_requests:
                return False
            self._requests += 1
            return True


class BearerAuthMiddleware:
    """Private MCP bearer gate that strips credentials before SDK handling."""

    def __init__(self, app: Any, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.limiter = FixedWindowLimiter()

    @asynccontextmanager
    async def lifespan_context(self) -> AsyncGenerator[None]:
        async with self.app.router.lifespan_context(self.app):
            yield

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = list(scope.get("headers", []))
        if authenticate_request(headers, self.settings) is None:
            await self._reject(send, status=401, detail="MCP authentication required")
            return
        if not self.limiter.allow():
            await self._reject(send, status=429, detail="MCP rate limit exceeded", challenge=False)
            return
        sanitized_scope = dict(scope)
        sanitized_scope["headers"] = [
            (name, value) for name, value in headers if name.lower() != b"authorization"
        ]
        await self.app(sanitized_scope, receive, send)

    @staticmethod
    async def _reject(
        send: Any,
        *,
        status: int,
        detail: str,
        challenge: bool = True,
    ) -> None:
        body = ('{"detail":"' + detail + '"}').encode("utf-8")
        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if challenge:
            response_headers.append((b"www-authenticate", b'Bearer realm="darwin-mcp"'))
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": response_headers,
            }
        )
        await send({"type": "http.response.body", "body": body})
