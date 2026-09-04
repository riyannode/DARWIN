from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl, BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from darwinspot.api.auth import current_owner, mutation_owner
from darwinspot.approval.service import (
    ApprovalError,
    TradeIntentApprovalService,
)
from darwinspot.binance.client import (
    AgentOSAuthInvalid,
    AgentOSUnavailable,
    BinanceAgentOSClient,
    DatabaseOAuthStorage,
    ToolCatalog,
)
from darwinspot.binance.codex_transport import (
    CodexAppServerTransport,
    CodexAuthRequired,
    CodexTransportError,
)
from darwinspot.config import get_settings
from darwinspot.notifications.telegram import (
    TelegramDeliveryError,
    TelegramNotConfigured,
    TelegramNotifier,
)
from darwinspot.observability import log_event
from darwinspot.security.encryption import (
    decrypt_connection_material,
    encrypt_connection_material,
)
from darwinspot.storage.database import SessionLocal, get_db
from darwinspot.storage.models import (
    AgentRun,
    BinanceConnection,
    OrderEvent,
    OutboxMessage,
    TradeIntent,
    TradeIntentApproval,
)
from darwinspot.storage.repository import Repository

router = APIRouter(tags=["activity"])


def _run_decision(run: AgentRun) -> dict[str, Any]:
    if not run.decision:
        return {}
    try:
        value = json.loads(run.decision)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _run_system_result(
    run: AgentRun, decision: dict[str, Any] | None = None
) -> tuple[str, str | None]:
    decision = decision if decision is not None else _run_decision(run)
    if decision.get("action") == "HOLD":
        return "SKIPPED", "NO_TRADE"
    if run.result_state in {
        "POLICY_REJECTED",
        "SIGNAL_SUPPRESSED",
        "NO_EFFECTIVE_SYMBOLS",
        "EMERGENCY_STOP",
        "FINANCIAL_WRITES_DISABLED",
    }:
        return "SKIPPED", (
            "FINANCIAL_WRITES_DISABLED"
            if run.result_state == "FINANCIAL_WRITES_DISABLED"
            else run.result_state
        )
    if run.result_state in {"WAITING_FOR_APPROVAL", "AUTO_AUTHORIZED"}:
        return "PENDING", run.result_state
    if run.result_state == "FAILED":
        return "FAILED", run.rationale
    return run.result_state, None


def _run_activity_event(run: AgentRun) -> dict[str, object]:
    is_decision = run.trigger_type in {"SCHEDULED", "RUN_ONCE"}
    decision = _run_decision(run) if is_decision else {}
    system_outcome, reason = _run_system_result(run, decision) if is_decision else (None, None)
    return {
        "id": run.id,
        "type": "decision" if is_decision else "audit",
        "state": run.result_state,
        "timestamp": run.started_at,
        "trigger": run.trigger_type,
        "rationale": run.rationale,
        "decision": decision.get("action"),
        "pair": decision.get("pair"),
        "confidence": decision.get("confidence"),
        "systemOutcome": system_outcome,
        "reason": reason,
    }


@dataclass
class PendingOAuth:
    connection_id: str
    redirect_ready: asyncio.Event
    authorization_url: str | None = None
    oauth_state: str | None = None
    error: str | None = None


class ConfirmationInput(BaseModel):
    action: Literal["ACCEPT", "DECLINE", "CANCEL"]


_oauth_flows: dict[str, PendingOAuth] = {}


@router.get("/api/integrations/binance/status")
def binance_status(
    _: object = Depends(current_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    settings = get_settings()
    if Repository(db).get_or_create_agent().mode == "AUTO_BOUNDED":
        return {
            "state": "READY"
            if settings.binance_api_key and settings.binance_api_secret
            else "NOT_CONFIGURED",
            "transport": "BINANCE_SPOT_API",
            "accountReference": None,
            "capabilities": [],
        }
    if settings.binance_agent_os_transport == "codex":
        return {"state": "AUTH_REQUIRED", "accountReference": None, "capabilities": []}
    return Repository(db).redact_connection(Repository(db).current_connection())


@router.get("/api/integrations/binance-api/status")
def binance_api_status(_: object = Depends(current_owner)) -> dict[str, object]:
    settings = get_settings()
    configured = bool(settings.binance_api_key and settings.binance_api_secret)
    return {
        "transport": "BINANCE_SPOT_API",
        "state": "READY" if configured else "NOT_CONFIGURED",
        "configured": configured,
        "liveVerification": "UNVERIFIED",
    }


@router.post("/api/integrations/binance/connect")
async def binance_connect(
    _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    from uuid import uuid7

    settings = get_settings()
    if settings.binance_agent_os_transport == "codex":
        return {
            "state": "AUTH_REQUIRED",
            "transport": "codex",
            "mcpEndpoint": settings.binance_agent_os_mcp_url,
            "authorizationRequired": True,
            "message": (
                "Codex App Server is the configured Binance transport. Complete the genuine "
                "Codex-managed OAuth flow later; custom DARWIN OAuth is not used by runtime."
            ),
        }
    if not settings.token_encryption_key:
        raise HTTPException(
            status_code=503, detail="TOKEN_ENCRYPTION_KEY is required for Agent OS auth"
        )
    encryption_key = settings.token_encryption_key
    connection = BinanceConnection(
        id=str(uuid7()),
        state="PENDING_AUTH",
        capabilities="[]",
        created_at=datetime.now(UTC),
    )
    db.add(connection)
    db.commit()
    callback_url = f"{settings.frontend_origin.rstrip('/')}/api/integrations/binance/callback"
    flow = PendingOAuth(
        connection_id=connection.id,
        redirect_ready=asyncio.Event(),
    )
    _oauth_flows[connection.id] = flow

    async def redirect_handler(url: str) -> None:
        flow.authorization_url = url
        values = parse_qs(urlsplit(url).query).get("state", [])
        flow.oauth_state = values[0] if values else None
        if flow.oauth_state is None:
            raise AgentOSUnavailable("Binance Agent OS authorization URL omitted state")
        with SessionLocal() as connection_db:
            stored = connection_db.get(BinanceConnection, connection.id)
            if stored is None:
                raise AgentOSUnavailable("connection disappeared during Agent OS auth")
            stored.oauth_state = flow.oauth_state
            stored.oauth_code = None
            stored.oauth_iss = None
            stored.oauth_error = None
            connection_db.commit()
        flow.redirect_ready.set()

    async def callback_handler() -> AuthorizationCodeResult:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 300
        while loop.time() < deadline:
            with SessionLocal() as connection_db:
                stored = connection_db.get(BinanceConnection, flow.connection_id)
                if stored is None:
                    raise AgentOSUnavailable("connection disappeared during Agent OS auth")
                if stored.oauth_error:
                    return AuthorizationCodeResult(
                        code="", state=flow.oauth_state, iss=stored.oauth_iss
                    )
                if stored.oauth_code:
                    return AuthorizationCodeResult(
                        code=decrypt_connection_material(stored.oauth_code, encryption_key),
                        state=flow.oauth_state,
                        iss=stored.oauth_iss,
                    )
            await asyncio.sleep(0.25)
        raise AgentOSUnavailable("Binance Agent OS authorization callback timed out")

    metadata = OAuthClientMetadata(
        client_name="DarwinSpot",
        redirect_uris=[TypeAdapter(AnyUrl).validate_python(callback_url)],
        token_endpoint_auth_method="none",
        application_type="web",
    )
    provider = OAuthClientProvider(
        settings.binance_agent_os_mcp_url,
        metadata,
        DatabaseOAuthStorage(connection.id, encryption_key),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        client_metadata_url=(
            f"{settings.frontend_origin.rstrip('/')}/.well-known/darwinspot-oauth-client.json"
        ),
    )
    client = BinanceAgentOSClient.with_provider(settings.binance_agent_os_mcp_url, provider)

    async def complete_connection() -> None:
        try:
            capabilities = ToolCatalog(await client.discover_tools()).permitted_names
            with SessionLocal() as connection_db:
                stored = connection_db.get(BinanceConnection, connection.id)
                if stored is None:
                    raise ValueError("connection disappeared during Agent OS auth")
                stored.state = "CONNECTED"
                stored.capabilities = json.dumps(list(capabilities), sort_keys=True)
                stored.refreshed_at = datetime.now(UTC)
                stored.oauth_state = None
                stored.oauth_code = None
                stored.oauth_iss = None
                stored.oauth_error = None
                Repository(connection_db).get_or_create_agent().state = "STOPPED"
                connection_db.commit()
        except Exception as exc:
            flow.error = str(exc)
            with SessionLocal() as connection_db:
                stored = connection_db.get(BinanceConnection, connection.id)
                if stored is not None and isinstance(exc, AgentOSAuthInvalid):
                    stored.state = "DISCONNECTED"
                    stored.disconnected_at = datetime.now(UTC)
                    connection_db.commit()
        finally:
            flow.redirect_ready.set()
            _oauth_flows.pop(flow.connection_id, None)

    task = asyncio.create_task(complete_connection())
    redirect_wait = asyncio.create_task(flow.redirect_ready.wait())
    done, _ = await asyncio.wait(
        (redirect_wait, task), timeout=5, return_when=asyncio.FIRST_COMPLETED
    )
    if not redirect_wait.done():
        redirect_wait.cancel()
    db.refresh(connection)
    if connection.state == "CONNECTED":
        return {
            "state": "CONNECTED",
            "mcpEndpoint": settings.binance_agent_os_mcp_url,
            "authorizationRequired": False,
            "capabilities": json.loads(connection.capabilities),
            "message": "Binance Agent OS capabilities discovered from the official MCP endpoint.",
        }
    if flow.authorization_url is not None:
        return {
            "state": "PENDING_AUTH",
            "mcpEndpoint": settings.binance_agent_os_mcp_url,
            "authorizationRequired": True,
            "authorizationUrl": flow.authorization_url,
            "message": (
                "Open the official Binance authorization page to continue Agent OS connection."
            ),
        }
    if flow.error is not None and task in done:
        return {
            "state": "PENDING_AUTH",
            "mcpEndpoint": settings.binance_agent_os_mcp_url,
            "authorizationRequired": True,
            "message": f"Agent OS authorization did not complete: {flow.error}",
        }
    return {
        "state": "PENDING_AUTH",
        "mcpEndpoint": settings.binance_agent_os_mcp_url,
        "authorizationRequired": True,
        "message": (
            "Agent OS authorization is pending; retry status after completing the official flow."
        ),
    }


@router.get("/api/integrations/codex/status")
async def codex_status(_: object = Depends(current_owner)) -> dict[str, object]:
    settings = get_settings()
    if settings.binance_agent_os_transport != "codex":
        return {
            "transport": settings.binance_agent_os_transport,
            "state": "LEGACY_DIRECT_OAUTH",
            "verification": "UNVERIFIED",
            "authenticated": False,
            "tools": [],
        }
    transport = CodexAppServerTransport(settings)
    try:
        status = await transport.status(detail="toolsAndAuthOnly")
        return {
            "transport": "codex",
            "state": status.auth_state,
            "verification": "UNVERIFIED",
            "authenticated": status.auth_state == "CONNECTED",
            "tools": sorted(status.tools),
            "runtimeStatus": status.runtime_status,
        }
    except (CodexAuthRequired, CodexTransportError) as exc:
        return {
            "transport": "codex",
            "state": "AUTH_REQUIRED" if isinstance(exc, CodexAuthRequired) else "UNAVAILABLE",
            "verification": "UNVERIFIED",
            "authenticated": False,
            "tools": [],
            "reason": str(exc),
        }
    finally:
        await transport.close()


@router.get("/api/integrations/binance/callback")
async def binance_callback(
    _: object = Depends(current_owner),
    db: Session = Depends(get_db),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    iss: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    if state is None:
        raise HTTPException(status_code=400, detail="Agent OS authorization state is required")
    connection = db.scalar(
        select(BinanceConnection).where(BinanceConnection.oauth_state == state).limit(1)
    )
    if connection is None:
        raise HTTPException(status_code=400, detail="Agent OS authorization state is invalid")
    if error is None and not code:
        raise HTTPException(status_code=400, detail="Agent OS authorization code is required")
    settings = get_settings()
    if not settings.token_encryption_key:
        raise HTTPException(
            status_code=503, detail="TOKEN_ENCRYPTION_KEY is required for Agent OS auth"
        )
    connection.oauth_code = (
        encrypt_connection_material(code, settings.token_encryption_key) if code else None
    )
    connection.oauth_iss = iss[:256] if iss else None
    connection.oauth_error = error[:512] if error else None
    db.commit()
    flow = _oauth_flows.get(connection.id)
    if flow is not None:
        flow.redirect_ready.set()
    if error:
        return RedirectResponse(
            url=f"{settings.frontend_origin.rstrip('/')}/settings?binance=error",
            status_code=303,
        )
    return RedirectResponse(
        url=f"{settings.frontend_origin.rstrip('/')}/settings?binance=returning",
        status_code=303,
    )


@router.post("/api/integrations/binance/disconnect")
def binance_disconnect(
    _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, str]:
    from datetime import UTC, datetime

    connection = Repository(db).current_connection()
    if connection is not None:
        connection.state = "DISCONNECTED"
        connection.disconnected_at = datetime.now(UTC)
        config = Repository(db).get_or_create_agent()
        config.state = "DISCONNECTED"
        config.next_run_at = None
        db.commit()
    return {"state": "DISCONNECTED"}


@router.get("/api/orders")
def orders(
    _: object = Depends(current_owner), db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    rows = db.scalars(select(TradeIntent).order_by(TradeIntent.created_at.desc()).limit(100)).all()
    return [
        {
            "id": row.id,
            "pair": row.pair,
            "side": row.side,
            "state": row.local_state,
            "binanceOrderId": row.binance_order_id,
            "clientOrderId": row.idempotency_key,
        }
        for row in rows
    ]


@router.get("/api/activity")
def activity(
    _: object = Depends(current_owner), db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    runs = db.scalars(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(100)).all()
    intents = db.scalars(
        select(TradeIntent).order_by(TradeIntent.created_at.desc()).limit(100)
    ).all()
    order_events = db.scalars(
        select(OrderEvent).order_by(OrderEvent.observed_at.desc()).limit(100)
    ).all()
    approvals = {
        approval.intent_id: approval for approval in db.scalars(select(TradeIntentApproval)).all()
    }
    deliveries = {
        row.aggregate_id: row
        for row in db.scalars(
            select(OutboxMessage).where(OutboxMessage.kind == "TELEGRAM_PROPOSAL")
        ).all()
    }
    events: list[dict[str, object]] = [_run_activity_event(run) for run in runs]
    events.extend(
        [
            {
                "id": intent.id,
                "type": "order",
                "state": intent.local_state,
                "timestamp": intent.created_at,
                "pair": intent.pair,
                "budgetResult": intent.budget_result,
                "binanceOrderId": intent.binance_order_id,
                "clientOrderId": intent.idempotency_key,
                "approvalState": approvals[intent.id].status if intent.id in approvals else None,
                "approvalExpiresAt": (
                    approvals[intent.id].expires_at if intent.id in approvals else None
                ),
                "notificationState": (
                    deliveries[intent.id].status if intent.id in deliveries else "NOT_CREATED"
                ),
                "executionMode": intent.execution_mode,
                "executionTransport": intent.execution_transport,
                "authorizationSource": intent.authorization_source,
                "authorizedAt": intent.authorized_at,
                "decision": intent.side,
                "confidence": str(intent.confidence),
                "systemOutcome": (
                    "EXECUTED"
                    if intent.local_state == "FILLED"
                    else "SKIPPED"
                    if intent.local_state == "FINANCIAL_WRITES_DISABLED"
                    else "FAILED"
                    if intent.local_state in {"REJECTED_EXCHANGE", "EXPIRED"}
                    else "PENDING"
                ),
                "reason": (
                    "FINANCIAL_WRITES_DISABLED"
                    if intent.local_state == "FINANCIAL_WRITES_DISABLED"
                    else intent.budget_result if intent.budget_result != "PASS" else None
                ),
            }
            for intent in intents
        ]
    )
    events.extend(
        {
            "id": event.id,
            "type": "order_event",
            "state": event.upstream_event_type,
            "timestamp": event.observed_at,
            "intentId": event.intent_id,
            "filledQuantity": event.filled_quantity,
            "filledNotional": event.filled_notional,
        }
        for event in order_events
    )
    events.sort(key=lambda event: str(event["timestamp"]), reverse=True)
    return events


@router.get("/api/activity/{activity_id}")
def activity_detail(
    activity_id: str, _: object = Depends(current_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    run = db.get(AgentRun, activity_id)
    if run is not None:
        return {
            "id": run.id,
            "type": "audit"
            if run.trigger_type in {"BUDGET_INCREASED", "EMERGENCY_STOP_CLEARED"}
            else "decision",
            "trigger": run.trigger_type,
            "decision": json.loads(run.decision) if run.decision else None,
            "rationale": run.rationale,
            "evidence": run.evidence_timestamps,
            "mandateVersion": run.mandate_version,
            "budgetVersion": run.budget_version,
            "startedAt": run.started_at,
            "completedAt": run.completed_at,
        }
    intent = db.get(TradeIntent, activity_id)
    if intent is not None:
        approval = db.scalar(
            select(TradeIntentApproval).where(TradeIntentApproval.intent_id == intent.id).limit(1)
        )
        delivery = db.scalar(
            select(OutboxMessage)
            .where(
                OutboxMessage.aggregate_id == intent.id,
                OutboxMessage.kind == "TELEGRAM_PROPOSAL",
            )
            .limit(1)
        )
        run = db.get(AgentRun, intent.agent_run_id)
        order_events = db.scalars(
            select(OrderEvent)
            .where(OrderEvent.intent_id == intent.id)
            .order_by(OrderEvent.observed_at.asc())
        ).all()
        return {
            "id": intent.id,
            "type": "order",
            "pair": intent.pair,
            "side": intent.side,
            "orderType": intent.order_type,
            "quantity": str(intent.quantity),
            "quoteNotional": (
                str(intent.quote_notional) if intent.quote_notional is not None else None
            ),
            "price": str(intent.price) if intent.price is not None else None,
            "state": intent.local_state,
            "budgetResult": intent.budget_result,
            "committedNotional": (
                str(intent.committed_notional) if intent.committed_notional is not None else None
            ),
            "binanceOrderId": intent.binance_order_id,
            "clientOrderId": intent.idempotency_key,
            "intentId": intent.id,
            "budgetVersion": run.budget_version if run else None,
            "idempotencyKey": intent.idempotency_key,
            "approval": (
                {
                    "id": approval.approval_id,
                    "state": approval.status,
                    "expiresAt": approval.expires_at,
                    "decidedAt": approval.decided_at,
                    "decisionSource": approval.decision_source,
                }
                if approval is not None
                else None
            ),
            "notificationState": delivery.status if delivery is not None else "NOT_CREATED",
            "executionMode": intent.execution_mode,
            "executionTransport": intent.execution_transport,
            "authorizationSource": intent.authorization_source,
            "authorizedAt": intent.authorized_at,
            "confirmationRequestId": intent.confirmation_request_id,
            "confirmationExpiresAt": intent.confirmation_expires_at,
            "rationale": intent.rationale,
            "supportingFactors": json.loads(intent.supporting_factors),
            "riskFactors": json.loads(intent.risk_factors),
            "confidence": str(intent.confidence),
            "revalidationEvidence": intent.revalidation_evidence,
            "revalidationFailedReason": intent.revalidation_failed_reason,
            "events": [
                {
                    "id": event.id,
                    "type": event.upstream_event_type,
                    "filledQuantity": (
                        str(event.filled_quantity) if event.filled_quantity is not None else None
                    ),
                    "filledNotional": (
                        str(event.filled_notional) if event.filled_notional is not None else None
                    ),
                    "observedAt": event.observed_at,
                    "exchangeTimestamp": event.exchange_timestamp,
                    "evidence": json.loads(event.sanitized_evidence),
                }
                for event in order_events
            ],
        }
    raise HTTPException(status_code=404, detail="activity not found")


@router.get("/api/runs/{run_id}")
def run_detail(
    run_id: str, _: object = Depends(current_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "id": run.id,
        "state": run.result_state,
        "decision": json.loads(run.decision) if run.decision else None,
        "evidence": run.evidence_timestamps,
        "mandateVersion": run.mandate_version,
        "budgetVersion": run.budget_version,
        "startedAt": run.started_at,
        "completedAt": run.completed_at,
    }


@router.post("/api/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    _: object = Depends(mutation_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    raise HTTPException(
        status_code=410,
        detail="direct cancellation is disabled; use the explicit emergency stop control",
    )


@router.post("/api/orders/{order_id}/approve")
async def approve_order(
    order_id: str,
    _: object = Depends(mutation_owner),
    db: Session = Depends(get_db),
) -> dict[str, str | None]:
    repo = Repository(db)
    intent = repo.find_intent_by_order_id(order_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="order not found")
    approval = db.scalar(
        select(TradeIntentApproval).where(TradeIntentApproval.intent_id == intent.id).limit(1)
    )
    if approval is None:
        raise HTTPException(status_code=409, detail="order has no approval record")
    try:
        result = TradeIntentApprovalService(
            db, default_ttl_seconds=get_settings().approval_ttl_seconds
        ).decide(
            approval.approval_id,
            "APPROVE",
            operator_user_id="WEB_OWNER",
            operator_chat_id="WEB_OWNER",
            source="WEB",
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "id": result.intent_id,
        "state": result.intent_state,
        "approvalState": result.approval_status,
        "binanceOrderId": intent.binance_order_id,
    }


@router.post("/api/orders/{order_id}/confirmation")
async def resolve_confirmation(
    order_id: str,
    request: ConfirmationInput,
    _: object = Depends(mutation_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    intent = db.get(TradeIntent, order_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="order not found")
    if (
        intent.execution_mode != "HUMAN_APPROVAL"
        or intent.local_state != "WAITING_FOR_EXECUTION_CONFIRMATION"
        or not intent.confirmation_request_id
    ):
        raise HTTPException(status_code=409, detail="order is not awaiting transport confirmation")
    from darwinspot.notifications.outbox import CONFIRMATION_KIND, enqueue_unique

    enqueue_unique(
        db,
        kind=CONFIRMATION_KIND,
        aggregate_id=intent.id,
        payload={"intent_id": intent.id, "action": request.action},
        dedupe_key=f"resolve-confirmation:{intent.id}:{request.action}",
    )
    db.commit()
    return {"state": "CONFIRMATION_RESOLUTION_QUEUED"}


@router.post("/api/orders/{order_id}/reject")
def reject_order(
    order_id: str,
    _: object = Depends(mutation_owner),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    repo = Repository(db)
    intent = repo.find_intent_by_order_id(order_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="order not found")
    approval = db.scalar(
        select(TradeIntentApproval).where(TradeIntentApproval.intent_id == intent.id).limit(1)
    )
    if approval is None:
        raise HTTPException(status_code=409, detail="order has no approval record")
    try:
        result = TradeIntentApprovalService(
            db, default_ttl_seconds=get_settings().approval_ttl_seconds
        ).decide(
            approval.approval_id,
            "REJECT",
            operator_user_id="WEB_OWNER",
            operator_chat_id="WEB_OWNER",
            source="WEB",
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": result.intent_id, "state": result.intent_state}


@router.get("/api/integrations/telegram/status")
def telegram_status(_: object = Depends(current_owner)) -> dict[str, object]:
    settings = get_settings()
    return {
        "configured": all(
            (
                settings.telegram_bot_token,
                settings.telegram_operator_chat_id is not None,
                settings.telegram_operator_user_id is not None,
                settings.telegram_webhook_secret,
            )
        ),
        "approvalTtlSeconds": settings.approval_ttl_seconds,
    }


@router.post("/api/integrations/telegram/webhook")
async def telegram_webhook(
    request: Request,
    db: Session = Depends(get_db),
    secret_token: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict[str, object]:
    settings = get_settings()
    if not settings.telegram_webhook_secret or secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Telegram webhook authentication failed")
    try:
        raw_update = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Telegram update must be JSON") from exc
    update = cast(dict[str, Any], raw_update) if isinstance(raw_update, dict) else {}
    callback = update.get("callback_query")
    if not isinstance(callback, dict):
        return {"status": "ignored"}
    callback = cast(dict[str, Any], callback)
    sender_value = callback.get("from")
    message_value = callback.get("message")
    data = callback.get("data")
    sender = cast(dict[str, Any], sender_value) if isinstance(sender_value, dict) else {}
    message = cast(dict[str, Any], message_value) if isinstance(message_value, dict) else {}
    chat_value = message.get("chat")
    chat = cast(dict[str, Any], chat_value) if isinstance(chat_value, dict) else {}
    user_id = sender.get("id")
    chat_id = chat.get("id")
    if (
        user_id != settings.telegram_operator_user_id
        or chat_id != settings.telegram_operator_chat_id
        or not isinstance(data, str)
    ):
        raise HTTPException(status_code=403, detail="Telegram operator is not authorized")
    import re

    match = re.fullmatch(r"(approve|reject):([0-9a-fA-F-]{36})", data)
    if match is None:
        raise HTTPException(status_code=400, detail="Telegram callback reference is invalid")
    try:
        result = TradeIntentApprovalService(
            db, default_ttl_seconds=settings.approval_ttl_seconds
        ).decide(
            match.group(2),
            "APPROVE" if match.group(1) == "approve" else "REJECT",
            operator_user_id=str(user_id),
            operator_chat_id=str(chat_id),
            source="TELEGRAM",
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        await TelegramNotifier(settings).answer_callback(
            str(callback.get("id", "")),
            "Recorded" if not result.changed else result.approval_status,
        )
    except (TelegramDeliveryError, TelegramNotConfigured) as exc:
        log_event("TELEGRAM_CALLBACK_ACK_FAILED", approval_id=result.approval_id)
        raise HTTPException(status_code=503, detail="Telegram acknowledgement failed") from exc
    log_event(
        "TELEGRAM_APPROVAL_RECORDED",
        approval_id=result.approval_id,
        decision=match.group(1).upper(),
        changed=result.changed,
    )
    return {
        "status": "recorded",
        "approvalId": result.approval_id,
        "approvalState": result.approval_status,
        "intentState": result.intent_state,
    }
