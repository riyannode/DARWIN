from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MandateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trading_mandate: str = Field(min_length=1, max_length=4000)
    allowed_symbols: list[str] = Field(min_length=1, max_length=100)
    max_order_notional: Decimal = Field(gt=Decimal("0"), max_digits=30, decimal_places=12)
    max_open_actionable_intents: int = Field(gt=0, le=100)

    @field_validator("allowed_symbols")
    @classmethod
    def validate_symbols(cls, values: list[str]) -> list[str]:
        if any(
            not value.isascii() or not value.isupper() or not value.isalnum() for value in values
        ):
            raise ValueError("allowed_symbols must contain exact uppercase alphanumeric symbols")
        if len(set(values)) != len(values):
            raise ValueError("allowed_symbols must not contain duplicates")
        return values
