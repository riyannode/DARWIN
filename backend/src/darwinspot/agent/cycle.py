from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from darwinspot.agent.runtime import AgentRuntime
from darwinspot.binance.client import AgentOSUnavailable, BinanceAgentOSClient, ToolCatalog
from darwinspot.binance.mapper import (
    BinanceMappingError,
    map_balances,
    map_mcp_result,
    map_open_orders,
    map_order_submission,
    map_recent_activity,
    map_symbol_filters,
)
from darwinspot.domain import new_idempotency_key
from darwinspot.execution.budget import BudgetExceeded
from darwinspot.execution.gateway import ExecutionGateway
from darwinspot.execution.orders import EmergencyStop, SubmissionBlocked
from darwinspot.observability import log_event
from darwinspot.storage.models import TradeIntent
from darwinspot.storage.repository import Repository


class CycleUnavailable(RuntimeError):
    pass


def _mandate_pairs(assets: str) -> set[str]:
    tokens = "".join(character if character.isalnum() else " " for character in assets.upper())
    return {token for token in tokens.split() if token}


def _pair_is_in_mandate(pair: str, assets: str) -> bool:
    return pair in _mandate_pairs(assets)


async def run_cycle(
    repo: Repository, client: BinanceAgentOSClient, runtime: AgentRuntime, run_id: str
) -> str:
    config = repo.get_or_create_agent()
    mandate = repo.current_mandate()
    budget = repo.budget_snapshot()
    if config.emergency_stop:
        raise CycleUnavailable("emergency stop is active")
    if mandate is None or budget is None:
        raise CycleUnavailable("mandate and budget must exist before a cycle")
    await reconcile_open_intents(repo, client)
    if any(
        intent.local_state in {"SUBMITTING", "SUBMISSION_UNKNOWN", "CANCEL_PENDING"}
        for intent in repo.non_terminal_intents()
    ):
        raise CycleUnavailable("pending order reconciliation must complete before new execution")
    budget = repo.budget_snapshot()
    if budget is None:
        raise CycleUnavailable("budget disappeared after order reconciliation")

    catalog = ToolCatalog(await client.discover_tools())
    selection = await runtime.choose_pair(
        {
            "mandate": {
                "assets": mandate.assets,
                "entry_rules": mandate.entry_rules,
                "sizing_rules": mandate.sizing_rules,
                "exit_rules": mandate.exit_rules,
            },
            "budget": {
                "available_budget": str(budget.available_budget),
                "spent_amount": str(budget.spent_amount),
            },
        }
    )
    pair = selection.pair
    if not _pair_is_in_mandate(pair, mandate.assets):
        raise CycleUnavailable("model selected a pair that is not explicitly listed in the mandate")

    observed_at = datetime.now(UTC)
    market = map_mcp_result(
        "get_ticker",
        await client.call_tool(catalog.arguments("market", {"symbol": pair})),
    )
    balances = map_balances(await client.call_tool(catalog.arguments("balances", {})))
    open_orders = map_open_orders(
        await client.call_tool(catalog.arguments("open_orders", {"symbol": pair}))
    )
    window_start = observed_at - timedelta(hours=24)
    recent_activity = map_recent_activity(
        await client.call_tool(
            catalog.arguments(
                "recent_activity",
                {
                    "symbol": pair,
                    "startTime": int(window_start.timestamp() * 1000),
                    "endTime": int(observed_at.timestamp() * 1000),
                },
            )
        ),
    )
    filters = map_symbol_filters(
        await client.call_tool(catalog.arguments("symbol_filters", {"symbol": pair}))
    )
    now = datetime.now(UTC)
    for source_name, timestamp, observed in (
        ("market", market.timestamp, market.observed_at),
        ("balances", balances.timestamp, balances.observed_at),
        ("open_orders", open_orders.timestamp, open_orders.observed_at),
        ("recent_activity", recent_activity.timestamp, recent_activity.observed_at),
        ("symbol_filters", filters.timestamp, filters.observed_at),
    ):
        freshness_timestamp = timestamp or observed
        if (
            freshness_timestamp.tzinfo is None
            or freshness_timestamp > now
            or now - freshness_timestamp > timedelta(seconds=60)
        ):
            raise CycleUnavailable(f"{source_name} snapshot is stale or has an invalid timestamp")
    evidence: dict[str, Any] = {
        "selected_pair": pair,
        "market": market.model_dump(mode="json"),
        "balances": balances.model_dump(mode="json"),
        "open_orders": open_orders.model_dump(mode="json"),
        "recent_activity": recent_activity.model_dump(mode="json"),
        "symbol_filters": filters.model_dump(mode="json"),
        "mandate": {
            "assets": mandate.assets,
            "entry_rules": mandate.entry_rules,
            "sizing_rules": mandate.sizing_rules,
            "exit_rules": mandate.exit_rules,
        },
        "budget": {
            "available_budget": str(budget.available_budget),
            "spent_amount": str(budget.spent_amount),
        },
    }
    decision = await runtime.decide(evidence)
    if decision.action in {"BUY", "SELL", "CANCEL_REPLACE"} and decision.pair != pair:
        raise CycleUnavailable("decision pair changed after live evidence was collected")
    repo.record_decision(run_id, decision.model_dump(mode="json"), evidence)
    if decision.action != "HOLD" and config.mode == "READ_ONLY":
        return config.mode
    if decision.action in {"CANCEL", "CANCEL_REPLACE"}:
        canceled = await _cancel_target(repo, client, catalog, decision.cancel_order_id or "")
        if decision.action == "CANCEL":
            return canceled
        if canceled != "CANCELED":
            return canceled
        budget = repo.budget_snapshot()
        if budget is None:
            raise CycleUnavailable("budget disappeared while replacing an order")
    repo.db.refresh(config)
    emergency_stop = EmergencyStop()
    if config.emergency_stop:
        emergency_stop.enable()
    result = ExecutionGateway(budget, emergency_stop, market, balances, filters).check(decision)
    if result.result == "BUDGET_EXCEEDED":
        log_event("BUDGET_EXCEEDED", run_id=run_id, pair=decision.pair)
    elif result.result == "ALLOW" and result.committed_notional is not None:
        log_event("BUDGET_ALLOWED", run_id=run_id, pair=decision.pair)
    if result.result != "ALLOW" or decision.action == "HOLD":
        return result.result
    if decision.pair is None or decision.quantity is None:
        raise CycleUnavailable("typed decision lacked required order fields")
    try:
        intent = repo.record_intent(
            run_id=run_id,
            idempotency_key=new_idempotency_key(),
            pair=decision.pair,
            side=decision.side or ("BUY" if decision.action == "BUY" else "SELL"),
            order_type=decision.order_type or "MARKET",
            quantity=decision.quantity,
            quote_notional=(
                result.committed_notional
                if decision.action == "BUY"
                or (decision.action == "CANCEL_REPLACE" and decision.side == "BUY")
                else None
            ),
            price=decision.price,
            budget_result=result.result,
            committed_notional=result.committed_notional,
            initial_state=("PROPOSED" if config.mode == "APPROVAL_REQUIRED" else "SUBMITTING"),
        )
    except BudgetExceeded:
        log_event(
            "BUDGET_EXCEEDED",
            run_id=run_id,
            pair=decision.pair,
            reason="concurrent_reservation",
        )
        return "BUDGET_EXCEEDED"
    if config.mode == "APPROVAL_REQUIRED":
        return "PROPOSED"
    await submit_intent(repo, client, catalog, intent)
    return result.result


async def submit_intent(
    repo: Repository, client: BinanceAgentOSClient, catalog: ToolCatalog, intent: TradeIntent
) -> str:
    try:
        repo.ensure_submission_allowed()
        upstream = await client.call_tool(catalog.arguments("submit_order", {"intent": intent}))
        submission = map_order_submission(upstream)
    except SubmissionBlocked:
        if intent.binance_order_id is None:
            intent.local_state = "PROPOSED"
            repo.db.commit()
        raise
    except (AgentOSUnavailable, BinanceMappingError):
        intent.local_state = "SUBMISSION_UNKNOWN"
        repo.db.commit()
        log_event("ORDER_SUBMIT_UNKNOWN", intent_id=intent.id, pair=intent.pair)
        raise
    repo.apply_order_status(
        intent,
        order_id=submission.order_id,
        status=submission.status,
        filled_quantity=submission.executed_quantity,
        filled_notional=submission.quote_notional,
        exchange_timestamp=submission.updated_at,
        evidence=submission.model_dump(mode="json"),
    )
    repo.db.commit()
    return intent.local_state


async def reconcile_open_intents(repo: Repository, client: BinanceAgentOSClient) -> None:
    intents = [
        intent
        for intent in repo.non_terminal_intents()
        if intent.local_state
        in {"SUBMITTING", "SUBMISSION_UNKNOWN", "OPEN", "PARTIALLY_FILLED", "CANCEL_PENDING"}
    ]
    if not intents:
        return
    try:
        catalog = ToolCatalog(await client.discover_tools())
    except (AgentOSUnavailable, ValueError) as exc:
        log_event("RECONCILIATION_FAILED", reason=str(exc))
        raise
    for intent in intents:
        try:
            raw = await client.call_tool(
                catalog.arguments(
                    "order_status",
                    {
                        "symbol": intent.pair,
                        "order_id": intent.binance_order_id,
                        "client_order_id": intent.idempotency_key,
                    },
                )
            )
            status = map_order_submission(raw)
            repo.apply_order_status(
                intent,
                order_id=status.order_id,
                status=status.status,
                filled_quantity=status.executed_quantity,
                filled_notional=status.quote_notional,
                exchange_timestamp=status.updated_at,
                evidence=status.model_dump(mode="json"),
            )
        except (AgentOSUnavailable, BinanceMappingError, ValueError) as exc:
            log_event("RECONCILIATION_FAILED", intent_id=intent.id, reason=str(exc))
            raise
    repo.db.commit()


async def _cancel_target(
    repo: Repository, client: BinanceAgentOSClient, catalog: ToolCatalog, order_id: str
) -> str:
    intent = repo.find_intent_by_order_id(order_id)
    if intent is None:
        raise CycleUnavailable("cancel target is not a known DarwinSpot order")
    if intent.local_state in {"CANCELED", "EXPIRED", "FILLED", "REJECTED_EXCHANGE"}:
        return intent.local_state
    exchange_order_id = intent.binance_order_id or order_id
    intent.local_state = "CANCEL_PENDING"
    repo.db.commit()
    log_event("ORDER_CANCEL_REQUESTED", intent_id=intent.id, order_id=exchange_order_id)
    try:
        raw = await client.call_tool(
            catalog.arguments(
                "cancel_order",
                {
                    "symbol": intent.pair,
                    "order_id": exchange_order_id,
                    "client_order_id": intent.idempotency_key,
                },
            )
        )
        response = map_order_submission(raw)
    except (AgentOSUnavailable, BinanceMappingError):
        repo.db.rollback()
        intent = repo.find_intent_by_order_id(order_id)
        if intent is not None:
            intent.local_state = "CANCEL_PENDING"
            repo.db.commit()
        raise
    repo.apply_order_status(
        intent,
        order_id=response.order_id,
        status=response.status,
        filled_quantity=response.executed_quantity,
        filled_notional=response.quote_notional,
        exchange_timestamp=response.updated_at,
        evidence=response.model_dump(mode="json"),
    )
    repo.db.commit()
    return intent.local_state
