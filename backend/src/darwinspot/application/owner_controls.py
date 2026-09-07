from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from darwinspot.binance.client import AgentOSUnavailable, ToolCatalog
from darwinspot.binance.codex_transport import CodexTransportError
from darwinspot.binance.factory import build_binance_client
from darwinspot.binance.mapper import map_spot_market_universe, map_symbol_filters
from darwinspot.config import Settings
from darwinspot.domain import AgentState
from darwinspot.execution.approved import account_execution_lock
from darwinspot.execution.universe import validate_supported_symbols
from darwinspot.notifications.outbox import EMERGENCY_CANCEL_KIND, enqueue_unique
from darwinspot.observability import log_event
from darwinspot.storage.repository import Repository


def update_mandate(db: Session, request: Any, *, actor: str, model: str) -> dict[str, object]:
    repo = Repository(db)
    mandate = repo.save_mandate(request.model_dump())
    repo.record_audit_event(
        trigger="MCP_MANDATE_UPDATED",
        state="MANDATE_UPDATED",
        model=model,
        evidence={"actor": actor, "version": mandate.id},
    )
    return {"version": mandate.id, "createdAt": mandate.created_at}


def update_budget(db: Session, amount: Any, *, actor: str, model: str) -> dict[str, str]:
    repo = Repository(db)
    previous = repo.current_budget()
    budget = repo.save_budget(amount)
    if previous is not None and budget.daily_budget > previous.daily_budget:
        repo.record_audit_event(
            trigger="MCP_BUDGET_INCREASED",
            state="BUDGET_INCREASED",
            model=model,
            evidence={
                "actor": actor,
                "previousDailyBudget": str(previous.daily_budget),
                "newDailyBudget": str(budget.daily_budget),
            },
        )
    return {"version": budget.id, "dailyBudget": str(budget.daily_budget)}


async def update_universe(
    db: Session,
    symbols: list[str],
    *,
    actor: str,
    settings: Settings,
) -> dict[str, object]:
    values = list(validate_supported_symbols(symbols))
    repo = Repository(db)
    config = repo.get_or_create_agent()
    connection = repo.current_connection()
    existing_symbols = set(repo.supported_symbols())
    additions = [symbol for symbol in values if symbol not in existing_symbols]
    client: Any = None
    try:
        if additions:
            client = build_binance_client(settings, connection, mode=config.mode)
            catalog = ToolCatalog(await client.discover_tools())
            market_universe = map_spot_market_universe(
                await client.call_tool(
                    catalog.arguments("market_universe", {"symbols": values})
                )
            )
            live = {str(item["symbol"]): item for item in market_universe}
            for symbol in additions:
                if live.get(symbol) is None:
                    raise ValueError(f"{symbol} is not a current Binance Spot/USDT symbol")
                filters = map_symbol_filters(
                    await client.call_tool(catalog.arguments("symbol_filters", {"symbol": symbol}))
                )
                if filters.symbol != symbol or filters.quote_asset != "USDT":
                    raise ValueError(f"{symbol} does not expose valid Spot/USDT filters")
        saved = repo.save_supported_symbols(values)
    except (AgentOSUnavailable, CodexTransportError) as exc:
        raise RuntimeError("selected Binance transport is unavailable") from exc
    finally:
        transport = getattr(client, "transport", None)
        if transport is not None:
            await transport.close()
    repo.record_audit_event(
        trigger=(
            "MCP_SUPPORTED_SYMBOLS_CHANGED"
            if actor == "MCP_OWNER"
            else "SUPPORTED_SYMBOLS_CHANGED"
        ),
        state="SUPPORTED_SYMBOLS_CHANGED",
        model=settings.openai_model,
        evidence={"actor": actor, "supportedSymbols": list(saved)},
    )
    return {"supportedSymbols": list(saved)}


def emergency_stop(db: Session, *, actor: str, settings: Settings) -> dict[str, object]:
    repo = Repository(db)
    with account_execution_lock(db, settings.binance_account_lock_key):
        config = repo.get_or_create_agent()
        config.emergency_stop = True
        config.state = AgentState.EMERGENCY_STOP
        config.next_run_at = None
        targets: list[dict[str, str]] = []
        for intent in repo.non_terminal_intents():
            if intent.local_state not in {
                "OPEN",
                "PARTIALLY_FILLED",
                "SUBMITTING",
                "SUBMISSION_UNKNOWN",
                "CANCEL_PENDING",
            }:
                continue
            enqueue_unique(
                db,
                kind=EMERGENCY_CANCEL_KIND,
                aggregate_id=intent.id,
                payload={"intent_id": intent.id, "operator_action_id": actor},
                dedupe_key=f"emergency-cancel:{config.id}:{intent.id}",
            )
            targets.append({"id": intent.id, "state": "CANCEL_QUEUED"})
        db.commit()
    log_event(
        "EMERGENCY_STOP_ENABLED",
        operator_action_id=actor,
        target_count=len(targets),
        target_ids=[item["id"] for item in targets],
    )
    if not targets:
        return {"state": config.state, "cancellationState": "RECONCILED", "outcomes": []}
    return {"state": config.state, "cancellationState": "QUEUED", "outcomes": targets}
