from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from darwinspot.config import Settings
from darwinspot.mcp.auth import BearerAuthMiddleware
from darwinspot.mcp.tools import register_tools

MCP_NAME = "darwin"
MCP_VERSION = "0.1.0"


def build_mcp_server() -> MCPServer[Any]:
    server = MCPServer(
        name=MCP_NAME,
        version=MCP_VERSION,
        instructions=(
            "DARWIN HUMAN_APPROVAL control plane. External hosts may reason and propose; "
            "DARWIN remains the deterministic authorization authority."
        ),
        log_level="INFO",
    )
    register_tools(server)
    return server


def build_mcp_app(settings: Settings) -> Any:
    server = build_mcp_server()
    app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
        max_request_body_size=1024 * 1024,
    )
    return BearerAuthMiddleware(app, settings)
