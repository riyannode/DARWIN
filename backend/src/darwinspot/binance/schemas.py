from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    price: Decimal = Field(gt=Decimal("0"))
    timestamp: datetime | None
    observed_at: datetime


class BalanceAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    free: Decimal = Field(ge=Decimal("0"))
    locked: Decimal = Field(ge=Decimal("0"))


class BalanceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime | None
    observed_at: datetime
    balances: list[BalanceAsset]


class UpstreamOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(validation_alias=AliasChoices("order_id", "orderId"))
    symbol: str
    status: str
    executed_quantity: Decimal = Field(
        ge=Decimal("0"), validation_alias=AliasChoices("executed_quantity", "executedQty")
    )
    quote_notional: Decimal = Field(
        ge=Decimal("0"),
        validation_alias=AliasChoices(
            "quote_notional", "cummulativeQuoteQty", "cumulativeQuoteQty", "quoteNotional"
        ),
    )
    updated_at: datetime = Field(
        validation_alias=AliasChoices(
            "updated_at", "updateTime", "transactTime", "workingTime", "time"
        )
    )


class OpenOrdersSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime | None
    observed_at: datetime
    orders: list[UpstreamOrder]


class RecentActivitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime | None
    observed_at: datetime
    items: list[dict[str, Any]]


class SymbolFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    quote_asset: str = Field(validation_alias=AliasChoices("quote_asset", "quoteAsset"))
    min_quantity: Decimal = Field(
        gt=Decimal("0"), validation_alias=AliasChoices("min_quantity", "minQty")
    )
    step_size: Decimal = Field(
        gt=Decimal("0"), validation_alias=AliasChoices("step_size", "stepSize")
    )
    tick_size: Decimal = Field(
        gt=Decimal("0"), validation_alias=AliasChoices("tick_size", "tickSize")
    )
    min_notional: Decimal = Field(
        gt=Decimal("0"), validation_alias=AliasChoices("min_notional", "minNotional", "notional")
    )
    timestamp: datetime | None
    observed_at: datetime


class OrderSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(validation_alias=AliasChoices("order_id", "orderId"))
    status: str
    symbol: str | None = None
    executed_quantity: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        validation_alias=AliasChoices("executed_quantity", "executedQty"),
    )
    quote_notional: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        validation_alias=AliasChoices(
            "quote_notional", "cummulativeQuoteQty", "cumulativeQuoteQty", "quoteNotional"
        ),
    )
    updated_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "updated_at", "updateTime", "transactTime", "workingTime", "time"
        ),
    )
