from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IntentState(StrEnum):
    PROPOSED = "PROPOSED"
    REJECTED_BUDGET = "REJECTED_BUDGET"
    READY = "READY"
    SUBMITTING = "SUBMITTING"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELED = "CANCELED"
    REJECTED_EXCHANGE = "REJECTED_EXCHANGE"
    EXPIRED = "EXPIRED"


class InvalidTransition(ValueError):
    pass


class SubmissionBlocked(ValueError):
    pass


_TRANSITIONS: dict[tuple[IntentState, str], IntentState] = {
    (IntentState.PROPOSED, "budget_rejected"): IntentState.REJECTED_BUDGET,
    (IntentState.PROPOSED, "budget_allowed"): IntentState.READY,
    (IntentState.READY, "submit"): IntentState.SUBMITTING,
    (IntentState.SUBMITTING, "unknown"): IntentState.SUBMISSION_UNKNOWN,
    (IntentState.SUBMITTING, "open"): IntentState.OPEN,
    (IntentState.SUBMITTING, "exchange_rejected"): IntentState.REJECTED_EXCHANGE,
    (IntentState.SUBMISSION_UNKNOWN, "reconciled_open"): IntentState.OPEN,
    (IntentState.SUBMISSION_UNKNOWN, "reconciled_partial"): IntentState.PARTIALLY_FILLED,
    (IntentState.SUBMISSION_UNKNOWN, "reconciled_filled"): IntentState.FILLED,
    (IntentState.SUBMISSION_UNKNOWN, "reconciled_canceled"): IntentState.CANCELED,
    (IntentState.SUBMISSION_UNKNOWN, "reconciled_expired"): IntentState.EXPIRED,
    (IntentState.SUBMISSION_UNKNOWN, "reconciled_rejected"): IntentState.REJECTED_EXCHANGE,
    (IntentState.OPEN, "partial_fill"): IntentState.PARTIALLY_FILLED,
    (IntentState.OPEN, "fill"): IntentState.FILLED,
    (IntentState.OPEN, "cancel_requested"): IntentState.CANCEL_PENDING,
    (IntentState.OPEN, "expired"): IntentState.EXPIRED,
    (IntentState.PARTIALLY_FILLED, "fill"): IntentState.FILLED,
    (IntentState.PARTIALLY_FILLED, "cancel_requested"): IntentState.CANCEL_PENDING,
    (IntentState.CANCEL_PENDING, "canceled"): IntentState.CANCELED,
    (IntentState.CANCEL_PENDING, "fill"): IntentState.FILLED,
}


def next_state(current: IntentState, event: str) -> IntentState:
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError as exc:
        raise InvalidTransition(f"cannot apply {event!r} to {current}") from exc


@dataclass
class Intent:
    idempotency_key: str
    pair: str
    side: str


class IntentRegistry:
    def __init__(self) -> None:
        self._intents: dict[str, Intent] = {}

    def create_or_get(self, idempotency_key: str, pair: str, side: str) -> Intent:
        existing = self._intents.get(idempotency_key)
        if existing is not None:
            if existing.pair != pair or existing.side != side:
                raise ValueError("idempotency key was reused for a different order")
            return existing
        intent = Intent(idempotency_key=idempotency_key, pair=pair, side=side)
        self._intents[idempotency_key] = intent
        return intent

    @property
    def size(self) -> int:
        return len(self._intents)

    def has(self, idempotency_key: str) -> bool:
        return idempotency_key in self._intents


class EmergencyStop:
    def __init__(self) -> None:
        self.enabled = False

    @property
    def can_submit(self) -> bool:
        return not self.enabled

    def enable(self) -> None:
        self.enabled = True

    def cancel_open_orders(
        self, registry: IntentRegistry, outcomes: dict[str, str]
    ) -> dict[str, str]:
        if not self.enabled:
            raise RuntimeError("emergency stop must be enabled first")
        return {key: outcomes[key] for key in outcomes if registry.has(key)}
