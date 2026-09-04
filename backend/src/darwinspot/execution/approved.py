from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.orm import Session

from darwinspot.agent.schemas import AgentDecision
from darwinspot.approval.service import TradeIntentApprovalService
from darwinspot.binance.client import (
    AgentOSAuthInvalid,
    AgentOSUnavailable,
    ToolCatalog,
    UnsupportedCapability,
)
from darwinspot.binance.codex_transport import (
    CodexAuthRequired,
    CodexConfirmationRequired,
    remember_pending_confirmation,
)
from darwinspot.binance.mapper import (
    BinanceMappingError,
    map_balances,
    map_mcp_result,
    map_open_orders,
    map_order_submission,
    map_recent_activity,
    map_spot_market_universe,
    map_symbol_filters,
    validate_order_submission_correlation,
)
from darwinspot.config import get_settings
from darwinspot.execution.orders import SubmissionBlocked
from darwinspot.execution.policy import PolicyEvaluation, evaluate_execution_policy
from darwinspot.execution.universe import effective_symbols
from darwinspot.observability import log_event
from darwinspot.storage.models import TradeIntent, TradeIntentApproval
from darwinspot.storage.repository import Repository


class ExecutionUnavailable(RuntimeError):
    pass


class RevalidationRejected(ExecutionUnavailable):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    state: str
    reason: str | None = None


@dataclass(frozen=True)
class ConfirmationRequest:
    request_id: str
    expires_at: datetime | None


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@contextmanager
def account_execution_lock(db: Session, account_key: str) -> Generator[None]:
    bind: Any = db.get_bind()
    if bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(
            hashlib.sha256(account_key.encode()).digest()[:8], "big", signed=True
        )
        connection = bind.connect()
        try:
            connection.execute(text("SELECT pg_advisory_lock(:lock_key)"), {"lock_key": lock_key})
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key})
            connection.close()
        return
    with _locks_guard:
        lock = _locks.setdefault(account_key, threading.Lock())
    with lock:
        yield


class ApprovedExecution:
    """The only ordinary Binance write seam after operator approval."""

    def __init__(self, repo: Repository, client: Any) -> None:
        self.repo = repo
        self.client = client
        self.settings = get_settings()

    async def execute_claimed(
        self, *, approval_id: str | None = None, intent_id: str | None = None
    ) -> ExecutionResult:
        service = TradeIntentApprovalService(
            self.repo.db, default_ttl_seconds=self.settings.approval_ttl_seconds
        )
        if approval_id is not None:
            approval, intent = service.claim_for_execution(approval_id)
        elif intent_id is not None:
            approval = None
            intent = service.claim_auto_for_execution(intent_id)
        else:
            raise ValueError("an approval or autonomous intent reference is required")
        if intent.execution_mode == "HUMAN_APPROVAL" and approval is None:
            raise ValueError("human execution requires an approval")
        connection = self.repo.current_connection()
        if connection is None and intent.execution_mode == "HUMAN_APPROVAL":
            return ExecutionResult("AUTH_REQUIRED", "Binance Agent OS connection is unavailable")
        with account_execution_lock(self.repo.db, self.settings.binance_account_lock_key):
            self.repo.db.refresh(intent)
            if intent.external_call_started_at is not None or intent.local_state in {
                "SUBMITTING",
                "SUBMISSION_UNKNOWN",
                "WAITING_FOR_EXECUTION_CONFIRMATION",
            }:
                from darwinspot.agent.cycle import reconcile_open_intents

                if intent.local_state == "WAITING_FOR_EXECUTION_CONFIRMATION":
                    return ExecutionResult(intent.local_state)
                await reconcile_open_intents(self.repo, self.client)
                return ExecutionResult(intent.local_state)
            try:
                self.repo.ensure_submission_allowed()
                catalog, _decision, evaluation = await self._revalidate(intent)
            except SubmissionBlocked as exc:
                self._complete(service, approval, intent, "BLOCKED", str(exc))
                return ExecutionResult("BLOCKED", str(exc))
            except CodexAuthRequired as exc:
                return ExecutionResult("AUTH_REQUIRED", str(exc))
            except AgentOSAuthInvalid as exc:
                if connection is not None:
                    self.repo.mark_connection_unavailable(connection.id)
                self.repo.db.commit()
                return ExecutionResult("AUTH_REQUIRED", str(exc))
            except RevalidationRejected as exc:
                self._complete(service, approval, intent, "REVALIDATION_FAILED", str(exc))
                return ExecutionResult("REVALIDATION_FAILED", str(exc))
            except (
                AgentOSUnavailable,
                BinanceMappingError,
                ExecutionUnavailable,
                TimeoutError,
            ) as exc:
                log_event(
                    "REVALIDATION_UNAVAILABLE", intent_id=intent.id, error_code=type(exc).__name__
                )
                return ExecutionResult("REVALIDATION_PENDING", str(exc))
            if not evaluation.allowed:
                reason = evaluation.reason or "deterministic revalidation failed"
                self._complete(service, approval, intent, "REVALIDATION_FAILED", reason)
                return ExecutionResult("REVALIDATION_FAILED", reason)
            if (
                intent.execution_mode == "HUMAN_APPROVAL"
                and not self.settings.codex_write_confirmation_verified
            ):
                reason = "Codex/Binance write confirmation capability is unverified"
                self._complete(service, approval, intent, "BLOCKED", reason)
                return ExecutionResult("BLOCKED", reason)
            try:
                call = catalog.arguments("submit_order", {"intent": intent})
            except UnsupportedCapability as exc:
                self._complete(service, approval, intent, "BLOCKED", str(exc))
                return ExecutionResult("BLOCKED", str(exc))
            intent.write_request_hash = hashlib.sha256(
                json.dumps(call.arguments, default=str, sort_keys=True).encode("utf-8")
            ).hexdigest()
            intent.local_state = "SUBMITTING"
            intent.external_call_started_at = datetime.now(UTC)
            intent.updated_at = datetime.now(UTC)
            self.repo.db.commit()
            try:
                from darwinspot.agent.cycle import submit_intent

                await submit_intent(self.repo, self.client, catalog, intent)
            except CodexConfirmationRequired as exc:
                intent.local_state = "WAITING_FOR_EXECUTION_CONFIRMATION"
                intent.confirmation_request_id = str(exc.request_id)
                if exc.expires_at is not None:
                    try:
                        intent.confirmation_expires_at = datetime.fromisoformat(exc.expires_at)
                    except ValueError:
                        intent.confirmation_expires_at = None
                transport = getattr(self.client, "transport", None)
                if transport is not None:
                    remember_pending_confirmation(intent.id, transport, exc.request_id)
                intent.updated_at = datetime.now(UTC)
                self.repo.db.commit()
                log_event("BINANCE_CONFIRMATION_REQUIRED", intent_id=intent.id)
                return ExecutionResult("WAITING_FOR_EXECUTION_CONFIRMATION", str(exc))
            except AgentOSAuthInvalid as exc:
                self._complete(service, approval, intent, "SUBMISSION_UNKNOWN", str(exc))
                return ExecutionResult("SUBMISSION_UNKNOWN", str(exc))
            except UnsupportedCapability as exc:
                self._complete(service, approval, intent, "BLOCKED", str(exc))
                return ExecutionResult("BLOCKED", str(exc))
            except AgentOSUnavailable as exc:
                self._complete(service, approval, intent, "SUBMISSION_UNKNOWN", str(exc))
                return ExecutionResult("SUBMISSION_UNKNOWN", str(exc))
            except TimeoutError as exc:
                self._complete(
                    service,
                    approval,
                    intent,
                    "SUBMISSION_UNKNOWN",
                    "submission timed out; reconciliation required",
                )
                return ExecutionResult("SUBMISSION_UNKNOWN", str(exc))
            except ValueError as exc:
                self._complete(service, approval, intent, "BLOCKED", str(exc))
                return ExecutionResult("BLOCKED", str(exc))
            state = intent.local_state
            self._complete(service, approval, intent, state, state)
            return ExecutionResult(state)

    @staticmethod
    def _complete(
        service: TradeIntentApprovalService,
        approval: TradeIntentApproval | None,
        intent: TradeIntent,
        state: str,
        reason: str,
    ) -> None:
        if approval is not None:
            service.consume(approval.approval_id, intent_state=state, reason=reason)
        else:
            service.complete_auto(intent.id, intent_state=state, reason=reason)

    async def cancel_for_emergency_stop(
        self, intent_id: str, operator_action_id: str
    ) -> ExecutionResult:
        connection = self.repo.current_connection()
        intent = self.repo.db.get(TradeIntent, intent_id)
        if intent is None:
            return ExecutionResult("NOT_FOUND", "emergency-stop target is unavailable")
        if connection is None and intent.execution_mode == "HUMAN_APPROVAL":
            return ExecutionResult("AUTH_REQUIRED", "Binance Agent OS connection is unavailable")
        if intent.local_state in {"CANCELED", "FILLED", "EXPIRED", "REJECTED_EXCHANGE"}:
            return ExecutionResult(intent.local_state)
        if not intent.binance_order_id:
            return ExecutionResult("CANCEL_UNAVAILABLE", "Binance order identifier is unknown")
        with account_execution_lock(self.repo.db, self.settings.binance_account_lock_key):
            intent.local_state = "CANCEL_PENDING"
            intent.updated_at = datetime.now(UTC)
            self.repo.db.commit()
            catalog = ToolCatalog(await self.client.discover_tools())
            raw = await self.client.call_tool(
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
            self.repo.apply_order_status(
                intent,
                order_id=response.order_id,
                status=response.status,
                filled_quantity=response.executed_quantity,
                filled_notional=response.quote_notional,
                exchange_timestamp=response.updated_at,
                evidence={
                    "operator_action_id": operator_action_id,
                    "response": response.model_dump(mode="json"),
                },
            )
            self.repo.db.commit()
            log_event(
                "EMERGENCY_CANCEL_RECONCILED",
                intent_id=intent.id,
                operator_action_id=operator_action_id,
                state=intent.local_state,
            )
            return ExecutionResult(intent.local_state)

    async def _revalidate(
        self, intent: TradeIntent
    ) -> tuple[ToolCatalog, AgentDecision, PolicyEvaluation]:
        catalog = ToolCatalog(await self.client.discover_tools())
        policy = self.repo.current_policy()
        if policy is None:
            raise ExecutionUnavailable("current policy is required")
        market_universe = map_spot_market_universe(
            await self.client.call_tool(catalog.arguments("market_universe", {}))
        )
        live_universe = effective_symbols(
            self.repo.supported_symbols(), policy.allowed_symbols, market_universe
        )
        if intent.pair not in live_universe.eligible:
            raise RevalidationRejected(
                "intent symbol is disabled in the effective Spot universe"
            )
        observed_at = datetime.now(UTC)
        market = map_mcp_result(
            "get_ticker",
            await self.client.call_tool(catalog.arguments("market", {"symbol": intent.pair})),
            observed_at=observed_at,
        )
        balances = map_balances(
            await self.client.call_tool(catalog.arguments("balances", {})), observed_at=observed_at
        )
        open_orders = map_open_orders(
            await self.client.call_tool(catalog.arguments("open_orders", {"symbol": intent.pair})),
            observed_at=observed_at,
        )
        recent_activity = map_recent_activity(
            await self.client.call_tool(
                catalog.arguments(
                    "recent_activity",
                    {
                        "symbol": intent.pair,
                        "startTime": int((observed_at - timedelta(hours=24)).timestamp() * 1000),
                        "endTime": int(observed_at.timestamp() * 1000),
                    },
                )
            ),
            observed_at=observed_at,
        )
        filters = map_symbol_filters(
            await self.client.call_tool(
                catalog.arguments("symbol_filters", {"symbol": intent.pair})
            ),
            observed_at=observed_at,
        )
        now = datetime.now(UTC)
        for source_name, timestamp, observed in (
            ("market", market.timestamp, market.observed_at),
            ("balances", balances.timestamp, balances.observed_at),
            ("open_orders", open_orders.timestamp, open_orders.observed_at),
            ("recent_activity", recent_activity.timestamp, recent_activity.observed_at),
            ("symbol_filters", filters.timestamp, filters.observed_at),
        ):
            freshness = timestamp or observed
            if (
                freshness.tzinfo is None
                or freshness > now
                or now - freshness > timedelta(seconds=60)
            ):
                raise ExecutionUnavailable(f"{source_name} revalidation evidence is stale")
        budget = self.repo.budget_snapshot()
        if budget is None:
            raise ExecutionUnavailable("current budget and policy are required")
        decision = AgentDecision(
            action=cast(Any, intent.side),
            pair=intent.pair,
            order_type=cast(Any, intent.order_type),
            side=cast(Any, intent.side),
            quantity=Decimal(str(intent.quantity)),
            price=Decimal(str(intent.price)) if intent.price is not None else None,
            rationale=intent.rationale or "approved intent revalidation",
            evidence=["fresh_market", "fresh_balances", "fresh_filters"],
            confidence=Decimal(str(intent.confidence)),
            supporting_factors=cast(list[str], json.loads(intent.supporting_factors)),
            risk_factors=cast(list[str], json.loads(intent.risk_factors)),
        )
        evaluation = evaluate_execution_policy(
            policy,
            decision=decision,
            market=market,
            balances=balances,
            filters=filters,
            open_orders=open_orders,
            budget=budget,
            emergency_stop=self.repo.get_or_create_agent().emergency_stop,
            actionable_intent_count=self.repo.actionable_intent_count(exclude_intent_id=intent.id),
            eligible_symbols=live_universe.eligible,
        )
        mandate = self.repo.current_mandate()
        intent.revalidation_evidence = json.dumps(
            {
                "mandate_version": mandate.id if mandate else None,
                "computed_notional": (
                    str(evaluation.computed_notional)
                    if evaluation.computed_notional is not None
                    else None
                ),
                "mandate_result": evaluation.mandate_result,
                "risk_result": evaluation.risk_result,
                "budget_result": evaluation.budget_result,
                "execution_policy_result": evaluation.execution_policy_result,
                "reason": evaluation.reason,
                "observed_at": observed_at.isoformat(),
            },
            sort_keys=True,
        )
        intent.updated_at = datetime.now(UTC)
        self.repo.db.commit()
        return catalog, decision, evaluation
