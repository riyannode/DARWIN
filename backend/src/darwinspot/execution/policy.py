from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from darwinspot.agent.schemas import AgentDecision
from darwinspot.binance.schemas import (
    BalanceSnapshot,
    MarketSnapshot,
    OpenOrdersSnapshot,
    SymbolFilters,
)
from darwinspot.execution.budget import BudgetSnapshot


@dataclass(frozen=True)
class ExecutionPolicy:
    allowed_symbols: frozenset[str]
    max_order_notional: Decimal
    max_open_actionable_intents: int

    def __post_init__(self) -> None:
        if not self.allowed_symbols:
            raise ValueError("allowed_symbols must not be empty")
        if any(symbol != symbol.upper() for symbol in self.allowed_symbols):
            raise ValueError("allowed_symbols must contain uppercase symbols")
        if not self.max_order_notional.is_finite() or self.max_order_notional <= 0:
            raise ValueError("max_order_notional must be finite and positive")
        if self.max_open_actionable_intents <= 0:
            raise ValueError("max_open_actionable_intents must be positive")


@dataclass(frozen=True)
class PolicyEvaluation:
    allowed: bool
    reason: str | None
    mandate_result: str
    risk_result: str
    budget_result: str
    execution_policy_result: str
    computed_notional: Decimal | None


def _rejected(reason: str, *, budget_result: str = "NOT_EVALUATED") -> PolicyEvaluation:
    return PolicyEvaluation(
        allowed=False,
        reason=reason,
        mandate_result="FAIL" if "allowed_symbols" in reason else "PASS",
        risk_result="FAIL" if "risk" in reason or "balance" in reason else "PASS",
        budget_result=budget_result,
        execution_policy_result="FAIL",
        computed_notional=None,
    )


def evaluate_execution_policy(
    policy: ExecutionPolicy,
    *,
    decision: AgentDecision,
    market: MarketSnapshot,
    balances: BalanceSnapshot,
    filters: SymbolFilters,
    open_orders: OpenOrdersSnapshot,
    budget: BudgetSnapshot,
    emergency_stop: bool,
    actionable_intent_count: int,
) -> PolicyEvaluation:
    if emergency_stop:
        return _rejected("emergency stop is active")
    if decision.action not in {"BUY", "SELL"}:
        return _rejected("only BUY and SELL decisions can be actionable")
    if decision.pair is None or decision.pair not in policy.allowed_symbols:
        return _rejected("symbol is not in allowed_symbols")
    if decision.pair != market.symbol or decision.pair != filters.symbol:
        return _rejected("risk evidence does not match the decision pair")
    if actionable_intent_count >= policy.max_open_actionable_intents:
        return _rejected("max_open_actionable_intents reached")
    if any(
        order.symbol == decision.pair and order.status in {"NEW", "OPEN", "PARTIALLY_FILLED"}
        for order in open_orders.orders
    ):
        return _rejected("an open order already exists for this symbol")
    if decision.quantity is None or not decision.quantity.is_finite():
        return _rejected("risk requires a finite quantity")
    if decision.quantity < filters.min_quantity or decision.quantity % filters.step_size != 0:
        return _rejected("quantity fails Binance symbol filters")
    if decision.order_type == "LIMIT":
        if decision.price is None or not decision.price.is_finite():
            return _rejected("limit order requires a finite price")
        if decision.price % filters.tick_size != 0:
            return _rejected("price fails Binance symbol filters")
        reference_price = decision.price
    else:
        reference_price = market.price
    computed_notional = decision.quantity * reference_price
    if not computed_notional.is_finite() or computed_notional <= 0:
        return _rejected("risk notional must be finite and positive")
    if computed_notional > policy.max_order_notional:
        return _rejected("max_order_notional exceeded")
    if computed_notional < filters.min_notional:
        return _rejected("order notional is below Binance minimum notional")
    if decision.action == "BUY":
        if not budget.can_buy(computed_notional):
            return _rejected("buy exceeds available budget", budget_result="EXCEEDED")
        asset = filters.quote_asset
        required = computed_notional
        budget_result = "PASS"
    else:
        asset = decision.pair.removesuffix(filters.quote_asset)
        required = decision.quantity
        budget_result = "NOT_APPLICABLE"
    available = next((item.free for item in balances.balances if item.asset == asset), None)
    if available is None or available < required:
        return _rejected(f"insufficient available {asset} balance")
    return PolicyEvaluation(
        allowed=True,
        reason=None,
        mandate_result="PASS",
        risk_result="PASS",
        budget_result=budget_result,
        execution_policy_result="PASS",
        computed_notional=computed_notional,
    )
