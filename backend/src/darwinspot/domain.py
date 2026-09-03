from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid7


class AgentState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED_CONNECTION = "PAUSED_CONNECTION"
    PAUSED_ERROR = "PAUSED_ERROR"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class DecisionAction(StrEnum):
    HOLD = "HOLD"
    BUY = "BUY"
    SELL = "SELL"
    CANCEL = "CANCEL"
    CANCEL_REPLACE = "CANCEL_REPLACE"


def now_utc() -> datetime:
    return datetime.now(UTC)


def new_idempotency_key() -> str:
    return str(uuid7())


def decimal_string(value: Decimal) -> str:
    return format(value, "f")
