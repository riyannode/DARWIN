from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from darwinspot.domain import new_idempotency_key, now_utc
from darwinspot.storage.models import OutboxMessage

PROPOSAL_KIND = "TELEGRAM_PROPOSAL"
RESULT_KIND = "TELEGRAM_RESULT"
EXECUTION_KIND = "EXECUTE_APPROVED_INTENT"
EMERGENCY_CANCEL_KIND = "EMERGENCY_STOP_CANCEL"
CONFIRMATION_KIND = "RESOLVE_EXECUTION_CONFIRMATION"


class OutboxError(RuntimeError):
    pass


def enqueue_unique(
    db: Session,
    *,
    kind: str,
    aggregate_id: str,
    payload: dict[str, Any],
    dedupe_key: str,
) -> OutboxMessage:
    existing = db.scalar(select(OutboxMessage).where(OutboxMessage.dedupe_key == dedupe_key))
    if existing is not None:
        return existing
    now = now_utc()
    message = OutboxMessage(
        id=new_idempotency_key(),
        dedupe_key=dedupe_key,
        kind=kind,
        aggregate_id=aggregate_id,
        payload=json.dumps(payload, default=str, sort_keys=True),
        status="PENDING",
        attempts=0,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(message)
            db.flush()
    except IntegrityError:
        existing = db.scalar(select(OutboxMessage).where(OutboxMessage.dedupe_key == dedupe_key))
        if existing is None:
            raise
        return existing
    return message


def claim_due(
    db: Session,
    *,
    worker_id: str,
    limit: int = 20,
    lease_seconds: int = 60,
    now: datetime | None = None,
) -> list[OutboxMessage]:
    current = (now or now_utc()).astimezone(UTC)
    rows = list(
        db.scalars(
            select(OutboxMessage)
            .where(
                OutboxMessage.available_at <= current,
                or_(
                    OutboxMessage.status == "PENDING",
                    and_(
                        OutboxMessage.status == "PROCESSING",
                        OutboxMessage.lease_until.is_not(None),
                        OutboxMessage.lease_until <= current,
                    ),
                ),
            )
            .order_by(OutboxMessage.available_at.asc(), OutboxMessage.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )
    lease_until = current + timedelta(seconds=lease_seconds)
    for row in rows:
        row.status = "PROCESSING"
        row.attempts += 1
        row.lease_owner = worker_id
        row.lease_until = lease_until
        row.updated_at = current
    db.commit()
    return rows


def mark_sent(db: Session, *, message_id: str, worker_id: str) -> None:
    row = db.scalar(
        select(OutboxMessage)
        .where(
            OutboxMessage.id == message_id,
            OutboxMessage.status == "PROCESSING",
            OutboxMessage.lease_owner == worker_id,
        )
        .with_for_update()
    )
    if row is None:
        raise OutboxError("outbox message is not owned by this worker")
    now = now_utc()
    row.status = "SENT"
    row.sent_at = now
    row.lease_until = None
    row.lease_owner = None
    row.updated_at = now
    db.commit()


def mark_skipped(db: Session, *, message_id: str, worker_id: str, reason: str) -> None:
    row = db.scalar(
        select(OutboxMessage)
        .where(
            OutboxMessage.id == message_id,
            OutboxMessage.status == "PROCESSING",
            OutboxMessage.lease_owner == worker_id,
        )
        .with_for_update()
    )
    if row is None:
        raise OutboxError("outbox message is not owned by this worker")
    row.status = "SENT"
    row.last_error = reason[:512]
    row.lease_until = None
    row.lease_owner = None
    row.updated_at = now_utc()
    db.commit()


def mark_retry(
    db: Session,
    *,
    message_id: str,
    worker_id: str,
    error: str,
    delay_seconds: int,
) -> None:
    row = db.scalar(
        select(OutboxMessage)
        .where(
            OutboxMessage.id == message_id,
            OutboxMessage.status == "PROCESSING",
            OutboxMessage.lease_owner == worker_id,
        )
        .with_for_update()
    )
    if row is None:
        raise OutboxError("outbox message is not owned by this worker")
    now = now_utc()
    row.status = "PENDING"
    row.available_at = now + timedelta(seconds=max(1, delay_seconds))
    row.lease_until = None
    row.lease_owner = None
    row.last_error = error[:512]
    row.updated_at = now
    db.commit()


def payload(row: OutboxMessage) -> dict[str, Any]:
    try:
        value = json.loads(row.payload)
    except json.JSONDecodeError as exc:
        raise OutboxError("outbox payload is not valid JSON") from exc
    if not isinstance(value, dict):
        raise OutboxError("outbox payload must be an object")
    return cast(dict[str, Any], value)
