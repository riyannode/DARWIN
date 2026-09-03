from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from darwinspot.agent.schemas import AgentDecision
from darwinspot.binance.schemas import BalanceSnapshot, MarketSnapshot, SymbolFilters
from darwinspot.execution.budget import BudgetSnapshot
from darwinspot.execution.orders import EmergencyStop


@dataclass(frozen=True)
class GateResult:
    result: str
    committed_notional: Decimal | None
    reason: str | None = None


class ExecutionGateway:
    """Deterministic boundary between a typed model decision and order submission."""

    def __init__(
        self,
        budget: BudgetSnapshot,
        emergency_stop: EmergencyStop,
        market: MarketSnapshot | None = None,
        balances: BalanceSnapshot | None = None,
        filters: SymbolFilters | None = None,
    ) -> None:
        self.budget = budget
        self.emergency_stop = emergency_stop
        self.market = market
        self.balances = balances
        self.filters = filters

    def check(self, decision: AgentDecision) -> GateResult:
        if not self.emergency_stop.can_submit:
            return GateResult("REJECTED_STOP", None, "emergency stop is active")
        is_buy = decision.action == "BUY" or (
            decision.action == "CANCEL_REPLACE" and decision.side == "BUY"
        )
        if is_buy:
            notional = self._computed_buy_notional(decision)
            if not self.budget.can_buy(notional):
                return GateResult("BUDGET_EXCEEDED", None, "buy exceeds Available Budget")
            correctness = self._check_order(decision, notional)
            if correctness is not None:
                return GateResult("REJECTED_CORRECTNESS", None, correctness)
            return GateResult("ALLOW", notional)
        if decision.action == "SELL" or (
            decision.action == "CANCEL_REPLACE" and decision.side == "SELL"
        ):
            if decision.quantity is None:
                return GateResult("REJECTED_CORRECTNESS", None, "sell requires quantity")
            correctness = self._check_order(decision, None)
            if correctness is not None:
                return GateResult("REJECTED_CORRECTNESS", None, correctness)
        if decision.action in {"SELL", "CANCEL", "CANCEL_REPLACE", "HOLD"}:
            return GateResult("ALLOW", None)
        return GateResult("REJECTED_SCHEMA", None, "unsupported action")

    def _computed_buy_notional(self, decision: AgentDecision) -> Decimal:
        if decision.quantity is None:
            raise ValueError("buy requires quantity")
        if not decision.quantity.is_finite():
            raise ValueError("buy quantity must be finite")
        if decision.order_type == "LIMIT":
            if decision.price is None:
                raise ValueError("limit buy requires price")
            notional = decision.quantity * decision.price
        else:
            if self.market is None:
                raise ValueError("market data is required for a market buy")
            notional = decision.quantity * self.market.price
        if notional <= Decimal("0") or notional.is_finite() is False:
            raise ValueError("computed buy notional must be finite and positive")
        return notional

    def _check_order(self, decision: AgentDecision, notional: Decimal | None) -> str | None:
        if self.market is None or self.balances is None or self.filters is None:
            return "live market, balance, and symbol filters are required"
        if decision.pair != self.market.symbol or self.filters.symbol != decision.pair:
            return "market and symbol filter snapshots do not match the decision pair"
        if self.filters.quote_asset != "USDT":
            return "selected pair quote asset is incompatible with the configured USDT budget"
        if decision.quantity is None or not decision.quantity.is_finite():
            return "order requires a finite quantity"
        if decision.quantity < self.filters.min_quantity:
            return "quantity is below Binance minimum quantity"
        if decision.quantity % self.filters.step_size != 0:
            return "quantity does not satisfy Binance step size"
        if decision.order_type == "LIMIT":
            if decision.price is None:
                return "limit order requires price"
            if decision.price % self.filters.tick_size != 0:
                return "price does not satisfy Binance tick size"
        is_buy = decision.action == "BUY" or (
            decision.action == "CANCEL_REPLACE" and decision.side == "BUY"
        )
        order_notional = notional or decision.quantity * (decision.price or self.market.price)
        if order_notional < self.filters.min_notional:
            return "order notional is below Binance minimum notional"
        asset = decision.pair.removesuffix(self.filters.quote_asset) if decision.pair else ""
        balance_asset = self.filters.quote_asset if is_buy else asset
        available = next(
            (item.free for item in self.balances.balances if item.asset == balance_asset), None
        )
        required = order_notional if is_buy else decision.quantity
        if available is None or available < required:
            return f"insufficient available {balance_asset} balance"
        return None
