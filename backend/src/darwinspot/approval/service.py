from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from darwinspot.domain import new_idempotency_key, now_utc
from darwinspot.notifications.outbox import (
    EXECUTION_KIND,
    RESULT_KIND,
    enqueue_unique,
)
from darwinspot.storage.models import TradeIntent, TradeIntentApproval

ApprovalDecision = Literal["APPROVE", "REJECT"]
ApprovalSource = Literal["TELEGRAM", "WEB"]


class ApprovalError(ValueError):
    pass


class UnauthorizedApproval(ApprovalError):
    pass


@dataclass(frozen=True)
class ApprovalResult:
    approval_id: str
    intent_id: str
    approval_status: str
    intent_state: str
    changed: bool


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class TradeIntentApprovalService:
    def __init__(self, db: Session, *, default_ttl_seconds: int = 90) -> None:
        if not 30 <= default_ttl_seconds <= 180:
            raise ValueError("approval TTL must be between 30 and 180 seconds")
        self.db = db
        self.default_ttl_seconds = default_ttl_seconds

    def create_waiting_approval(
        self,
        intent: TradeIntent,
        *,
        operator_user_id: str,
        operator_chat_id: str,
        ttl_seconds: int | None = None,
    ) -> TradeIntentApproval:
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if not 30 <= ttl <= 180:
            raise ValueError("approval TTL must be between 30 and 180 seconds")
        if intent.local_state not in {"PROPOSED", "WAITING_FOR_APPROVAL"}:
            raise ApprovalError("only a new intent can receive an approval")
        now = now_utc()
        intent.local_state = "WAITING_FOR_APPROVAL"
        intent.updated_at = now
        approval = TradeIntentApproval(
            approval_id=new_idempotency_key(),
            intent_id=intent.id,
            operator_user_id=operator_user_id,
            operator_chat_id=operator_chat_id,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
            status="PENDING",
            updated_at=now,
        )
        self.db.add(approval)
        enqueue_unique(
            self.db,
            kind="TELEGRAM_PROPOSAL",
            aggregate_id=intent.id,
            payload={"approval_id": approval.approval_id, "intent_id": intent.id},
            dedupe_key=f"telegram-proposal:{approval.approval_id}",
        )
        self.db.commit()
        return approval

    def decide(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        *,
        operator_user_id: str,
        operator_chat_id: str,
        source: ApprovalSource,
    ) -> ApprovalResult:
        approval = self.db.scalar(
            select(TradeIntentApproval)
            .where(TradeIntentApproval.approval_id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise ApprovalError("approval not found")
        if source == "TELEGRAM" and (
            str(approval.operator_user_id) != str(operator_user_id)
            or str(approval.operator_chat_id) != str(operator_chat_id)
        ):
            raise UnauthorizedApproval("approval identity is not authorized")
        intent = self.db.get(TradeIntent, approval.intent_id)
        if intent is None:
            raise ApprovalError("approval intent not found")
        if approval.status != "PENDING":
            return ApprovalResult(
                approval.approval_id,
                intent.id,
                approval.status,
                intent.local_state,
                False,
            )
        if intent.local_state != "WAITING_FOR_APPROVAL":
            raise ApprovalError("approval and intent state are inconsistent")
        now = now_utc()
        if _aware(approval.expires_at) <= now:
            approval.status = "EXPIRED"
            approval.decided_at = now
            approval.decision_source = source
            approval.updated_at = now
            intent.local_state = "APPROVAL_EXPIRED"
            intent.updated_at = now
            enqueue_unique(
                self.db,
                kind=RESULT_KIND,
                aggregate_id=intent.id,
                payload={"intent_id": intent.id, "result": "APPROVAL_EXPIRED"},
                dedupe_key=f"telegram-result:{intent.id}:APPROVAL_EXPIRED",
            )
            self.db.commit()
            return ApprovalResult(
                approval.approval_id, intent.id, approval.status, intent.local_state, True
            )
        approval.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
        approval.decided_at = now
        approval.decision_source = source
        approval.updated_at = now
        intent.local_state = "APPROVED" if decision == "APPROVE" else "REJECTED"
        intent.updated_at = now
        if decision == "APPROVE":
            enqueue_unique(
                self.db,
                kind=EXECUTION_KIND,
                aggregate_id=intent.id,
                payload={"approval_id": approval.approval_id, "intent_id": intent.id},
                dedupe_key=f"execute-approved:{approval.approval_id}",
            )
        else:
            enqueue_unique(
                self.db,
                kind=RESULT_KIND,
                aggregate_id=intent.id,
                payload={"intent_id": intent.id, "result": "REJECTED"},
                dedupe_key=f"telegram-result:{intent.id}:REJECTED",
            )
        self.db.commit()
        return ApprovalResult(
            approval.approval_id, intent.id, approval.status, intent.local_state, True
        )

    def expire_due(self, *, now: datetime | None = None) -> int:
        current = (now or now_utc()).astimezone(UTC)
        approvals = list(
            self.db.scalars(
                select(TradeIntentApproval)
                .where(
                    TradeIntentApproval.status == "PENDING",
                    TradeIntentApproval.expires_at <= current,
                )
                .with_for_update(skip_locked=True)
            ).all()
        )
        changed = 0
        for approval in approvals:
            intent = self.db.get(TradeIntent, approval.intent_id)
            if intent is None or intent.local_state != "WAITING_FOR_APPROVAL":
                continue
            approval.status = "EXPIRED"
            approval.decided_at = current
            approval.updated_at = current
            intent.local_state = "APPROVAL_EXPIRED"
            intent.updated_at = current
            enqueue_unique(
                self.db,
                kind=RESULT_KIND,
                aggregate_id=intent.id,
                payload={"intent_id": intent.id, "result": "APPROVAL_EXPIRED"},
                dedupe_key=f"telegram-result:{intent.id}:APPROVAL_EXPIRED",
            )
            changed += 1
        self.db.commit()
        return changed

    def claim_for_execution(self, approval_id: str) -> tuple[TradeIntentApproval, TradeIntent]:
        approval = self.db.scalar(
            select(TradeIntentApproval)
            .where(TradeIntentApproval.approval_id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise ApprovalError("approval not found")
        intent = self.db.get(TradeIntent, approval.intent_id)
        if intent is None:
            raise ApprovalError("approval intent not found")
        if approval.status == "APPROVED" and intent.local_state == "APPROVED":
            approval.status = "EXECUTING"
            approval.updated_at = now_utc()
            intent.local_state = "REVALIDATING"
            intent.updated_at = now_utc()
            self.db.commit()
            return approval, intent
        if approval.status == "EXECUTING" and intent.local_state in {
            "REVALIDATING",
            "WAITING_FOR_EXECUTION_CONFIRMATION",
        }:
            return approval, intent
        raise ApprovalError("approval is not available for execution")

    def consume(
        self,
        approval_id: str,
        *,
        intent_state: str,
        reason: str,
    ) -> None:
        approval = self.db.scalar(
            select(TradeIntentApproval)
            .where(TradeIntentApproval.approval_id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise ApprovalError("approval not found")
        intent = self.db.get(TradeIntent, approval.intent_id)
        if intent is None:
            raise ApprovalError("approval intent not found")
        if approval.status not in {"EXECUTING", "APPROVED"}:
            raise ApprovalError("approval cannot be consumed from its current state")
        approval.status = "CONSUMED"
        approval.updated_at = now_utc()
        intent.local_state = intent_state
        intent.updated_at = now_utc()
        enqueue_unique(
            self.db,
            kind=RESULT_KIND,
            aggregate_id=intent.id,
            payload={"intent_id": intent.id, "result": intent_state, "reason": reason[:512]},
            dedupe_key=f"telegram-result:{intent.id}:{intent_state}",
        )
        self.db.commit()
