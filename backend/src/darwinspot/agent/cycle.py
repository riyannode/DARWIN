from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from darwinspot.agent.runtime import AgentRuntime
from darwinspot.binance.client import (
    AgentOSAuthInvalid,
    AgentOSUnavailable,
    BinanceAgentOSClient,
    ToolCatalog,
    UnsupportedCapability,
)
from darwinspot.binance.mapper import (
    BinanceMappingError,
    OrderCorrelationError,
    map_balances,
    map_mcp_result,
    map_open_orders,
    map_order_submission,
    map_recent_activity,
    map_spot_market_universe,
    map_symbol_filters,
    order_submission_evidence,
    validate_order_submission_correlation,
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


class CycleConfigurationError(CycleUnavailable):
    pass


class SubmissionUncertain(AgentOSUnavailable):
    pass


async def run_cycle(
    repo: Repository, client: BinanceAgentOSClient, runtime: AgentRuntime, run_id: str
) -> str:
    config = repo.get_or_create_agent()
    mandate = repo.current_mandate()
    budget = repo.budget_snapshot()
    if config.emergency_stop:
        raise CycleUnavailable("emergency stop is active")
    if mandate is None or budget is None:
        raise CycleConfigurationError("mandate and budget must exist before a cycle")
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
    market_universe = map_spot_market_universe(
        await client.call_tool(catalog.arguments("market_universe", {}))
    )
    available_pairs = {item["symbol"] for item in market_universe}
    selection = await runtime.choose_pair(
        {
            "market_universe": market_universe,
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
    if pair not in available_pairs:
        raise CycleUnavailable(
            "model selected a pair that is not available in the live market universe"
        )

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
    return await submit_intent(repo, client, catalog, intent)


async def submit_intent(
    repo: Repository, client: BinanceAgentOSClient, catalog: ToolCatalog, intent: TradeIntent
) -> str:
    repo.ensure_submission_allowed()
    submission_call = catalog.arguments("submit_order", {"intent": intent})
    upstream: Any = None
    try:
        upstream = await client.call_tool(submission_call)
        submission = map_order_submission(upstream)
        validate_order_submission_correlation(
            upstream,
            submission=submission,
            expected_symbol=intent.pair,
            expected_client_order_id=intent.idempotency_key,
            expected_side=intent.side,
        )
    except SubmissionBlocked:
        if intent.binance_order_id is None:
            intent.local_state = "PROPOSED"
            repo.db.commit()
        raise
    except UnsupportedCapability:
        raise
    except AgentOSAuthInvalid as exc:
        _record_submission_unknown(repo, intent, upstream, exc)
        raise
    except (AgentOSUnavailable, BinanceMappingError, TimeoutError) as exc:
        _record_submission_unknown(repo, intent, upstream, exc)
        raise SubmissionUncertain("order submission outcome is uncertain") from exc
    repo.apply_order_status(
        intent,
        order_id=submission.order_id,
        status=submission.status,
        filled_quantity=submission.executed_quantity,
        filled_notional=submission.quote_notional,
        exchange_timestamp=submission.updated_at,
        evidence=order_submission_evidence(
            upstream,
            intent_id=intent.id,
            client_order_id=intent.idempotency_key,
            submission=submission,
        ),
    )
    repo.db.commit()
    return intent.local_state


def _record_submission_unknown(
    repo: Repository, intent: TradeIntent, upstream: Any, error: BaseException
) -> None:
    intent.local_state = "SUBMISSION_UNKNOWN"
    repo.record_order_event(
        intent=intent,
        event_type="SUBMISSION_FAILED",
        filled_quantity=None,
        filled_notional=None,
        exchange_timestamp=None,
        evidence=order_submission_evidence(
            upstream,
            intent_id=intent.id,
            client_order_id=intent.idempotency_key,
            error=error,
        ),
    )
    repo.db.commit()
    log_event(
        "ORDER_SUBMIT_UNKNOWN",
        intent_id=intent.id,
        pair=intent.pair,
        error_code=type(error).__name__,
    )


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
            validate_order_submission_correlation(
                raw,
                submission=status,
                expected_symbol=intent.pair,
                expected_client_order_id=intent.idempotency_key,
                expected_side=intent.side,
            )
            repo.apply_order_status(
                intent,
                order_id=status.order_id,
                status=status.status,
                filled_quantity=status.executed_quantity,
                filled_notional=status.quote_notional,
                exchange_timestamp=status.updated_at,
                evidence=order_submission_evidence(
                    raw,
                    intent_id=intent.id,
                    client_order_id=intent.idempotency_key,
                    submission=status,
                ),
            )
        except AgentOSAuthInvalid:
            raise
        except OrderCorrelationError as exc:
            log_event("RECONCILIATION_FAILED", intent_id=intent.id, reason=str(exc))
            raise SubmissionUncertain(
                "order reconciliation response did not match the intent"
            ) from exc
        except (AgentOSUnavailable, BinanceMappingError, ValueError) as exc:
            log_event("RECONCILIATION_FAILED", intent_id=intent.id, reason=str(exc))
            raise SubmissionUncertain("order reconciliation is temporarily unavailable") from exc
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
        validate_order_submission_correlation(
            raw,
            submission=response,
            expected_symbol=intent.pair,
            expected_client_order_id=intent.idempotency_key,
            expected_side=intent.side,
        )
    except AgentOSAuthInvalid:
        repo.db.rollback()
        intent = repo.find_intent_by_order_id(order_id)
        if intent is not None:
            intent.local_state = "CANCEL_PENDING"
            repo.db.commit()
        raise
    except OrderCorrelationError as exc:
        repo.db.rollback()
        intent = repo.find_intent_by_order_id(order_id)
        if intent is not None:
            intent.local_state = "CANCEL_PENDING"
            repo.db.commit()
        raise SubmissionUncertain("cancel response did not match the intent") from exc
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
