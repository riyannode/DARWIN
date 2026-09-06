from __future__ import annotations

# MCP tool descriptions are intentionally prose-rich and are presented verbatim to hosts.
# ruff: noqa: E501
# pyright: reportUnusedFunction=false
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from fastapi import HTTPException
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from sqlalchemy.orm import Session

from darwinspot.agent.mandate import MandateInput
from darwinspot.application.human_approval import (
    HumanApprovalApplication,
    ProposalInput,
    SubmitProposalInput,
)
from darwinspot.application.owner_controls import (
    emergency_stop,
    update_budget,
    update_mandate,
    update_universe,
)
from darwinspot.application.projections import (
    activity_projection,
    budget_projection,
    latest_decision_projection,
    mandate_projection,
    pending_trades_projection,
    status_projection,
    universe_projection,
)
from darwinspot.binance.client import AgentOSUnavailable, ToolCatalog
from darwinspot.binance.factory import build_binance_client
from darwinspot.binance.mapper import map_spot_market_universe
from darwinspot.config import get_settings
from darwinspot.execution.modes import ExecutionMode
from darwinspot.storage.database import SessionLocal
from darwinspot.storage.repository import Repository


def _result(value: Any) -> dict[str, Any]:
    return value


def _error(message: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        CallToolResult(
            is_error=True,
            content=[TextContent(type="text", text=message)],
        ),
    )


def _approval_result(value: Any) -> dict[str, Any]:
    return _result(
        {
            "approvalId": value.approval_id,
            "intentId": value.intent_id,
            "approvalState": value.approval_status,
            "intentState": value.intent_state,
            "changed": value.changed,
        }
    )


def _with_db() -> Session:
    return SessionLocal()


def _proposal(
    *,
    symbol: str,
    side: Literal["BUY", "SELL"],
    order_type: Literal["MARKET", "LIMIT"],
    quantity: Decimal | None,
    intended_notional: Decimal | None,
    price: Decimal | None,
    confidence: Decimal | None,
    rationale: str,
    supporting_factors: list[str] | None,
    risk_factors: list[str] | None,
) -> ProposalInput:
    return ProposalInput(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        intended_notional=intended_notional,
        price=price,
        confidence=confidence,
        rationale=rationale,
        supporting_factors=supporting_factors or [],
        risk_factors=risk_factors or [],
    )


async def _get_universe() -> dict[str, Any]:
    with _with_db() as db:
        base = universe_projection(db)
        repo = Repository(db)
        client: Any = None
        try:
            client = build_binance_client(
                get_settings(), repo.current_connection(), mode=ExecutionMode.HUMAN_APPROVAL
            )
            catalog = ToolCatalog(await client.discover_tools())
            live = map_spot_market_universe(
                await client.call_tool(catalog.arguments("market_universe", {}))
            )
            allowed = set(base["allowedSymbols"])
            configured = set(base["configuredSymbols"])
            effective = sorted(
                str(item["symbol"])
                for item in live
                if str(item.get("symbol")) in configured
                and str(item.get("symbol")) in allowed
                and item.get("quote_asset", item.get("quoteAsset")) == "USDT"
                and item.get("status") == "TRADING"
            )
            base["effectiveSymbols"] = effective
            base["liveState"] = "FRESH"
            return base
        except (AgentOSUnavailable, ValueError, RuntimeError):
            base["liveState"] = "UNAVAILABLE"
            return base
        finally:
            transport = getattr(client, "transport", None)
            if transport is not None:
                await transport.close()


def register_tools(server: MCPServer[Any]) -> None:
    def readonly(title: str, *, open_world: bool = False) -> ToolAnnotations:
        return ToolAnnotations(
            title=title,
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=open_world,
        )

    def mutation(
        title: str, *, destructive: bool = True, idempotent: bool = True
    ) -> ToolAnnotations:
        return ToolAnnotations(
            title=title,
            read_only_hint=False,
            destructive_hint=destructive,
            idempotent_hint=idempotent,
            open_world_hint=False,
        )

    @server.tool(
        name="darwin.get_status",
        title="DARWIN status",
        description="Read the bounded current DARWIN mode, state, emergency stop, and latest decision projection.",
        annotations=readonly("DARWIN status"),
        structured_output=True,
    )
    def get_status() -> dict[str, Any]:
        with _with_db() as db:
            return _result(status_projection(db))

    @server.tool(
        name="darwin.get_mandate",
        title="DARWIN trading mandate",
        description="Read the current versioned Trading Mandate and deterministic limits without credentials or hidden reasoning.",
        annotations=readonly("DARWIN trading mandate"),
        structured_output=True,
    )
    def get_mandate() -> dict[str, Any]:
        with _with_db() as db:
            return _result(mandate_projection(db))

    @server.tool(
        name="darwin.get_budget",
        title="DARWIN budget",
        description="Read the current rolling 24-hour budget, available budget, and spent amount.",
        annotations=readonly("DARWIN budget"),
        structured_output=True,
    )
    def get_budget() -> dict[str, Any]:
        with _with_db() as db:
            return _result(budget_projection(db))

    @server.tool(
        name="darwin.get_universe",
        title="DARWIN trading universe",
        description="Read configured, allowed, and live-effective Binance Spot/USDT universe state.",
        annotations=readonly("DARWIN trading universe", open_world=True),
        structured_output=True,
    )
    async def get_universe() -> dict[str, Any]:
        return _result(await _get_universe())

    @server.tool(
        name="darwin.get_portfolio",
        title="DARWIN portfolio",
        description="Read the existing safe live portfolio projection; credentials and provider headers are never returned.",
        annotations=readonly("DARWIN portfolio", open_world=True),
        structured_output=True,
    )
    async def get_portfolio() -> dict[str, Any]:
        from darwinspot.api.portfolio import get_portfolio as route_get_portfolio

        with _with_db() as db:
            try:
                return _result(await route_get_portfolio(None, db))
            except (HTTPException, AgentOSUnavailable, ValueError, RuntimeError):
                return _error("portfolio is currently unavailable")

    @server.tool(
        name="darwin.get_latest_decision",
        title="DARWIN latest decision",
        description="Read the latest completed decision projection without raw evidence blobs or hidden reasoning.",
        annotations=readonly("DARWIN latest decision"),
        structured_output=True,
    )
    def get_latest_decision() -> dict[str, Any]:
        with _with_db() as db:
            return _result(latest_decision_projection(Repository(db).latest_decision_run()))

    @server.tool(
        name="darwin.get_activity",
        title="DARWIN activity",
        description="Read a bounded newest-first activity projection. The hard limit is 50 items.",
        annotations=readonly("DARWIN activity"),
        structured_output=True,
    )
    def get_activity(limit: int = 25) -> dict[str, Any]:
        with _with_db() as db:
            bounded_limit = max(1, min(limit, 50))
            return _result(
                {
                    "items": activity_projection(db, limit=bounded_limit),
                    "limit": bounded_limit,
                }
            )

    @server.tool(
        name="darwin.list_pending_trades",
        title="DARWIN pending trades",
        description="List bounded opaque trade references and approval states; financial arguments are not accepted from the caller.",
        annotations=readonly("DARWIN pending trades"),
        structured_output=True,
    )
    def list_pending_trades(limit: int = 25) -> dict[str, Any]:
        with _with_db() as db:
            bounded_limit = max(1, min(limit, 50))
            return _result(
                {
                    "items": pending_trades_projection(db, limit=bounded_limit),
                    "limit": bounded_limit,
                }
            )

    @server.tool(
        name="darwin.validate_proposal",
        title="Validate DARWIN proposal",
        description="Dry-run an untrusted host proposal against fresh DARWIN mandate, universe, budget, balance, filter, freshness, open-order, emergency-stop, and write-gate state. Creates no intent or approval.",
        annotations=readonly("Validate DARWIN proposal", open_world=True),
        structured_output=True,
    )
    async def validate_proposal(
        symbol: Annotated[str, Field(pattern=r"^[A-Z0-9]{5,20}$")],
        side: Literal["BUY", "SELL"],
        order_type: Literal["MARKET", "LIMIT"] = "MARKET",
        quantity: Decimal | None = None,
        intended_notional: Decimal | None = None,
        price: Decimal | None = None,
        confidence: Decimal | None = None,
        rationale: str = "",
        supporting_factors: list[str] | None = None,
        risk_factors: list[str] | None = None,
    ) -> dict[str, Any]:
        proposal = _proposal(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            intended_notional=intended_notional,
            price=price,
            confidence=confidence,
            rationale=rationale,
            supporting_factors=supporting_factors,
            risk_factors=risk_factors,
        )
        with _with_db() as db:
            result = await HumanApprovalApplication(db).validate_proposal(proposal)
            return _result(result.as_dict())

    @server.tool(
        name="darwin.submit_proposal",
        title="Submit DARWIN proposal",
        description="Admit an untrusted host proposal into durable HUMAN_APPROVAL only after fresh server-side validation. Requires an explicit idempotency key and stops at WAITING_FOR_APPROVAL; it never places an order.",
        annotations=mutation("Submit DARWIN proposal", destructive=False, idempotent=True),
        structured_output=True,
    )
    async def submit_proposal(
        symbol: Annotated[str, Field(pattern=r"^[A-Z0-9]{5,20}$")],
        side: Literal["BUY", "SELL"],
        idempotency_key: Annotated[
            str,
            Field(min_length=36, max_length=36, pattern=r"^[0-9a-fA-F-]{36}$"),
        ],
        order_type: Literal["MARKET", "LIMIT"] = "MARKET",
        quantity: Decimal | None = None,
        intended_notional: Decimal | None = None,
        price: Decimal | None = None,
        confidence: Decimal | None = None,
        rationale: str = "",
        supporting_factors: list[str] | None = None,
        risk_factors: list[str] | None = None,
    ) -> dict[str, Any]:
        proposal = SubmitProposalInput(
            **_proposal(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                intended_notional=intended_notional,
                price=price,
                confidence=confidence,
                rationale=rationale,
                supporting_factors=supporting_factors,
                risk_factors=risk_factors,
            ).model_dump(),
            idempotency_key=idempotency_key,
        )
        with _with_db() as db:
            try:
                result = await HumanApprovalApplication(db).submit_proposal(
                    proposal,
                    proposal.idempotency_key,
                )
                return _result(result.as_dict())
            except ValueError as exc:
                return _error(str(exc))

    @server.tool(
        name="darwin.approve_trade",
        title="Approve DARWIN trade",
        description="Record an explicit owner approval for an opaque intent reference through TradeIntentApprovalService. The model must not self-approve from confidence or policy PASS.",
        annotations=mutation("Approve DARWIN trade", destructive=True, idempotent=True),
        structured_output=True,
    )
    def approve_trade(intent_id: str) -> dict[str, Any]:
        with _with_db() as db:
            try:
                return _approval_result(HumanApprovalApplication(db).approve_trade(intent_id))
            except ValueError as exc:
                return _error(str(exc))

    @server.tool(
        name="darwin.reject_trade",
        title="Reject DARWIN trade",
        description="Record an explicit owner rejection for an opaque intent reference through TradeIntentApprovalService; no Binance write is created.",
        annotations=mutation("Reject DARWIN trade", destructive=False, idempotent=True),
        structured_output=True,
    )
    def reject_trade(intent_id: str) -> dict[str, Any]:
        with _with_db() as db:
            try:
                return _approval_result(HumanApprovalApplication(db).reject_trade(intent_id))
            except ValueError as exc:
                return _error(str(exc))

    @server.tool(
        name="darwin.resolve_execution_confirmation",
        title="Resolve provider confirmation",
        description="Queue an explicit owner/provider confirmation action for an intent already waiting on the existing confirmation state machine. Never auto-answers provider confirmation.",
        annotations=mutation("Resolve provider confirmation", destructive=True, idempotent=True),
        structured_output=True,
    )
    def resolve_execution_confirmation(
        intent_id: str, action: Literal["ACCEPT", "DECLINE", "CANCEL"]
    ) -> dict[str, Any]:
        with _with_db() as db:
            try:
                return _result(
                    HumanApprovalApplication(db).queue_execution_confirmation(intent_id, action)
                )
            except ValueError as exc:
                return _error(str(exc))

    @server.tool(
        name="darwin.update_mandate",
        title="Update DARWIN mandate",
        description="Update the versioned Trading Mandate through the existing server-side validation and audit path.",
        annotations=mutation("Update DARWIN mandate", destructive=True, idempotent=False),
        structured_output=True,
    )
    def update_mandate_tool(
        trading_mandate: str,
        allowed_symbols: list[str],
        max_order_notional: Decimal,
        max_open_actionable_intents: int,
    ) -> dict[str, Any]:
        request = MandateInput(
            trading_mandate=trading_mandate,
            allowed_symbols=allowed_symbols,
            max_order_notional=max_order_notional,
            max_open_actionable_intents=max_open_actionable_intents,
        )
        with _with_db() as db:
            try:
                return _result(
                    update_mandate(
                        db,
                        request,
                        actor="MCP_OWNER",
                        model="external-mcp-host",
                    )
                )
            except ValueError as exc:
                return _error(str(exc))

    @server.tool(
        name="darwin.update_budget",
        title="Update DARWIN budget",
        description="Update the versioned rolling budget through the existing repository and audit path.",
        annotations=mutation("Update DARWIN budget", destructive=True, idempotent=False),
        structured_output=True,
    )
    def update_budget_tool(daily_budget: Decimal) -> dict[str, Any]:
        with _with_db() as db:
            try:
                return _result(
                    update_budget(
                        db,
                        daily_budget,
                        actor="MCP_OWNER",
                        model="external-mcp-host",
                    )
                )
            except ValueError as exc:
                return _error(str(exc))

    @server.tool(
        name="darwin.update_universe",
        title="Update DARWIN universe",
        description="Update configured Spot/USDT symbols through live Binance validation and the existing audit path.",
        annotations=mutation("Update DARWIN universe", destructive=True, idempotent=False),
        structured_output=True,
    )
    async def update_universe_tool(supported_symbols: list[str]) -> dict[str, Any]:
        with _with_db() as db:
            try:
                return _result(
                    await update_universe(
                        db,
                        supported_symbols,
                        actor="MCP_OWNER",
                        settings=get_settings(),
                    )
                )
            except (ValueError, RuntimeError) as exc:
                return _error(str(exc))

    @server.tool(
        name="darwin.emergency_stop",
        title="DARWIN emergency stop",
        description="Enable the existing authoritative emergency-stop path after explicit owner confirmation. Queues durable cancellation/reconciliation work and never creates an MCP-only cancellation path.",
        annotations=mutation("DARWIN emergency stop", destructive=True, idempotent=True),
        structured_output=True,
    )
    def emergency_stop_tool(confirmation: Literal["EMERGENCY_STOP"]) -> dict[str, Any]:
        with _with_db() as db:
            return _result(
                emergency_stop(db, actor="MCP_OWNER", settings=get_settings())
            )
