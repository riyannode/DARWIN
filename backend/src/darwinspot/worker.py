"""Long-running DARWIN scheduler and durable-work processor."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx2
import openai
from sqlalchemy import select

from darwinspot.agent.cycle import (
    CycleConfigurationError,
    CycleUnavailable,
    SubmissionUncertain,
    run_cycle,
)
from darwinspot.agent.runtime import AgentRuntime, ModelResponseError
from darwinspot.approval.service import TradeIntentApprovalService
from darwinspot.binance.client import AgentOSAuthInvalid, AgentOSUnavailable, UnsupportedCapability
from darwinspot.binance.codex_transport import (
    CodexAuthRequired,
    CodexTransportError,
    ElicitationAction,
    discard_pending_confirmation,
    resolve_pending_confirmation,
)
from darwinspot.binance.factory import build_binance_client
from darwinspot.binance.mapper import BinanceMappingError
from darwinspot.config import Settings, get_settings
from darwinspot.execution.approved import (
    ApprovedExecution,
    account_execution_lock,
)
from darwinspot.execution.demo_guard import FinancialWriteBlocked
from darwinspot.notifications.outbox import (
    CONFIRMATION_KIND,
    EMERGENCY_CANCEL_KIND,
    EXECUTION_KIND,
    PROPOSAL_KIND,
    RESULT_KIND,
    claim_due,
    mark_retry,
    mark_sent,
    mark_skipped,
    payload,
)
from darwinspot.notifications.telegram import (
    TelegramDeliveryError,
    TelegramNotConfigured,
    TelegramNotifier,
)
from darwinspot.observability import log_event
from darwinspot.storage.database import SessionLocal
from darwinspot.storage.models import TradeIntent, TradeIntentApproval
from darwinspot.storage.repository import Repository

_TRANSIENT_OPENAI_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_MAX_BACKOFF_SECONDS = 60


def _validate_worker_config(settings: Settings) -> None:
    missing = [
        name
        for name, value in (
            ("OPENAI_API_KEY", settings.openai_api_key),
            ("OPENAI_MODEL", settings.openai_model),
            ("CODEX_APP_SERVER_COMMAND", settings.codex_app_server_command),
        )
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        raise RuntimeError(f"worker configuration is missing: {', '.join(missing)}")


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, (AgentOSAuthInvalid, CycleConfigurationError, UnsupportedCapability)):
        return False
    if isinstance(
        exc,
        (
            AgentOSUnavailable,
            CodexAuthRequired,
            CodexTransportError,
            SubmissionUncertain,
            CycleUnavailable,
            ModelResponseError,
            TimeoutError,
            httpx2.RequestError,
            httpx2.TimeoutException,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
        ),
    ):
        return True
    return (
        isinstance(exc, openai.APIStatusError) and exc.status_code in _TRANSIENT_OPENAI_STATUS_CODES
    )


def _backoff_seconds(failure_streak: int) -> int:
    return min(2 ** max(0, failure_streak - 1), _MAX_BACKOFF_SECONDS)


async def _process_outbox_message(db: Any, row: Any, settings: Settings, worker_id: str) -> None:
    data = payload(row)
    try:
        if row.kind == CONFIRMATION_KIND:
            intent = db.get(TradeIntent, data.get("intent_id"))
            action = data.get("action")
            if (
                intent is None
                or intent.local_state != "WAITING_FOR_EXECUTION_CONFIRMATION"
                or action not in {"ACCEPT", "DECLINE", "CANCEL"}
            ):
                mark_skipped(
                    db,
                    message_id=row.id,
                    worker_id=worker_id,
                    reason="confirmation work is invalid",
                )
                return
            with account_execution_lock(db, settings.binance_account_lock_key):
                db.refresh(intent)
                expires_at = intent.confirmation_expires_at
                if expires_at is not None:
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=UTC)
                    if expires_at.astimezone(UTC) <= datetime.now(UTC):
                        await discard_pending_confirmation(intent.id)
                        approval = db.scalar(
                            select(TradeIntentApproval)
                            .where(TradeIntentApproval.intent_id == intent.id)
                            .limit(1)
                        )
                        if approval is not None:
                            TradeIntentApprovalService(
                                db, default_ttl_seconds=settings.approval_ttl_seconds
                            ).resolve_execution_confirmation(
                                approval.approval_id,
                                reason="transport confirmation expired; reconciliation required",
                            )
                        else:
                            intent.local_state = "SUBMISSION_UNKNOWN"
                            intent.updated_at = datetime.now(UTC)
                            db.commit()
                        mark_sent(db, message_id=row.id, worker_id=worker_id)
                        return
                resolution = cast(ElicitationAction, str(action).lower())
                resolved = await resolve_pending_confirmation(intent.id, resolution)
                if not resolved:
                    await discard_pending_confirmation(intent.id)
                    approval = db.scalar(
                        select(TradeIntentApproval)
                        .where(TradeIntentApproval.intent_id == intent.id)
                        .limit(1)
                    )
                    if approval is not None:
                        TradeIntentApprovalService(
                            db, default_ttl_seconds=settings.approval_ttl_seconds
                        ).resolve_execution_confirmation(
                            approval.approval_id,
                            reason=(
                                "transport confirmation could not be resolved; "
                                "reconciliation required"
                            ),
                        )
                    else:
                        intent.local_state = "SUBMISSION_UNKNOWN"
                        intent.updated_at = datetime.now(UTC)
                        db.commit()
                    mark_sent(db, message_id=row.id, worker_id=worker_id)
                    return
                db.refresh(intent)
                if intent.local_state == "WAITING_FOR_EXECUTION_CONFIRMATION":
                    approval = db.scalar(
                        select(TradeIntentApproval)
                        .where(TradeIntentApproval.intent_id == intent.id)
                        .limit(1)
                    )
                    if approval is not None:
                        TradeIntentApprovalService(
                            db, default_ttl_seconds=settings.approval_ttl_seconds
                        ).resolve_execution_confirmation(
                            approval.approval_id,
                            reason="transport confirmation resolved; reconciliation required",
                        )
                    else:
                        intent.local_state = "SUBMISSION_UNKNOWN"
                        intent.updated_at = datetime.now(UTC)
                        db.commit()
                elif intent.local_state != "SUBMISSION_UNKNOWN":
                    mark_skipped(
                        db,
                        message_id=row.id,
                        worker_id=worker_id,
                        reason="confirmation was resolved after intent state changed",
                    )
                    return
                mark_sent(db, message_id=row.id, worker_id=worker_id)
            return
        if row.kind == PROPOSAL_KIND:
            intent = db.get(TradeIntent, data.get("intent_id"))
            approval = db.get(TradeIntentApproval, data.get("approval_id"))
            if intent is None or (intent.execution_mode == "HUMAN_APPROVAL" and approval is None):
                mark_skipped(
                    db, message_id=row.id, worker_id=worker_id, reason="approval aggregate missing"
                )
                return
            notifier = TelegramNotifier(settings)
            if intent.execution_mode == "AUTO_BOUNDED":
                delivery = await notifier.send_auto_signal(intent)
            else:
                if approval is None:
                    mark_skipped(
                        db,
                        message_id=row.id,
                        worker_id=worker_id,
                        reason="human approval aggregate missing",
                    )
                    return
                delivery = await notifier.send_proposal(intent, approval)
                approval.telegram_chat_id = delivery.chat_id
                approval.telegram_message_id = delivery.message_id
            db.commit()
            mark_sent(db, message_id=row.id, worker_id=worker_id)
            return
        if row.kind == RESULT_KIND:
            intent = db.get(TradeIntent, data.get("intent_id"))
            if intent is None:
                mark_skipped(
                    db, message_id=row.id, worker_id=worker_id, reason="intent aggregate missing"
                )
                return
            await TelegramNotifier(settings).send_result(
                intent, str(data.get("result", intent.local_state)), data.get("reason")
            )
            mark_sent(db, message_id=row.id, worker_id=worker_id)
            return
        if row.kind == EXECUTION_KIND:
            approval_id = data.get("approval_id")
            intent_id = data.get("intent_id")
            if not isinstance(approval_id, str) and not isinstance(intent_id, str):
                mark_skipped(
                    db,
                    message_id=row.id,
                    worker_id=worker_id,
                    reason="execution reference missing",
                )
                return
            intent = db.get(TradeIntent, intent_id)
            mode = intent.execution_mode if intent is not None else "HUMAN_APPROVAL"
            client = build_binance_client(settings, Repository(db).current_connection(), mode=mode)
            result: Any = None
            try:
                result = await ApprovedExecution(Repository(db), client).execute_claimed(
                    approval_id=approval_id if isinstance(approval_id, str) else None,
                    intent_id=intent_id if isinstance(intent_id, str) else None,
                )
            finally:
                transport = getattr(client, "transport", None)
                if transport is not None and (
                    result is None or result.state != "WAITING_FOR_EXECUTION_CONFIRMATION"
                ):
                    await transport.close()
            if result is None:
                raise RuntimeError("execution coordinator returned no result")
            if result.state in {
                "AUTH_REQUIRED",
                "REVALIDATION_PENDING",
                "WAITING_FOR_EXECUTION_CONFIRMATION",
                "SUBMISSION_UNKNOWN",
            }:
                mark_retry(
                    db,
                    message_id=row.id,
                    worker_id=worker_id,
                    error=result.reason or result.state,
                    delay_seconds=30,
                )
            else:
                mark_sent(db, message_id=row.id, worker_id=worker_id)
            return
        if row.kind == EMERGENCY_CANCEL_KIND:
            intent_id = data.get("intent_id")
            operator_action_id = data.get("operator_action_id")
            if not isinstance(intent_id, str) or not isinstance(operator_action_id, str):
                mark_skipped(
                    db, message_id=row.id, worker_id=worker_id, reason="emergency target is invalid"
                )
                return
            intent = db.get(TradeIntent, intent_id)
            mode = intent.execution_mode if intent is not None else "HUMAN_APPROVAL"
            client = build_binance_client(settings, Repository(db).current_connection(), mode=mode)
            try:
                result = await ApprovedExecution(Repository(db), client).cancel_for_emergency_stop(
                    intent_id, operator_action_id
                )
            finally:
                transport = getattr(client, "transport", None)
                if transport is not None:
                    await transport.close()
            if result.state in {"AUTH_REQUIRED", "CANCEL_PENDING", "CANCEL_BLOCKED"}:
                mark_retry(
                    db,
                    message_id=row.id,
                    worker_id=worker_id,
                    error=result.reason or result.state,
                    delay_seconds=30,
                )
            else:
                mark_sent(db, message_id=row.id, worker_id=worker_id)
            return
        mark_skipped(
            db, message_id=row.id, worker_id=worker_id, reason="unsupported outbox work kind"
        )
    except FinancialWriteBlocked as exc:
        if row.kind == CONFIRMATION_KIND:
            intent_id = data.get("intent_id")
            if isinstance(intent_id, str):
                intent = db.get(TradeIntent, intent_id)
                if intent is not None:
                    state = (
                        "FINANCIAL_WRITES_DISABLED"
                        if exc.reason_code == "FINANCIAL_WRITES_DISABLED"
                        else "BLOCKED"
                    )
                    approval = db.scalar(
                        select(TradeIntentApproval)
                        .where(TradeIntentApproval.intent_id == intent.id)
                        .limit(1)
                    )
                    if approval is not None and approval.status in {"EXECUTING", "APPROVED"}:
                        TradeIntentApprovalService(
                            db, default_ttl_seconds=settings.approval_ttl_seconds
                        ).consume(
                            approval.approval_id,
                            intent_state=state,
                            reason=exc.reason_code,
                        )
                    else:
                        intent.local_state = state
                        intent.updated_at = datetime.now(UTC)
                        db.commit()
                    Repository(db).complete_run(intent.agent_run_id, state, None, exc.reason_code)
        mark_skipped(
            db,
            message_id=row.id,
            worker_id=worker_id,
            reason=exc.reason_code,
        )
    except (TelegramDeliveryError, TelegramNotConfigured) as exc:
        mark_retry(db, message_id=row.id, worker_id=worker_id, error=str(exc), delay_seconds=30)
    except (AgentOSUnavailable, CodexAuthRequired, CodexTransportError) as exc:
        mark_retry(db, message_id=row.id, worker_id=worker_id, error=str(exc), delay_seconds=30)
    except (BinanceMappingError, TimeoutError, ValueError) as exc:
        mark_retry(db, message_id=row.id, worker_id=worker_id, error=str(exc), delay_seconds=30)


async def _process_outbox(settings: Settings) -> None:
    worker_id = f"worker-{id(asyncio.current_task())}"
    with SessionLocal() as db:
        rows = claim_due(db, worker_id=worker_id, limit=20, lease_seconds=60)
        for row in rows:
            await _process_outbox_message(db, row, settings, worker_id)


async def run_worker() -> None:
    settings = get_settings()
    _validate_worker_config(settings)
    if settings.openai_api_key is None:
        raise RuntimeError("worker configuration validation did not establish OPENAI_API_KEY")
    failure_streak = 0
    while True:
        sleep_seconds = settings.agent_cycle_seconds
        await _process_outbox(settings)
        with SessionLocal() as db:
            repo = Repository(db)
            TradeIntentApprovalService(
                db, default_ttl_seconds=settings.approval_ttl_seconds
            ).expire_due()
            config = repo.claim_due_run(settings.agent_cycle_seconds)
            if config is not None:
                run = repo.start_run("SCHEDULED", settings.openai_model)
                connection = repo.current_connection()
                client: Any = None
                try:
                    client = build_binance_client(settings, connection, mode=config.mode)
                    result = await asyncio.wait_for(
                        run_cycle(
                            repo,
                            client,
                            AgentRuntime(
                                settings.openai_api_key,
                                settings.openai_model,
                                settings.openai_base_url,
                            ),
                            run.id,
                        ),
                        timeout=60,
                    )
                except Exception as exc:
                    transient = _is_transient_error(exc)
                    if isinstance(exc, AgentOSAuthInvalid) and connection is not None:
                        repo.mark_connection_unavailable(connection.id)
                    repo.complete_run(run.id, "FAILED", None, str(exc))
                    if transient:
                        failure_streak += 1
                        sleep_seconds = _backoff_seconds(failure_streak)
                        config.next_run_at = datetime.now(UTC) + timedelta(seconds=sleep_seconds)
                    else:
                        log_event(
                            "AGENT_CYCLE_FAILED",
                            run_id=run.id,
                            error_code=type(exc).__name__,
                            transient=False,
                        )
                        db.commit()
                        raise
                    log_event(
                        "AGENT_CYCLE_FAILED",
                        run_id=run.id,
                        error_code=type(exc).__name__,
                        transient=True,
                        backoff_seconds=sleep_seconds,
                    )
                else:
                    failure_streak = 0
                    repo.complete_run(run.id, result, None, None)
                finally:
                    transport = getattr(client, "transport", None)
                    if transport is not None:
                        await transport.close()
                db.commit()
        await asyncio.sleep(sleep_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker())
