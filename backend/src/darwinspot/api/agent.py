from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from darwinspot.agent.cycle import CycleUnavailable, run_cycle
from darwinspot.agent.mandate import MandateInput
from darwinspot.agent.runtime import AgentRuntime
from darwinspot.api.auth import (
    current_owner,
    mutation_owner,
    require_recent_reauthentication,
)
from darwinspot.binance.client import (
    AgentOSAuthInvalid,
    AgentOSUnavailable,
    ToolCatalog,
)
from darwinspot.binance.codex_transport import CodexTransportError
from darwinspot.binance.factory import build_binance_client
from darwinspot.binance.mapper import map_spot_market_universe, map_symbol_filters
from darwinspot.config import get_settings
from darwinspot.domain import AgentState
from darwinspot.execution.modes import ExecutionMode
from darwinspot.execution.universe import validate_supported_symbols
from darwinspot.observability import log_event
from darwinspot.storage.database import get_db
from darwinspot.storage.models import OwnerSession
from darwinspot.storage.repository import Repository

router = APIRouter(prefix="/api/agent", tags=["agent"])
Mode = Literal["HUMAN_APPROVAL", "AUTO_BOUNDED"]


class ModeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode


class UniverseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported_symbols: list[str] = Field(min_length=1, max_length=100)

    @field_validator("supported_symbols")
    @classmethod
    def validate_symbols(cls, values: list[str]) -> list[str]:
        return list(validate_supported_symbols(values))


def _agent_payload(repo: Repository) -> dict[str, object]:
    config = repo.get_or_create_agent()
    mandate = repo.current_mandate()
    latest = repo.latest_run()
    return {
        "mode": config.mode,
        "supportedSymbols": list(repo.supported_symbols()),
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
            "allowedSymbols": json.loads(mandate.allowed_symbols),
            "maxOrderNotional": str(mandate.max_order_notional),
            "maxOpenActionableIntents": mandate.max_open_actionable_intents,
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
    try:
        mandate = repo.save_mandate(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"version": mandate.id, "createdAt": mandate.created_at}


@router.put("/universe")
async def put_universe(
    request: UniverseInput, _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    repo = Repository(db)
    config = repo.get_or_create_agent()
    settings = get_settings()
    connection = repo.current_connection()
    existing_symbols = set(repo.supported_symbols())
    additions = [symbol for symbol in request.supported_symbols if symbol not in existing_symbols]
    client = None
    try:
        if additions:
            try:
                client = build_binance_client(settings, connection, mode=config.mode)
            except AgentOSUnavailable as exc:
                raise HTTPException(
                    status_code=503, detail="selected Binance transport is unavailable"
                ) from exc
            catalog = ToolCatalog(await client.discover_tools())
            market_universe = map_spot_market_universe(
                await client.call_tool(catalog.arguments("market_universe", {}))
            )
            live = {str(item["symbol"]): item for item in market_universe}
            for symbol in additions:
                if live.get(symbol) is None:
                    raise HTTPException(
                        status_code=422,
                        detail=f"{symbol} is not a currently trading Binance Spot/USDT symbol",
                    )
                filters = map_symbol_filters(
                    await client.call_tool(
                        catalog.arguments("symbol_filters", {"symbol": symbol})
                    )
                )
                if filters.symbol != symbol or filters.quote_asset != "USDT":
                    raise HTTPException(
                        status_code=422,
                        detail=f"{symbol} does not expose valid Binance Spot/USDT filters",
                    )
        saved = repo.save_supported_symbols(request.supported_symbols)
    except (AgentOSUnavailable, CodexTransportError) as exc:
        raise HTTPException(
            status_code=503, detail="selected Binance transport is unavailable"
        ) from exc
    finally:
        transport = getattr(client, "transport", None)
        if transport is not None:
            await transport.close()
    repo.record_audit_event(
        trigger="SUPPORTED_SYMBOLS_CHANGED",
        state="SUPPORTED_SYMBOLS_CHANGED",
        model=settings.openai_model,
        evidence={"supportedSymbols": list(saved)},
    )
    return {"supportedSymbols": list(saved)}


@router.put("/mode")
def put_mode(
    request: ModeInput, _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, str]:
    repo = Repository(db)
    config = repo.get_or_create_agent()
    if request.mode == ExecutionMode.AUTO_BOUNDED and repo.current_mandate() is None:
        raise HTTPException(
            status_code=409, detail="complete all four mandate sections before activation"
        )
    if request.mode == ExecutionMode.AUTO_BOUNDED and repo.current_budget() is None:
        raise HTTPException(
            status_code=409, detail="set the rolling 24-hour budget before activation"
        )
    previous_mode = config.mode
    config.mode = request.mode
    db.commit()
    repo.record_audit_event(
        trigger="EXECUTION_MODE_CHANGED",
        state=request.mode,
        model=get_settings().openai_model,
        evidence={"previousMode": previous_mode, "mode": request.mode},
    )
    return {"mode": config.mode}


@router.post("/start")
def start_agent(
    _: object = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, str]:
    repo = Repository(db)
    config = repo.get_or_create_agent()
    if config.emergency_stop:
        raise HTTPException(status_code=409, detail="emergency stop is active")
    if not get_settings().openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is required to start the agent")
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
    settings = get_settings()
    config = repo.get_or_create_agent()
    connection = repo.current_connection()
    if (
        config.mode == ExecutionMode.HUMAN_APPROVAL
        and settings.binance_agent_os_transport == "direct_oauth"
        and (
        connection is None or connection.state != "CONNECTED"
        )
    ):
        raise HTTPException(status_code=409, detail="Binance Agent OS is not connected")
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is required for a real run")
    run = repo.start_run("RUN_ONCE", settings.openai_model)
    client = None
    try:
        client = build_binance_client(settings, connection, mode=config.mode)
        result = await asyncio.wait_for(
            run_cycle(
                repo,
                client,
                AgentRuntime(
                    settings.openai_api_key, settings.openai_model, settings.openai_base_url
                ),
                run.id,
            ),
            timeout=60,
        )
    except (
        AgentOSUnavailable,
        CodexTransportError,
        CycleUnavailable,
        TimeoutError,
        ValueError,
    ) as exc:
        if isinstance(exc, AgentOSAuthInvalid) and connection is not None:
            repo.mark_connection_unavailable(connection.id)
        repo.complete_run(run.id, "FAILED", None, str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        transport = getattr(client, "transport", None)
        if transport is not None:
            await transport.close()
    repo.complete_run(run.id, result, None, None)
    return {"runId": run.id, "state": result}


@router.post("/emergency-stop")
async def emergency_stop(
    owner: OwnerSession = Depends(mutation_owner), db: Session = Depends(get_db)
) -> dict[str, object]:
    require_recent_reauthentication(owner)
    repo = Repository(db)
    config = repo.get_or_create_agent()
    config.emergency_stop = True
    config.state = AgentState.EMERGENCY_STOP
    config.next_run_at = None
    targets: list[dict[str, str]] = []
    from darwinspot.notifications.outbox import EMERGENCY_CANCEL_KIND, enqueue_unique

    for intent in repo.non_terminal_intents():
        if intent.local_state not in {
            "OPEN",
            "PARTIALLY_FILLED",
            "SUBMITTING",
            "SUBMISSION_UNKNOWN",
            "CANCEL_PENDING",
        }:
            continue
        enqueue_unique(
            db,
            kind=EMERGENCY_CANCEL_KIND,
            aggregate_id=intent.id,
            payload={"intent_id": intent.id, "operator_action_id": owner.id},
            dedupe_key=f"emergency-cancel:{config.id}:{intent.id}",
        )
        targets.append({"id": intent.id, "state": "CANCEL_QUEUED"})
    db.commit()
    log_event(
        "EMERGENCY_STOP_ENABLED",
        operator_action_id=owner.id,
        target_count=len(targets),
        target_ids=[item["id"] for item in targets],
    )
    if not targets:
        return {"state": config.state, "cancellationState": "RECONCILED", "outcomes": []}
    return {"state": config.state, "cancellationState": "QUEUED", "outcomes": targets}


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
