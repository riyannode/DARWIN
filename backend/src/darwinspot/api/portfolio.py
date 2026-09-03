from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from darwinspot.api.auth import current_owner, mutation_owner, require_recent_reauthentication
from darwinspot.binance.client import AgentOSUnavailable, BinanceAgentOSClient, ToolCatalog
from darwinspot.binance.mapper import (
    BinanceMappingError,
    map_balances,
    map_mcp_result,
    map_open_orders,
)
from darwinspot.config import get_settings
from darwinspot.storage.database import get_db
from darwinspot.storage.models import OwnerSession
from darwinspot.storage.repository import Repository

router = APIRouter(tags=["portfolio"])


class BudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_budget: Decimal


def _is_fresh(timestamp: datetime | None, now: datetime) -> bool:
    if timestamp is None:
        return False
    return (
        timestamp.tzinfo is not None
        and timestamp <= now
        and now - timestamp.astimezone(UTC) <= timedelta(seconds=60)
    )


@router.get("/api/budget")
def get_budget(
    _: object = Depends(current_owner), db: Session = Depends(get_db)
) -> dict[str, str | None]:
    repo = Repository(db)
    budget = repo.current_budget()
    if budget is None:
        return {"dailyBudget": None, "availableBudget": None, "spentAmount": None}
    snapshot = repo.budget_snapshot()
    if snapshot is None:
        return {
            "dailyBudget": str(budget.daily_budget),
            "availableBudget": None,
            "spentAmount": None,
        }
    return {
        "dailyBudget": str(budget.daily_budget),
        "availableBudget": str(snapshot.available_budget),
        "spentAmount": str(snapshot.spent_amount),
    }


@router.put("/api/budget")
def put_budget(
    request: BudgetInput,
    owner: OwnerSession = Depends(mutation_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not request.daily_budget.is_finite() or request.daily_budget <= 0:
        raise HTTPException(status_code=422, detail="daily budget must be positive")
    repo = Repository(db)
    previous = repo.current_budget()
    if previous is not None and request.daily_budget > previous.daily_budget:
        require_recent_reauthentication(owner)
    budget = repo.save_budget(request.daily_budget)
    if previous is not None and request.daily_budget > previous.daily_budget:
        repo.record_audit_event(
            trigger="BUDGET_INCREASED",
            state="BUDGET_INCREASED",
            model=get_settings().openai_model,
            evidence={
                "previousDailyBudget": str(previous.daily_budget),
                "newDailyBudget": str(budget.daily_budget),
            },
        )
    return {"version": budget.id, "dailyBudget": str(budget.daily_budget)}


@router.get("/api/portfolio")
async def get_portfolio(
    _: object = Depends(current_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    connection = Repository(db).current_connection()
    if connection is None or connection.state != "CONNECTED":
        return {
            "connectionState": "DISCONNECTED",
            "balances": None,
            "allocation": None,
            "openOrders": None,
            "openOrdersSyncedAt": None,
            "stale": False,
            "staleReason": None,
            "syncedAt": None,
        }
    try:
        settings = get_settings()
        if not settings.token_encryption_key:
            raise AgentOSUnavailable("TOKEN_ENCRYPTION_KEY is required for Agent OS auth")
        client = BinanceAgentOSClient.with_oauth(
            settings.binance_agent_os_mcp_url,
            connection.id,
            settings.token_encryption_key,
            f"{settings.frontend_origin.rstrip('/')}/api/integrations/binance/callback",
            f"{settings.frontend_origin.rstrip('/')}/.well-known/darwinspot-oauth-client.json",
        )
        catalog = ToolCatalog(await client.discover_tools())
        snapshot = map_balances(await client.call_tool(catalog.arguments("balances", {})))
        open_orders = map_open_orders(await client.call_tool(catalog.arguments("open_orders", {})))
        now = datetime.now(UTC)
        stale_reasons: list[str] = []
        if not _is_fresh(snapshot.timestamp or snapshot.observed_at, now):
            stale_reasons.append("balance snapshot is stale")
        if not _is_fresh(open_orders.timestamp or open_orders.observed_at, now):
            stale_reasons.append("open-order snapshot is stale")
        allocation_total: Decimal | None = None
        allocation_timestamp = snapshot.timestamp or snapshot.observed_at
        if not stale_reasons:
            allocation_total = Decimal("0")
            for balance in snapshot.balances:
                quantity = balance.free + balance.locked
                if quantity == 0:
                    continue
                if balance.asset == "USDT":
                    allocation_total += quantity
                    continue
                symbol = f"{balance.asset}USDT"
                market = map_mcp_result(
                    "get_ticker",
                    await client.call_tool(catalog.arguments("market", {"symbol": symbol})),
                )
                if market.symbol != symbol or not _is_fresh(
                    market.timestamp or market.observed_at, now
                ):
                    stale_reasons.append(f"market valuation is stale for {symbol}")
                    allocation_total = None
                    break
                allocation_total += quantity * market.price
                allocation_timestamp = max(
                    allocation_timestamp, market.timestamp or market.observed_at
                )
    except (AgentOSUnavailable, BinanceMappingError, ValueError) as exc:
        if isinstance(exc, AgentOSUnavailable):
            repo = Repository(db)
            repo.mark_connection_unavailable(connection.id)
            db.commit()
        raise HTTPException(
            status_code=503, detail=f"live Binance account unavailable: {exc}"
        ) from exc
    return {
        "connectionState": connection.state,
        "balances": [item.model_dump(mode="json") for item in snapshot.balances],
        "allocation": None
        if allocation_total is None
        else {
            "quoteAsset": "USDT",
            "total": str(allocation_total),
            "asOf": allocation_timestamp,
        },
        "openOrders": [
            {
                "orderId": item.order_id,
                "symbol": item.symbol,
                "status": item.status,
                "executedQuantity": str(item.executed_quantity),
                "quoteNotional": str(item.quote_notional),
                "updatedAt": item.updated_at,
            }
            for item in open_orders.orders
        ],
        "openOrdersSyncedAt": open_orders.timestamp,
        "stale": bool(stale_reasons),
        "staleReason": "; ".join(stale_reasons) if stale_reasons else None,
        "syncedAt": max(snapshot.observed_at, open_orders.observed_at, allocation_timestamp),
    }
