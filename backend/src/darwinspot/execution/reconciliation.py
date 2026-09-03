from __future__ import annotations

from dataclasses import dataclass

from darwinspot.execution.orders import IntentState, next_state


@dataclass(frozen=True)
class ReconciliationResult:
    state: IntentState
    exchange_state: str


def reconcile_submission_unknown(exchange_status: str) -> ReconciliationResult:
    mapping = {
        "NEW": ("reconciled_open", IntentState.OPEN),
        "OPEN": ("reconciled_open", IntentState.OPEN),
        "PARTIALLY_FILLED": ("reconciled_partial", IntentState.PARTIALLY_FILLED),
        "FILLED": ("reconciled_filled", IntentState.FILLED),
        "CANCELED": ("reconciled_canceled", IntentState.CANCELED),
        "EXPIRED": ("reconciled_expired", IntentState.EXPIRED),
        "REJECTED": ("reconciled_rejected", IntentState.REJECTED_EXCHANGE),
    }
    try:
        event, _ = mapping[exchange_status]
    except KeyError as exc:
        raise ValueError(f"unknown exchange status: {exchange_status}") from exc
    return ReconciliationResult(
        state=next_state(IntentState.SUBMISSION_UNKNOWN, event), exchange_state=exchange_status
    )
