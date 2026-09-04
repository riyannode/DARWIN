from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal


class BudgetExceeded(ValueError):
    pass


BUY_BUDGET_RESERVATION_STATES = frozenset(
    {
        "WAITING_FOR_APPROVAL",
        "APPROVED",
        "AUTO_AUTHORIZED",
        "REVALIDATING",
        "WAITING_FOR_EXECUTION_CONFIRMATION",
        "SUBMITTING",
        "SUBMISSION_UNKNOWN",
        "OPEN",
        "PARTIALLY_FILLED",
        "CANCEL_PENDING",
        "CANCEL_BLOCKED",
    }
)


@dataclass(frozen=True)
class BuyFill:
    quote_notional: Decimal
    observed_at: datetime


@dataclass(frozen=True)
class OpenBuyCommitment:
    quote_notional: Decimal


@dataclass(frozen=True)
class BudgetSnapshot:
    daily_budget: Decimal
    spent_amount: Decimal
    available_budget: Decimal

    def can_buy(self, quote_notional: Decimal) -> bool:
        return (
            quote_notional.is_finite()
            and quote_notional >= Decimal("0")
            and quote_notional <= self.available_budget
        )

    @property
    def can_sell(self) -> bool:
        return True


def calculate_budget(
    daily_budget: Decimal,
    now: datetime,
    buy_fills: list[BuyFill],
    open_buy_commitments: list[OpenBuyCommitment],
) -> BudgetSnapshot:
    if daily_budget <= Decimal("0"):
        raise ValueError("daily budget must be positive")
    cutoff = now.astimezone(UTC) - timedelta(hours=24)
    recent_fills = sum(
        (fill.quote_notional for fill in buy_fills if fill.observed_at.astimezone(UTC) >= cutoff),
        Decimal("0"),
    )
    committed = sum((item.quote_notional for item in open_buy_commitments), Decimal("0"))
    spent = recent_fills + committed
    return BudgetSnapshot(
        daily_budget=daily_budget,
        spent_amount=spent,
        available_budget=max(Decimal("0"), daily_budget - spent),
    )
