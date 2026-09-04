from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    price: Decimal = Field(gt=Decimal("0"))
    timestamp: datetime | None
    observed_at: datetime


MarketInterval = Literal["15m", "1h", "4h"]
SUPPORTED_MARKET_INTERVALS: tuple[MarketInterval, ...] = ("15m", "1h", "4h")
CANDIDATE_MARKET_INTERVALS: tuple[MarketInterval, ...] = ("15m", "1h")
MARKET_INTERVAL_SECONDS: dict[MarketInterval, int] = {
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}
HISTORY_CANDLE_COUNT = 48
HISTORY_REQUEST_LIMIT = HISTORY_CANDLE_COUNT + 1
CANDIDATE_CANDLE_COUNT = 10
CANDIDATE_HISTORY_REQUEST_LIMIT = CANDIDATE_CANDLE_COUNT + 1
MARKET_HISTORY_MAX_STALENESS_PERIODS = 2


class MarketCandle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_time: datetime
    close_time: datetime
    open: Decimal = Field(gt=Decimal("0"))
    high: Decimal = Field(gt=Decimal("0"))
    low: Decimal = Field(gt=Decimal("0"))
    close: Decimal = Field(gt=Decimal("0"))
    volume: Decimal = Field(ge=Decimal("0"))
    quote_volume: Decimal = Field(ge=Decimal("0"))
    trade_count: int | None = Field(default=None, ge=0)


class MarketHistorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    interval: MarketInterval
    candles: list[MarketCandle] = Field(
        min_length=HISTORY_CANDLE_COUNT,
        max_length=HISTORY_CANDLE_COUNT,
    )
    observed_at: datetime


class CandidateMarketHistorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    interval: MarketInterval
    candles: list[MarketCandle] = Field(
        min_length=CANDIDATE_CANDLE_COUNT,
        max_length=CANDIDATE_CANDLE_COUNT,
    )
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
