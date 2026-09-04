from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from darwinspot.agent.candidate_scan import scan_candidate_history
from darwinspot.agent.runtime import AgentRuntime
from darwinspot.binance.client import BinanceAgentOSClient, ToolCatalog
from darwinspot.binance.mapper import (
    map_balances,
    map_mcp_result,
    map_open_orders,
    map_recent_activity,
    map_spot_market_universe,
    map_symbol_filters,
)
from darwinspot.binance.market_data import BinanceSpotMarketDataClient
from darwinspot.binance.schemas import SUPPORTED_MARKET_INTERVALS
from darwinspot.config import get_settings
from darwinspot.execution.budget import BudgetExceeded
from darwinspot.execution.modes import ExecutionMode
from darwinspot.execution.policy import evaluate_execution_policy
from darwinspot.execution.universe import effective_symbols
from darwinspot.observability import log_event
from darwinspot.storage.repository import Repository


class DecisionCycle:
    """Read evidence, ask DARWIN for a decision, and create proposals only."""

    async def run(
        self, repo: Repository, client: BinanceAgentOSClient, runtime: AgentRuntime, run_id: str
    ) -> str:
        config = repo.get_or_create_agent()
        mandate = repo.current_mandate()
        budget = repo.budget_snapshot()
        policy = repo.current_policy()
        if config.emergency_stop:
            return "EMERGENCY_STOP"
        if mandate is None or budget is None or policy is None:
            raise ValueError("mandate, structured policy, and budget must exist before a cycle")
        try:
            execution_mode = ExecutionMode(config.mode)
        except ValueError as exc:
            raise ValueError("agent configuration has an unsupported execution mode") from exc

        from darwinspot.agent.cycle import reconcile_open_intents

        await reconcile_open_intents(repo, client)
        if any(
            intent.local_state
            in {
                "SUBMITTING",
                "SUBMISSION_UNKNOWN",
                "CANCEL_PENDING",
                "CANCEL_BLOCKED",
                "REVALIDATING",
            }
            for intent in repo.non_terminal_intents()
        ):
            raise RuntimeError("pending order reconciliation must complete before new proposals")

        catalog = ToolCatalog(await client.discover_tools())
        market_universe = map_spot_market_universe(
            await client.call_tool(catalog.arguments("market_universe", {}))
        )
        configured_symbols = repo.supported_symbols()
        universe = effective_symbols(configured_symbols, policy.allowed_symbols, market_universe)
        eligible_market = [
            item for item in market_universe if item["symbol"] in universe.eligible
        ]
        valid_symbols = set(universe.eligible)
        for item in eligible_market:
            symbol = str(item["symbol"])
            try:
                filters_for_symbol = map_symbol_filters(
                    await client.call_tool(catalog.arguments("symbol_filters", {"symbol": symbol}))
                )
            except (ValueError, TypeError):
                valid_symbols.discard(symbol)
                continue
            if filters_for_symbol.quote_asset != "USDT":
                valid_symbols.discard(symbol)
        eligible_symbols = frozenset(valid_symbols)
        eligible_market = [item for item in eligible_market if item["symbol"] in eligible_symbols]
        if not eligible_market:
            repo.record_run_evidence(
                run_id,
                {
                    "pair_selection": {
                        "selected_pair": None,
                        "candidate_symbols": [],
                        "candidate_history": {},
                        "candidate_failures": {},
                        "configured_symbols": list(configured_symbols),
                        "mandate_allowed_symbols": sorted(policy.allowed_symbols),
                        "invalid_configured_symbols": sorted(universe.invalid_configured),
                        "reason": "no effective market symbols",
                    }
                },
            )
            log_event("DECISION_NO_EFFECTIVE_SYMBOLS", run_id=run_id)
            return "NO_EFFECTIVE_SYMBOLS"
        market_data_client = BinanceSpotMarketDataClient(
            get_settings().binance_spot_api_base_url
        )
        candidate_scan = await scan_candidate_history(
            market_data_client, sorted(eligible_symbols)
        )
        candidate_failures = dict(candidate_scan.failures)
        for symbol, error_code in candidate_failures.items():
            log_event(
                "DECISION_CANDIDATE_EXCLUDED",
                run_id=run_id,
                symbol=symbol,
                error_code=error_code,
            )
        candidate_symbols = frozenset(candidate_scan.histories)
        if not candidate_symbols:
            repo.record_run_evidence(
                run_id,
                {
                    "pair_selection": {
                        "selected_pair": None,
                        "candidate_symbols": [],
                        "candidate_history": {},
                        "candidate_failures": candidate_failures,
                    }
                },
            )
            log_event("DECISION_NO_EFFECTIVE_SYMBOLS", run_id=run_id)
            return "NO_EFFECTIVE_SYMBOLS"
        candidate_market = [
            item for item in eligible_market if item["symbol"] in candidate_symbols
        ]
        candidate_history_evidence = {
            symbol: {
                interval: snapshot.model_dump(mode="json")
                for interval, snapshot in histories.items()
            }
            for symbol, histories in candidate_scan.histories.items()
        }
        selection_evidence: dict[str, Any] = {
            "market_universe": candidate_market,
            "effective_symbols": sorted(candidate_symbols),
            "candidate_symbols": sorted(candidate_symbols),
            "candidate_history": candidate_history_evidence,
            "candidate_failures": candidate_failures,
            "mandate": {"trading_mandate": repo.mandate_text(mandate)},
            "execution_policy": {
                "allowed_symbols": sorted(policy.allowed_symbols),
                "max_order_notional": str(policy.max_order_notional),
                "max_open_actionable_intents": policy.max_open_actionable_intents,
            },
            "budget": {
                "available_budget": str(budget.available_budget),
                "spent_amount": str(budget.spent_amount),
            },
        }
        selection = await runtime.choose_pair(selection_evidence)
        pair = selection.pair
        if pair not in candidate_symbols:
            repo.record_run_evidence(
                run_id,
                {
                    "pair_selection": {
                        "selected_pair": pair,
                        "candidate_symbols": sorted(candidate_symbols),
                        "candidate_history": candidate_history_evidence,
                        "candidate_failures": candidate_failures,
                    },
                    "rejection": {
                        "reason": "pair outside effective universe",
                        "model_selected_pair": pair,
                    },
                },
            )
            log_event(
                "DECISION_POLICY_REJECTED",
                run_id=run_id,
                reason="pair outside effective universe",
            )
            return "POLICY_REJECTED"

        observed_at = datetime.now(UTC)
        market = map_mcp_result(
            "get_ticker",
            await client.call_tool(catalog.arguments("market", {"symbol": pair})),
            observed_at=observed_at,
        )
        history_snapshots = await asyncio.gather(
            *(
                market_data_client.market_history(pair, interval)
                for interval in SUPPORTED_MARKET_INTERVALS
            )
        )
        market_history = {snapshot.interval: snapshot for snapshot in history_snapshots}
        if set(market_history) != set(SUPPORTED_MARKET_INTERVALS) or any(
            snapshot.symbol != pair for snapshot in history_snapshots
        ):
            raise RuntimeError("market-history evidence does not match the selected pair")
        balances = map_balances(
            await client.call_tool(catalog.arguments("balances", {})), observed_at=observed_at
        )
        open_orders = map_open_orders(
            await client.call_tool(catalog.arguments("open_orders", {"symbol": pair})),
            observed_at=observed_at,
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
            observed_at=observed_at,
        )
        filters = map_symbol_filters(
            await client.call_tool(catalog.arguments("symbol_filters", {"symbol": pair})),
            observed_at=observed_at,
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
                raise RuntimeError(f"{source_name} snapshot is stale or has an invalid timestamp")

        decision_evidence: dict[str, Any] = {
            "selected_pair": pair,
            "market": market.model_dump(mode="json"),
            "market_history": {
                interval: snapshot.model_dump(mode="json")
                for interval, snapshot in market_history.items()
            },
            "balances": balances.model_dump(mode="json"),
            "open_orders": open_orders.model_dump(mode="json"),
            "recent_activity": recent_activity.model_dump(mode="json"),
            "symbol_filters": filters.model_dump(mode="json"),
            "mandate": {"trading_mandate": repo.mandate_text(mandate)},
            "execution_policy": {
                "allowed_symbols": sorted(policy.allowed_symbols),
                "max_order_notional": str(policy.max_order_notional),
                "max_open_actionable_intents": policy.max_open_actionable_intents,
            },
            "budget": {
                "available_budget": str(budget.available_budget),
                "spent_amount": str(budget.spent_amount),
            },
        }
        decision = await runtime.decide(decision_evidence)
        pair_selection_evidence = {
            "selected_pair": pair,
            "effective_symbols": sorted(eligible_symbols),
            "candidate_symbols": sorted(candidate_symbols),
            "candidate_history": candidate_history_evidence,
            "candidate_failures": candidate_failures,
        }
        persisted_evidence = {
            "pair_selection": pair_selection_evidence,
            "final_decision": decision_evidence,
        }
        decision_pair_mismatch = decision.pair is not None and decision.pair != pair
        if decision_pair_mismatch:
            mismatch_reason = "final decision pair does not match selected pair"
            repo.record_run_evidence(
                run_id,
                {
                    **persisted_evidence,
                    "rejection": {"reason": mismatch_reason},
                },
            )
            log_event(
                "DECISION_POLICY_REJECTED",
                run_id=run_id,
                reason=mismatch_reason,
            )
            return "POLICY_REJECTED"
        repo.record_decision(run_id, decision.model_dump(mode="json"), persisted_evidence)
        if decision.action == "HOLD":
            return "HOLD"
        evaluation = evaluate_execution_policy(
            policy,
            decision=decision,
            market=market,
            balances=balances,
            filters=filters,
            open_orders=open_orders,
            budget=budget,
            emergency_stop=config.emergency_stop,
            actionable_intent_count=repo.actionable_intent_count(),
            eligible_symbols=eligible_symbols,
        )
        policy_evidence = {
            "mandate_result": evaluation.mandate_result,
            "risk_result": evaluation.risk_result,
            "budget_result": evaluation.budget_result,
            "execution_policy_result": evaluation.execution_policy_result,
            "reason": evaluation.reason,
            "computed_notional": (
                str(evaluation.computed_notional)
                if evaluation.computed_notional is not None
                else None
            ),
            "mandate_version": mandate.id,
            "policy": decision_evidence["execution_policy"],
            "reference_price": str(market.price),
        }
        persisted_evidence["policy"] = policy_evidence
        repo.record_run_evidence(run_id, persisted_evidence)
        if not evaluation.allowed:
            log_event("DECISION_POLICY_REJECTED", run_id=run_id, reason=evaluation.reason)
            return "POLICY_REJECTED"

        settings = get_settings()
        signal_since = datetime.now(UTC) - timedelta(seconds=settings.signal_cooldown_seconds)
        if repo.recent_actionable_signal_exists(
            pair=decision.pair or "",
            side=decision.side or decision.action,
            since=signal_since,
        ):
            log_event("DECISION_SIGNAL_SUPPRESSED", run_id=run_id, pair=decision.pair)
            return "SIGNAL_SUPPRESSED"
        if not settings.financial_writes_enabled:
            log_event(
                "DECISION_FINANCIAL_WRITES_DISABLED",
                run_id=run_id,
                action=decision.action,
                pair=decision.pair,
            )
            return "FINANCIAL_WRITES_DISABLED"
        operator_user_id = str(settings.telegram_operator_user_id or "WEB_OWNER")
        operator_chat_id = str(settings.telegram_operator_chat_id or "WEB_OWNER")
        approval_id: str | None = None
        try:
            if execution_mode == ExecutionMode.HUMAN_APPROVAL:
                _, approval = repo.create_waiting_intent(
                    run_id=run_id,
                    decision=decision.model_dump(mode="json"),
                    evaluation=evaluation,
                    policy_evidence=policy_evidence,
                    operator_user_id=operator_user_id,
                    operator_chat_id=operator_chat_id,
                    ttl_seconds=settings.approval_ttl_seconds,
                    signal_since=signal_since,
                )
                approval_id = approval.approval_id
            else:
                repo.create_auto_intent(
                    run_id=run_id,
                    decision=decision.model_dump(mode="json"),
                    evaluation=evaluation,
                    policy_evidence=policy_evidence,
                    signal_since=signal_since,
                )
        except BudgetExceeded as exc:
            log_event("DECISION_POLICY_REJECTED", run_id=run_id, reason=str(exc))
            return "POLICY_REJECTED"
        if execution_mode == ExecutionMode.HUMAN_APPROVAL:
            log_event(
                "TRADE_INTENT_WAITING_FOR_APPROVAL",
                run_id=run_id,
                approval_id=approval_id,
            )
            return "WAITING_FOR_APPROVAL"
        log_event("TRADE_INTENT_AUTO_AUTHORIZED", run_id=run_id)
        return "AUTO_AUTHORIZED"
