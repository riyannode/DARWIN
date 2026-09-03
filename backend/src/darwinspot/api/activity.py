from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from darwinspot.agent.cycle import submit_intent
from darwinspot.api.auth import current_owner, mutation_owner
from darwinspot.binance.client import (
    AgentOSAuthInvalid,
    AgentOSUnavailable,
    BinanceAgentOSClient,
    DatabaseOAuthStorage,
    ToolCatalog,
)
from darwinspot.binance.mapper import (
    BinanceMappingError,
    map_order_submission,
    validate_order_submission_correlation,
)
from darwinspot.config import get_settings
from darwinspot.execution.budget import BudgetExceeded
from darwinspot.observability import log_event
from darwinspot.security.encryption import (
    decrypt_connection_material,
    encrypt_connection_material,
)
from darwinspot.storage.database import SessionLocal, get_db
from darwinspot.storage.models import AgentRun, BinanceConnection, OrderEvent, TradeIntent
from darwinspot.storage.repository import Repository

router = APIRouter(tags=["activity"])


@dataclass
class PendingOAuth:
    connection_id: str
    redirect_ready: asyncio.Event
    authorization_url: str | None = None
    oauth_state: str | None = None
    error: str | None = None


_oauth_flows: dict[str, PendingOAuth] = {}


@router.get("/api/integrations/binance/status")
def binance_status(
    _: object = Depends(current_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    return Repository(db).redact_connection(Repository(db).current_connection())


@router.post("/api/integrations/binance/connect")
async def binance_connect(
    _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    from uuid import uuid7

    settings = get_settings()
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
    events: list[dict[str, object]] = [
        {
            "id": run.id,
            "type": "audit"
            if run.trigger_type in {"BUDGET_INCREASED", "EMERGENCY_STOP_CLEARED"}
            else "decision",
            "state": run.result_state,
            "timestamp": run.started_at,
            "trigger": run.trigger_type,
            "rationale": run.rationale,
        }
        for run in runs
    ]
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
            "quantity": intent.quantity,
            "quoteNotional": intent.quote_notional,
            "price": intent.price,
            "state": intent.local_state,
            "budgetResult": intent.budget_result,
            "committedNotional": intent.committed_notional,
            "binanceOrderId": intent.binance_order_id,
            "clientOrderId": intent.idempotency_key,
            "intentId": intent.id,
            "budgetVersion": run.budget_version if run else None,
            "idempotencyKey": intent.idempotency_key,
            "events": [
                {
                    "id": event.id,
                    "type": event.upstream_event_type,
                    "filledQuantity": event.filled_quantity,
                    "filledNotional": event.filled_notional,
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
    intent = Repository(db).find_intent_by_order_id(order_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="order not found")
    if intent.binance_order_id is None:
        raise HTTPException(status_code=409, detail="order has not been accepted by Binance")
    connection = Repository(db).current_connection()
    if connection is None or connection.state != "CONNECTED":
        raise HTTPException(status_code=503, detail="Binance Agent OS is not connected")
    intent.local_state = "CANCEL_PENDING"
    db.commit()
    try:
        settings = get_settings()
        if not settings.token_encryption_key:
            raise AgentOSUnavailable("TOKEN_ENCRYPTION_KEY is required for Agent OS auth")
        client = BinanceAgentOSClient.with_oauth(
            settings.binance_agent_os_mcp_url,
            connection.id,
            settings.token_encryption_key,
            f"{settings.frontend_origin.rstrip('/')}/api/integrations/binance/callback",
            f"{settings.frontend_origin.rstrip('/')}/.well-known/darwinspot-oauth-client.json",
        )
        catalog = ToolCatalog(await client.discover_tools())
        log_event("ORDER_CANCEL_REQUESTED", intent_id=intent.id, order_id=intent.binance_order_id)
        raw = await client.call_tool(
            catalog.arguments(
                "cancel_order",
                {
                    "symbol": intent.pair,
                    "order_id": intent.binance_order_id,
                    "client_order_id": intent.idempotency_key,
                },
            )
        )
        response = map_order_submission(raw)
        validate_order_submission_correlation(
            raw,
            submission=response,
            expected_symbol=intent.pair,
            expected_client_order_id=intent.idempotency_key,
            expected_side=intent.side,
        )
    except (AgentOSUnavailable, BinanceMappingError, ValueError) as exc:
        if isinstance(exc, AgentOSAuthInvalid):
            Repository(db).mark_connection_unavailable(connection.id)
        intent.local_state = "CANCEL_PENDING"
        db.commit()
        log_event("RECONCILIATION_FAILED", intent_id=intent.id, reason=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if response.status not in {"CANCELED", "FILLED", "EXPIRED"}:
        intent.local_state = "CANCEL_PENDING"
        db.commit()
        raise HTTPException(status_code=503, detail="cancel result requires reconciliation")
    repo = Repository(db)
    repo.apply_order_status(
        intent,
        order_id=response.order_id,
        status=response.status,
        filled_quantity=response.executed_quantity,
        filled_notional=response.quote_notional,
        exchange_timestamp=response.updated_at,
        evidence=response.model_dump(mode="json"),
    )
    db.commit()
    return {"id": intent.id, "state": intent.local_state}


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
    if intent.local_state != "PROPOSED":
        raise HTTPException(status_code=409, detail="only a proposed order can be approved")
    config = repo.get_or_create_agent()
    if config.emergency_stop:
        raise HTTPException(status_code=409, detail="emergency stop is active")
    connection = repo.current_connection()
    if connection is None or connection.state != "CONNECTED":
        raise HTTPException(status_code=503, detail="Binance Agent OS is not connected")
    try:
        repo.reserve_intent(intent)
        settings = get_settings()
        if not settings.token_encryption_key:
            raise AgentOSUnavailable("TOKEN_ENCRYPTION_KEY is required for Agent OS auth")
        client = BinanceAgentOSClient.with_oauth(
            settings.binance_agent_os_mcp_url,
            connection.id,
            settings.token_encryption_key,
            f"{settings.frontend_origin.rstrip('/')}/api/integrations/binance/callback",
            f"{settings.frontend_origin.rstrip('/')}/.well-known/darwinspot-oauth-client.json",
        )
        catalog = ToolCatalog(await client.discover_tools())
        state = await submit_intent(repo, client, catalog, intent)
    except BudgetExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (AgentOSUnavailable, BinanceMappingError, ValueError) as exc:
        if isinstance(exc, AgentOSAuthInvalid):
            repo.mark_connection_unavailable(connection.id)
            db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"id": intent.id, "state": state, "binanceOrderId": intent.binance_order_id}
