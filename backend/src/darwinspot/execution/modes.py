from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ExecutionMode(StrEnum):
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    AUTO_BOUNDED = "AUTO_BOUNDED"


class ExecutionTransport(StrEnum):
    CODEX_AGENT_OS_MCP = "CODEX_AGENT_OS_MCP"
    BINANCE_SPOT_API = "BINANCE_SPOT_API"


class AuthorizationSource(StrEnum):
    TELEGRAM = "TELEGRAM"
    WEB = "WEB"
    MCP = "MCP"
    AUTO_POLICY = "AUTO_POLICY"


@dataclass(frozen=True)
class ExecutionMetadata:
    mode: ExecutionMode
    transport: ExecutionTransport
    authorization_source: AuthorizationSource | None
    authorized_at: datetime | None = None


def metadata_for_mode(
    mode: ExecutionMode,
    authorization_source: AuthorizationSource | None = None,
    authorized_at: datetime | None = None,
) -> ExecutionMetadata:
    if mode == ExecutionMode.HUMAN_APPROVAL:
        if authorization_source not in {
            None,
            AuthorizationSource.TELEGRAM,
            AuthorizationSource.WEB,
            AuthorizationSource.MCP,
        }:
            raise ValueError("human approval requires TELEGRAM, WEB, or MCP authorization")
        return ExecutionMetadata(
            mode=mode,
            transport=ExecutionTransport.CODEX_AGENT_OS_MCP,
            authorization_source=authorization_source,
            authorized_at=authorized_at,
        )
    if authorization_source not in {None, AuthorizationSource.AUTO_POLICY}:
        raise ValueError("auto bounded execution requires AUTO_POLICY authorization")
    return ExecutionMetadata(
        mode=mode,
        transport=ExecutionTransport.BINANCE_SPOT_API,
        authorization_source=authorization_source,
        authorized_at=authorized_at,
    )
