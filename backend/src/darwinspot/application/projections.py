from __future__ import annotations

import json
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from darwinspot.storage.models import AgentRun, OutboxMessage, TradeIntent, TradeIntentApproval
from darwinspot.storage.repository import Repository


def status_projection(db: Session) -> dict[str, Any]:
    repo = Repository(db)
    config = repo.get_or_create_agent()
    latest = repo.latest_decision_run()
    return {
        "mode": config.mode,
        "state": config.state,
        "emergencyStop": config.emergency_stop,
        "supportedSymbols": list(repo.supported_symbols()),
        "nextRunAt": config.next_run_at,
        "latestDecision": latest_decision_projection(latest),
    }


def mandate_projection(db: Session) -> dict[str, Any]:
    repo = Repository(db)
    mandate = repo.current_mandate()
    if mandate is None:
        return {"configured": False}
    return {
        "configured": True,
        "version": mandate.id,
        "tradingMandate": repo.mandate_text(mandate),
        "allowedSymbols": json.loads(mandate.allowed_symbols),
        "maxOrderNotional": str(mandate.max_order_notional),
        "maxOpenActionableIntents": mandate.max_open_actionable_intents,
        "createdAt": mandate.created_at,
    }


def budget_projection(db: Session) -> dict[str, Any]:
    repo = Repository(db)
    budget = repo.current_budget()
    if budget is None:
        return {"configured": False}
    snapshot = repo.budget_snapshot()
    return {
        "configured": True,
        "version": budget.id,
        "dailyBudget": str(budget.daily_budget),
        "availableBudget": str(snapshot.available_budget) if snapshot else None,
        "spentAmount": str(snapshot.spent_amount) if snapshot else None,
    }


def universe_projection(db: Session) -> dict[str, Any]:
    repo = Repository(db)
    mandate = repo.current_mandate()
    return {
        "configuredSymbols": list(repo.supported_symbols()),
        "allowedSymbols": json.loads(mandate.allowed_symbols) if mandate else [],
        "effectiveSymbols": None,
        "liveState": "NOT_QUERIED",
    }


def latest_decision_projection(run: AgentRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    decision: dict[str, Any] | None = None
    if run.decision:
        try:
            value = json.loads(run.decision)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            safe_value = cast(dict[str, Any], value)
            decision = {
                key: safe_value.get(key)
                for key in (
                    "action",
                    "pair",
                    "side",
                    "order_type",
                    "quantity",
                    "price",
                    "confidence",
                )
                if key in value
            }
    return {
        "id": run.id,
        "state": run.result_state,
        "trigger": run.trigger_type,
        "decision": decision,
        "rationale": run.rationale,
        "startedAt": run.started_at,
        "completedAt": run.completed_at,
        "mandateVersion": run.mandate_version,
        "budgetVersion": run.budget_version,
    }


def activity_projection(db: Session, *, limit: int = 25) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(limit, 50))
    runs = db.scalars(
        select(AgentRun).order_by(AgentRun.started_at.desc()).limit(bounded_limit)
    ).all()
    intents = db.scalars(
        select(TradeIntent).order_by(TradeIntent.created_at.desc()).limit(bounded_limit)
    ).all()
    approvals = {
        item.intent_id: item
        for item in db.scalars(select(TradeIntentApproval)).all()
    }
    events: list[dict[str, Any]] = []
    for run in runs:
        events.append(
            {
                "id": run.id,
                "type": (
                    "decision"
                    if run.trigger_type in {"SCHEDULED", "RUN_ONCE", "MCP_PROPOSAL"}
                    else "audit"
                ),
                "state": run.result_state,
                "timestamp": run.started_at,
                "trigger": run.trigger_type,
                "rationale": run.rationale,
                "latestDecision": latest_decision_projection(run),
            }
        )
    for intent in intents:
        approval = approvals.get(intent.id)
        events.append(
            {
                "id": intent.id,
                "type": "order",
                "state": intent.local_state,
                "timestamp": intent.created_at,
                "pair": intent.pair,
                "side": intent.side,
                "orderType": intent.order_type,
                "quantity": str(intent.quantity),
                "price": str(intent.price) if intent.price is not None else None,
                "approvalState": approval.status if approval else None,
                "executionMode": intent.execution_mode,
                "executionTransport": intent.execution_transport,
                "authorizationSource": intent.authorization_source,
            }
        )
    events.sort(key=lambda item: str(item["timestamp"]), reverse=True)
    return events[:bounded_limit]


def pending_trades_projection(db: Session, *, limit: int = 25) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(limit, 50))
    rows = db.scalars(
        select(TradeIntent)
        .where(
            TradeIntent.local_state.in_(
                [
                    "WAITING_FOR_APPROVAL",
                    "APPROVED",
                    "REJECTED",
                    "WAITING_FOR_EXECUTION_CONFIRMATION",
                    "REVALIDATING",
                    "SUBMITTING",
                    "SUBMISSION_UNKNOWN",
                ]
            )
        )
        .order_by(TradeIntent.created_at.desc())
        .limit(bounded_limit)
    ).all()
    approvals = {
        item.intent_id: item
        for item in db.scalars(select(TradeIntentApproval)).all()
    }
    return [
        {
            "intentId": intent.id,
            "state": intent.local_state,
            "pair": intent.pair,
            "side": intent.side,
            "orderType": intent.order_type,
            "quantity": str(intent.quantity),
            "price": str(intent.price) if intent.price is not None else None,
            "approvalId": approvals[intent.id].approval_id if intent.id in approvals else None,
            "approvalState": approvals[intent.id].status if intent.id in approvals else None,
            "createdAt": intent.created_at,
        }
        for intent in rows
    ]


def find_pending_approval(db: Session, intent_id: str) -> TradeIntentApproval | None:
    return db.scalar(
        select(TradeIntentApproval).where(TradeIntentApproval.intent_id == intent_id).limit(1)
    )


def outbox_counts(db: Session) -> dict[str, int]:
    values = db.scalars(select(OutboxMessage.kind)).all()
    return {kind: values.count(kind) for kind in set(values)}
