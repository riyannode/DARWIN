from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from darwinspot.agent.cycle import CycleUnavailable, reconcile_open_intents, run_cycle
from darwinspot.agent.runtime import AgentRuntime
from darwinspot.api.auth import (
    current_owner,
    mutation_owner,
    require_recent_reauthentication,
)
from darwinspot.binance.client import (
    AgentOSAuthInvalid,
    AgentOSUnavailable,
    BinanceAgentOSClient,
    ToolCatalog,
    UnsupportedCapability,
)
from darwinspot.binance.mapper import (
    BinanceMappingError,
    map_order_submission,
    validate_order_submission_correlation,
)
from darwinspot.config import get_settings
from darwinspot.domain import AgentState
from darwinspot.observability import log_event
from darwinspot.storage.database import get_db
from darwinspot.storage.models import OwnerSession
from darwinspot.storage.repository import Repository

router = APIRouter(prefix="/api/agent", tags=["agent"])
Mode = Literal["READ_ONLY", "APPROVAL_REQUIRED", "AUTO_BOUNDED"]


class ModeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode


class MandateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: str = Field(min_length=1, max_length=2000)
    entry_rules: str = Field(min_length=1, max_length=4000)
    sizing_rules: str = Field(min_length=1, max_length=2000)
    exit_rules: str = Field(min_length=1, max_length=4000)


def _agent_payload(repo: Repository) -> dict[str, object]:
    config = repo.get_or_create_agent()
    mandate = repo.current_mandate()
    latest = repo.latest_run()
    return {
        "mode": config.mode,
        "state": config.state,
        "nextRunAt": config.next_run_at,
        "emergencyStop": config.emergency_stop,
        "latestDecision": None
        if latest is None
        else {
            "id": latest.id,
            "state": latest.result_state,
            "decision": json.loads(latest.decision) if latest.decision else None,
            "rationale": latest.rationale,
            "startedAt": latest.started_at,
            "completedAt": latest.completed_at,
            "mandateVersion": latest.mandate_version,
            "budgetVersion": latest.budget_version,
        },
        "mandate": None
        if mandate is None
        else {
            "version": mandate.id,
            "assets": mandate.assets,
            "entryRules": mandate.entry_rules,
            "sizingRules": mandate.sizing_rules,
            "exitRules": mandate.exit_rules,
            "createdAt": mandate.created_at,
        },
    }


@router.get("")
def get_agent(
    _: object = Depends(current_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    return _agent_payload(Repository(db))


@router.put("/mandate")
def put_mandate(
    request: MandateInput, _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    repo = Repository(db)
    mandate = repo.save_mandate(request.model_dump())
    return {"version": mandate.id, "createdAt": mandate.created_at}


@router.put("/mode")
def put_mode(
    request: ModeInput, _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, str]:
    repo = Repository(db)
    config = repo.get_or_create_agent()
    if request.mode == "AUTO_BOUNDED" and repo.current_mandate() is None:
        raise HTTPException(
            status_code=409, detail="complete all four mandate sections before activation"
        )
    if request.mode == "AUTO_BOUNDED" and repo.current_budget() is None:
        raise HTTPException(
            status_code=409, detail="set the rolling 24-hour budget before activation"
        )
    if request.mode == "AUTO_BOUNDED":
        connection = repo.current_connection()
        if connection is None or connection.state != "CONNECTED":
            raise HTTPException(
                status_code=409, detail="connect Binance Agent OS before activation"
            )
        try:
            ToolCatalog(json.loads(connection.capabilities)).resolve("submit_order")
        except (UnsupportedCapability, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=409, detail="connected Agent OS session has no spot trading capability"
            ) from exc
    config.mode = request.mode
    db.commit()
    return {"mode": config.mode}


@router.post("/start")
def start_agent(
    _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, str]:
    repo = Repository(db)
    config = repo.get_or_create_agent()
    connection = repo.current_connection()
    if connection is None or connection.state != "CONNECTED":
        raise HTTPException(status_code=409, detail="connect Binance Agent OS before starting")
    if config.emergency_stop:
        raise HTTPException(status_code=409, detail="emergency stop is active")
    if not get_settings().openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is required to start the agent")
    if config.mode == "AUTO_BOUNDED":
        connection = repo.current_connection()
        if connection is None:
            raise HTTPException(status_code=409, detail="connect Binance Agent OS before starting")
        try:
            ToolCatalog(json.loads(connection.capabilities)).resolve("submit_order")
        except (UnsupportedCapability, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=409, detail="connected Agent OS session has no spot trading capability"
            ) from exc
    config.state = AgentState.RUNNING
    config.next_run_at = datetime.now(UTC) + timedelta(seconds=get_settings().agent_cycle_seconds)
    db.commit()
    return {"state": config.state}


@router.post("/stop")
def stop_agent(
    _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, str]:
    config = Repository(db).get_or_create_agent()
    config.state = AgentState.STOPPED
    config.next_run_at = None
    db.commit()
    return {"state": config.state}


@router.post("/run-once")
async def run_once(
    _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, str]:
    repo = Repository(db)
    connection = repo.current_connection()
    settings = get_settings()
    if connection is None or connection.state != "CONNECTED":
        raise HTTPException(status_code=409, detail="Binance Agent OS is not connected")
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is required for a real run")
    if not settings.token_encryption_key:
        raise HTTPException(
            status_code=503, detail="TOKEN_ENCRYPTION_KEY is required for Agent OS auth"
        )
    run = repo.start_run("RUN_ONCE", settings.openai_model)
    try:
        result = await asyncio.wait_for(
            run_cycle(
                repo,
                BinanceAgentOSClient.with_oauth(
                    settings.binance_agent_os_mcp_url,
                    connection.id,
                    settings.token_encryption_key,
                    f"{settings.frontend_origin.rstrip('/')}/api/integrations/binance/callback",
                    f"{settings.frontend_origin.rstrip('/')}/.well-known/darwinspot-oauth-client.json",
                ),
                AgentRuntime(settings.openai_api_key, settings.openai_model),
                run.id,
            ),
            timeout=60,
        )
    except (AgentOSUnavailable, CycleUnavailable, TimeoutError, ValueError) as exc:
        if isinstance(exc, AgentOSAuthInvalid):
            repo.mark_connection_unavailable(connection.id)
        repo.complete_run(run.id, "FAILED", None, str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    repo.complete_run(run.id, result, None, None)
    return {"runId": run.id, "state": result}


@router.post("/emergency-stop")
async def emergency_stop(
    _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    config = Repository(db).get_or_create_agent()
    config.emergency_stop = True
    config.state = AgentState.EMERGENCY_STOP
    config.next_run_at = None
    db.commit()
    log_event("EMERGENCY_STOP_ENABLED")
    repo = Repository(db)
    outcomes: list[dict[str, str]] = []
    connection = repo.current_connection()
    if connection is None or connection.state != "CONNECTED":
        return {"state": config.state, "cancellationState": "UNAVAILABLE"}
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
        await reconcile_open_intents(repo, client)
        catalog = ToolCatalog(await client.discover_tools())
        for intent in repo.non_terminal_intents():
            if intent.local_state not in {
                "OPEN",
                "PARTIALLY_FILLED",
                "SUBMITTING",
                "SUBMISSION_UNKNOWN",
                "CANCEL_PENDING",
            }:
                continue
            if not intent.binance_order_id:
                outcomes.append(
                    {
                        "id": intent.id,
                        "state": "CANCEL_UNAVAILABLE",
                        "reason": "Binance order identifier is not known after reconciliation",
                    }
                )
                continue
            intent.local_state = "CANCEL_PENDING"
            db.commit()
            log_event(
                "ORDER_CANCEL_REQUESTED", intent_id=intent.id, order_id=intent.binance_order_id
            )
            try:
                response = map_order_submission(
                    raw := await client.call_tool(
                        catalog.arguments(
                            "cancel_order",
                            {
                                "symbol": intent.pair,
                                "order_id": intent.binance_order_id,
                                "client_order_id": intent.idempotency_key,
                            },
                        ),
                    )
                )
                validate_order_submission_correlation(
                    raw,
                    submission=response,
                    expected_symbol=intent.pair,
                    expected_client_order_id=intent.idempotency_key,
                    expected_side=intent.side,
                )
                repo.apply_order_status(
                    intent,
                    order_id=response.order_id,
                    status=response.status,
                    filled_quantity=response.executed_quantity,
                    filled_notional=response.quote_notional,
                    exchange_timestamp=response.updated_at,
                    evidence=response.model_dump(mode="json"),
                )
                outcomes.append({"id": intent.id, "state": intent.local_state})
            except (AgentOSUnavailable, BinanceMappingError, ValueError) as exc:
                outcomes.append({"id": intent.id, "state": "CANCEL_FAILED", "reason": str(exc)})
        db.commit()
    except (AgentOSUnavailable, BinanceMappingError, ValueError) as exc:
        db.rollback()
        if isinstance(exc, AgentOSAuthInvalid):
            repo.mark_connection_unavailable(connection.id)
        log_event("RECONCILIATION_FAILED", reason=str(exc))
        config = repo.get_or_create_agent()
        config.emergency_stop = True
        config.state = AgentState.EMERGENCY_STOP
        db.commit()
        return {"state": config.state, "cancellationState": "FAILED", "reason": str(exc)}
    cancellation_state = (
        "RECONCILED"
        if all(item["state"] in {"CANCELED", "FILLED", "EXPIRED"} for item in outcomes)
        else "PARTIAL"
    )
    return {"state": config.state, "cancellationState": cancellation_state, "outcomes": outcomes}


@router.post("/reactivate")
def reactivate(
    owner: OwnerSession = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, str]:
    require_recent_reauthentication(owner)
    repo = Repository(db)
    config = repo.get_or_create_agent()
    config.emergency_stop = False
    config.state = AgentState.STOPPED
    config.next_run_at = None
    db.commit()
    snapshot = repo.budget_snapshot()
    repo.record_audit_event(
        trigger="EMERGENCY_STOP_CLEARED",
        state="EMERGENCY_STOP_CLEARED",
        model=get_settings().openai_model,
        evidence={
            "availableBudget": str(snapshot.available_budget) if snapshot else None,
            "spentAmount": str(snapshot.spent_amount) if snapshot else None,
        },
    )
    return {"state": config.state}
