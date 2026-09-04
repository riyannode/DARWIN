from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from darwinspot.agent.schemas import Action, AgentDecision
from darwinspot.binance.mapper import (
    map_balances,
    map_candidate_market_history,
    map_market_history,
    map_mcp_result,
    map_open_orders,
    map_recent_activity,
    map_spot_market_universe,
    map_symbol_filters,
)
from darwinspot.binance.schemas import (
    CANDIDATE_MARKET_INTERVALS,
    SUPPORTED_MARKET_INTERVALS,
    BalanceSnapshot,
    MarketHistorySnapshot,
    MarketSnapshot,
    OpenOrdersSnapshot,
    SymbolFilters,
)
from darwinspot.execution.budget import BudgetSnapshot, calculate_budget
from darwinspot.execution.demo_guard import (
    DemoFinancialWriteBlocked,
    ensure_financial_write_allowed,
)
from darwinspot.execution.policy import ExecutionPolicy, PolicyEvaluation, evaluate_execution_policy
from darwinspot.execution.universe import DEFAULT_SUPPORTED_SYMBOLS, effective_symbols

DEMO_NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
DEMO_ALLOWED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEMO_BUDGET = Decimal("500")
DEMO_MAX_PER_TRADE = Decimal("100")
DEMO_MAX_CONCURRENT_TRADES = 1


@dataclass(frozen=True)
class DemoScenarioDefinition:
    scenario_id: str
    title: str
    description: str
    pair: str
    action: Action
    quantity: Decimal | None
    confidence: Decimal
    rationale: str
    supporting_factors: tuple[str, ...]
    risk_factors: tuple[str, ...]


SCENARIOS: tuple[DemoScenarioDefinition, ...] = (
    DemoScenarioDefinition(
        scenario_id="valid-buy",
        title="Valid autonomous BUY",
        description="A bounded BTC setup passes every deterministic policy check.",
        pair="BTCUSDT",
        action="BUY",
        quantity=Decimal("0.001333"),
        confidence=Decimal("0.84"),
        rationale=(
            "BTC has aligned closed-candle momentum across the candidate windows while the "
            "mandate prioritizes capital protection."
        ),
        supporting_factors=(
            "15m and 1h closed candles are aligned",
            "BTCUSDT is in the effective universe",
            "available USDT balance covers the computed notional",
        ),
        risk_factors=(
            "recorded evidence is not live market data",
            "demo financial submission is disabled",
        ),
    ),
    DemoScenarioDefinition(
        scenario_id="max-notional",
        title="Policy rejection",
        description="A deterministic BUY is rejected because its notional exceeds Max Per Trade.",
        pair="SOLUSDT",
        action="BUY",
        quantity=Decimal("1"),
        confidence=Decimal("0.91"),
        rationale=(
            "SOL has a strong recorded setup, but the requested notional is outside the "
            "mandate's hard per-trade limit."
        ),
        supporting_factors=(
            "SOLUSDT is in the effective universe",
            "recorded 15m and 1h candles show a strong setup",
        ),
        risk_factors=(
            "requested notional is 150 USDT",
            "Max Per Trade is 100 USDT",
        ),
    ),
    DemoScenarioDefinition(
        scenario_id="hold",
        title="Unclear evidence",
        description="The deterministic agent chooses HOLD when evidence is not decisive.",
        pair="ETHUSDT",
        action="HOLD",
        quantity=None,
        confidence=Decimal("0.67"),
        rationale=(
            "ETH evidence is mixed across the recorded windows, so the mandate's "
            "capital-protection preference selects HOLD."
        ),
        supporting_factors=(
            "ETHUSDT is in the effective universe",
            "mixed closed-candle direction",
        ),
        risk_factors=(
            "no decisive setup",
            "no trade authorization is created for HOLD",
        ),
    ),
)


def _definition(scenario_id: str) -> DemoScenarioDefinition:
    for definition in SCENARIOS:
        if definition.scenario_id == scenario_id:
            return definition
    raise KeyError(scenario_id)


def _raw_klines(
    interval: str, count: int, base: Decimal, drift: Decimal
) -> list[list[object]]:
    seconds = {"15m": 15 * 60, "1h": 60 * 60, "4h": 4 * 60 * 60}[interval]
    start = DEMO_NOW - timedelta(seconds=seconds * count + seconds // 2)
    candles: list[list[object]] = []
    for index in range(count):
        open_time = start + timedelta(seconds=seconds * index)
        close_time = open_time + timedelta(seconds=seconds)
        opening = base + drift * index
        closing = opening + drift
        high = max(opening, closing) + abs(drift) + Decimal("0.01")
        low = max(Decimal("0.000001"), min(opening, closing) - abs(drift) - Decimal("0.01"))
        candles.append(
            [
                str(int(open_time.timestamp() * 1000)),
                str(opening),
                str(high),
                str(low),
                str(closing),
                str(Decimal("1000") + index),
                str(int(close_time.timestamp() * 1000)),
                str((Decimal("1000") + index) * closing),
                100 + index,
                "0",
                "0",
                "0",
            ]
        )
    return candles


def _market_universe() -> list[dict[str, object]]:
    return [
        {
            "symbol": symbol,
            "status": "TRADING",
            "quoteAsset": "USDT",
            "permissions": ["SPOT"],
            "isSpotTradingAllowed": True,
        }
        for symbol in DEFAULT_SUPPORTED_SYMBOLS
    ]


def _price(pair: str) -> Decimal:
    return {
        "BTCUSDT": Decimal("60000"),
        "ETHUSDT": Decimal("3000"),
        "BNBUSDT": Decimal("500"),
        "SOLUSDT": Decimal("150"),
        "XRPUSDT": Decimal("0.5"),
    }[pair]


def _ticker(pair: str) -> MarketSnapshot:
    return map_mcp_result(
        "get_ticker",
        {
            "symbol": pair,
            "price": str(_price(pair)),
            "timestamp": int((DEMO_NOW - timedelta(seconds=30)).timestamp() * 1000),
        },
        observed_at=DEMO_NOW,
    )


def _balances() -> BalanceSnapshot:
    return map_balances(
        {
            "timestamp": int((DEMO_NOW - timedelta(seconds=30)).timestamp() * 1000),
            "balances": [
                {"asset": "USDT", "free": "5000", "locked": "0"},
                {"asset": "BTC", "free": "0.1", "locked": "0"},
                {"asset": "ETH", "free": "1", "locked": "0"},
                {"asset": "SOL", "free": "10", "locked": "0"},
            ],
        },
        observed_at=DEMO_NOW,
    )


def _open_orders() -> OpenOrdersSnapshot:
    return map_open_orders(
        {
            "timestamp": int((DEMO_NOW - timedelta(seconds=30)).timestamp() * 1000),
            "orders": [],
        },
        observed_at=DEMO_NOW,
    )


def _recent_activity() -> dict[str, object]:
    return map_recent_activity({"trades": []}, observed_at=DEMO_NOW).model_dump(mode="json")


def _filters(pair: str) -> SymbolFilters:
    return map_symbol_filters(
        {
            "symbol": pair,
            "quoteAsset": "USDT",
            "timestamp": int((DEMO_NOW - timedelta(seconds=30)).timestamp() * 1000),
            "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.000001", "stepSize": "0.000001"},
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
            ],
        },
        observed_at=DEMO_NOW,
    )


def _candidate_history() -> dict[str, dict[str, object]]:
    histories: dict[str, dict[str, object]] = {}
    for symbol in DEMO_ALLOWED_SYMBOLS:
        base = _price(symbol) * Decimal("0.98")
        drift = max(_price(symbol) * Decimal("0.001"), Decimal("0.0001"))
        histories[symbol] = {
            interval: map_candidate_market_history(
                _raw_klines(interval, 10, base, drift),
                symbol=symbol,
                interval=interval,
                now=DEMO_NOW,
                observed_at=DEMO_NOW,
            ).model_dump(mode="json")
            for interval in CANDIDATE_MARKET_INTERVALS
        }
    return histories


def _selected_history(pair: str) -> dict[str, MarketHistorySnapshot]:
    base = _price(pair) * Decimal("0.98")
    drift = max(_price(pair) * Decimal("0.001"), Decimal("0.0001"))
    return {
        interval: map_market_history(
            _raw_klines(interval, 48, base, drift),
            symbol=pair,
            interval=interval,
            now=DEMO_NOW,
            observed_at=DEMO_NOW,
        )
        for interval in SUPPORTED_MARKET_INTERVALS
    }


def _decision(definition: DemoScenarioDefinition) -> AgentDecision:
    return AgentDecision(
        action=definition.action,
        pair=definition.pair,
        order_type="MARKET" if definition.action != "HOLD" else None,
        side="BUY" if definition.action == "BUY" else None,
        quantity=definition.quantity,
        rationale=definition.rationale,
        evidence=["recorded_candidate_history", "recorded_selected_pair_evidence"],
        confidence=definition.confidence,
        supporting_factors=list(definition.supporting_factors),
        risk_factors=list(definition.risk_factors),
    )


def _reason_code(reason: str | None) -> str | None:
    return {
        "max_order_notional exceeded": "MAX_ORDER_NOTIONAL",
        "buy exceeds available budget": "BUDGET_EXCEEDED",
        "max_open_actionable_intents reached": "MAX_CONCURRENT_TRADES",
        "symbol is not in allowed_symbols": "SYMBOL_NOT_ALLOWED",
        "symbol is not in configured trading universe": "SYMBOL_NOT_CONFIGURED",
    }.get(reason or "")


def _guardrails(
    evaluation: PolicyEvaluation | None,
    *,
    decision: AgentDecision,
    budget: BudgetSnapshot,
    effective: frozenset[str],
) -> list[dict[str, str]]:
    base = [
        {
            "name": "Allowed Symbols",
            "result": "PASS" if decision.pair in DEMO_ALLOWED_SYMBOLS else "FAIL",
            "detail": "pair is mandate-authorized",
        },
        {
            "name": "Effective Universe",
            "result": "PASS" if decision.pair in effective else "FAIL",
            "detail": ", ".join(sorted(effective)),
        },
    ]
    if evaluation is None:
        result = "NOT_EVALUATED"
        reason = "HOLD does not create an executable policy evaluation"
        return base + [
            {"name": "Max Per Trade", "result": result, "detail": reason},
            {"name": "24h Budget", "result": result, "detail": reason},
            {"name": "Max Concurrent Trades", "result": result, "detail": reason},
            {"name": "Balance", "result": result, "detail": reason},
            {"name": "Symbol Filters", "result": result, "detail": reason},
            {"name": "Open-Order Conflict", "result": result, "detail": reason},
            {"name": "Emergency Stop", "result": "PASS", "detail": "not active"},
        ]
    passed = "PASS" if evaluation.allowed else "FAIL"
    reason = evaluation.reason or "all deterministic checks passed"
    return base + [
        {
            "name": "Max Per Trade",
            "result": passed
            if evaluation.reason == "max_order_notional exceeded" or evaluation.allowed
            else "PASS",
            "detail": reason,
        },
        {
            "name": "24h Budget",
            "result": "PASS"
            if budget.can_buy(evaluation.computed_notional or Decimal("0"))
            else "FAIL",
            "detail": f"{budget.available_budget} USDT available",
        },
        {"name": "Max Concurrent Trades", "result": "PASS", "detail": "0 of 1 active workflows"},
        {"name": "Balance", "result": "PASS", "detail": "5000 USDT available"},
        {
            "name": "Symbol Filters",
            "result": "PASS",
            "detail": "quantity and notional satisfy Spot filters",
        },
        {
            "name": "Open-Order Conflict",
            "result": "PASS",
            "detail": "no open order for selected pair",
        },
        {"name": "Emergency Stop", "result": "PASS", "detail": "not active"},
    ]


def build_demo_result(scenario_id: str) -> dict[str, Any]:
    definition = _definition(scenario_id)
    decision = _decision(definition)
    configured = tuple(DEFAULT_SUPPORTED_SYMBOLS)
    allowed = tuple(DEMO_ALLOWED_SYMBOLS)
    market_universe = map_spot_market_universe(_market_universe())
    effective = effective_symbols(configured, allowed, market_universe).eligible
    budget = calculate_budget(DEMO_BUDGET, DEMO_NOW, [], [])
    market = _ticker(definition.pair)
    balances = _balances()
    open_orders = _open_orders()
    filters = _filters(definition.pair)
    selected_history = _selected_history(definition.pair)
    candidate_history = _candidate_history()
    evaluation: PolicyEvaluation | None = None
    system_reason = "NO_TRADE"
    policy_result = "NOT_APPLICABLE"
    reason_code: str | None = "NO_TRADE"
    lifecycle = ["MODEL_DECISION_RECORDED", "NO_TRADE"]
    if decision.action != "HOLD":
        policy = ExecutionPolicy(
            allowed_symbols=frozenset(allowed),
            max_order_notional=DEMO_MAX_PER_TRADE,
            max_open_actionable_intents=DEMO_MAX_CONCURRENT_TRADES,
            configured_symbols=frozenset(configured),
        )
        evaluation = evaluate_execution_policy(
            policy,
            decision=decision,
            market=market,
            balances=balances,
            filters=filters,
            open_orders=open_orders,
            budget=budget,
            emergency_stop=False,
            actionable_intent_count=0,
            eligible_symbols=effective,
        )
        if evaluation.allowed:
            policy_result = "PASS"
            try:
                ensure_financial_write_allowed()
            except DemoFinancialWriteBlocked:
                system_reason = "DEMO_EXECUTION_BLOCKED"
                reason_code = "DEMO_EXECUTION_BLOCKED"
                lifecycle = ["MODEL_DECISION_RECORDED", "POLICY_PASSED", "DEMO_EXECUTION_BLOCKED"]
            else:
                system_reason = "DEMO_MODE_REQUIRED"
                reason_code = "DEMO_MODE_REQUIRED"
        else:
            policy_result = "REJECTED"
            system_reason = "POLICY_REJECTED"
            reason_code = _reason_code(evaluation.reason) or "POLICY_REJECTED"
            lifecycle = ["MODEL_DECISION_RECORDED", "POLICY_REJECTED"]
    final_evidence = {
        "recorded": True,
        "observed_at": DEMO_NOW,
        "selected_pair": definition.pair,
        "market": market.model_dump(mode="json"),
        "market_history": {
            interval: snapshot.model_dump(mode="json")
            for interval, snapshot in selected_history.items()
        },
        "balances": balances.model_dump(mode="json"),
        "open_orders": open_orders.model_dump(mode="json"),
        "recent_activity": _recent_activity(),
        "symbol_filters": filters.model_dump(mode="json"),
    }
    return {
        "mode": "DEMO_MODE",
        "scenarioId": definition.scenario_id,
        "title": definition.title,
        "description": definition.description,
        "timestamp": DEMO_NOW,
        "disclosure": {
            "deterministic": True,
            "recordedEvidence": True,
            "llmCall": False,
            "liveBinance": False,
            "financialWrites": False,
        },
        "configuredUniverse": list(configured),
        "allowedSymbols": list(allowed),
        "effectiveUniverse": sorted(effective),
        "candidateScan": {
            "intervals": list(CANDIDATE_MARKET_INTERVALS),
            "closedCandleCount": 10,
            "candidateSymbols": sorted(candidate_history),
            "candidateHistory": candidate_history,
            "selectedPair": definition.pair,
            "excludedCandidates": [],
        },
        "selectedPairEvidence": final_evidence,
        "mandate": "Protect capital. Prefer strong setups and HOLD when evidence is unclear.",
        "policy": {
            "allowedSymbols": list(allowed),
            "maxPerTrade": str(DEMO_MAX_PER_TRADE),
            "budgetTotal": str(DEMO_BUDGET),
            "budgetSpentOrReserved": str(budget.spent_amount),
            "budgetAvailable": str(budget.available_budget),
            "maxConcurrentTrades": DEMO_MAX_CONCURRENT_TRADES,
            "emergencyStop": False,
            "result": policy_result,
            "reason": evaluation.reason if evaluation else None,
            "reasonCode": reason_code,
            "guardrails": _guardrails(
                evaluation,
                decision=decision,
                budget=budget,
                effective=effective,
            ),
        },
        "decision": decision.model_dump(mode="json"),
        "systemOutcome": "SKIPPED",
        "systemReason": system_reason,
        "intentCreated": False,
        "lifecycle": lifecycle,
    }


def demo_summaries() -> list[dict[str, Any]]:
    results = [build_demo_result(definition.scenario_id) for definition in SCENARIOS]
    return [
        {
            "scenarioId": result["scenarioId"],
            "title": result["title"],
            "description": result["description"],
            "timestamp": result["timestamp"],
            "selectedPair": result["decision"]["pair"],
            "decision": result["decision"]["action"],
            "confidence": result["decision"]["confidence"],
            "systemOutcome": result["systemOutcome"],
            "reason": (
                result["policy"]["reasonCode"]
                if result["policy"]["result"] == "REJECTED"
                else result["systemReason"]
            ),
            "policy": result["policy"]["result"],
        }
        for result in results
    ]
