from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Action = Literal["HOLD", "BUY", "SELL", "CANCEL", "CANCEL_REPLACE"]
OrderType = Literal["MARKET", "LIMIT"]
OrderSide = Literal["BUY", "SELL"]
TimeInForce = Literal["GTC", "IOC", "FOK"]


class PairSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair: str = Field(pattern=r"^[A-Z0-9]{5,20}$")


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    pair: str | None = Field(default=None, pattern=r"^[A-Z0-9]{5,20}$")
    order_type: OrderType | None = None
    side: OrderSide | None = None
    quantity: Decimal | None = Field(default=None, gt=Decimal("0"))
    price: Decimal | None = Field(default=None, gt=Decimal("0"))
    time_in_force: TimeInForce | None = "GTC"
    cancel_order_id: str | None = None
    rationale: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(min_length=1, max_length=20)
    mandate_version: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> AgentDecision:
        if self.action in {"BUY", "SELL", "CANCEL_REPLACE"} and self.pair is None:
            raise ValueError("trade actions require a pair")
        if self.action in {"BUY", "SELL", "CANCEL_REPLACE"} and self.quantity is None:
            raise ValueError("trade actions require quantity")
        if self.action in {"CANCEL", "CANCEL_REPLACE"} and self.cancel_order_id is None:
            raise ValueError("cancel actions require cancel_order_id")
        if self.action == "CANCEL_REPLACE" and self.side is None:
            raise ValueError("cancel and replace actions require replacement side")
        if self.action == "BUY" and self.side not in {None, "BUY"}:
            raise ValueError("buy actions cannot carry a sell side")
        if self.action == "SELL" and self.side not in {None, "SELL"}:
            raise ValueError("sell actions cannot carry a buy side")
        if (
            self.action in {"BUY", "SELL", "CANCEL_REPLACE"}
            and self.order_type == "LIMIT"
            and self.price is None
        ):
            raise ValueError("limit actions require a price")
        return self
