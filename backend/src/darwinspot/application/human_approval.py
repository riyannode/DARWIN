from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from darwinspot.agent.schemas import AgentDecision
from darwinspot.approval.service import ApprovalError, ApprovalResult, TradeIntentApprovalService
from darwinspot.binance.client import ToolCatalog
from darwinspot.binance.factory import build_binance_client
from darwinspot.binance.mapper import (
    map_balances,
    map_mcp_result,
    map_open_orders,
    map_recent_activity,
    map_spot_market_universe,
    map_symbol_filters,
)
from darwinspot.config import Settings, get_settings
from darwinspot.execution.demo_guard import FinancialWriteBlocked, ensure_financial_write_allowed
from darwinspot.execution.modes import ExecutionMode
from darwinspot.execution.policy import PolicyEvaluation, evaluate_execution_policy
from darwinspot.execution.universe import effective_symbols
from darwinspot.notifications.outbox import CONFIRMATION_KIND, enqueue_unique
from darwinspot.storage.models import TradeIntent, TradeIntentApproval
from darwinspot.storage.repository import Repository

ProposalSide = Literal["BUY", "SELL"]
ProposalOrderType = Literal["MARKET", "LIMIT"]
ConfirmationAction = Literal["ACCEPT", "DECLINE", "CANCEL"]


class ProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(pattern=r"^[A-Z0-9]{5,20}$")
    side: ProposalSide
    order_type: ProposalOrderType = "MARKET"
    quantity: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=30)
    intended_notional: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=30)
    price: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=30)
    confidence: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    rationale: str = Field(default="", max_length=2000)
    supporting_factors: list[str] = Field(default_factory=list, max_length=6)
    risk_factors: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_shape(self) -> ProposalInput:
        if self.order_type == "LIMIT" and (self.quantity is None or self.price is None):
            raise ValueError("LIMIT proposals require quantity and price")
        if self.order_type == "LIMIT" and self.intended_notional is not None:
            raise ValueError("LIMIT proposals do not accept intended_notional")
        if self.side == "SELL" and self.quantity is None:
            raise ValueError("SELL proposals require quantity")
        if self.side == "SELL" and self.intended_notional is not None:
            raise ValueError("SELL proposals do not accept intended_notional")
        if self.order_type == "MARKET" and self.side == "BUY":
            if (self.quantity is None) == (self.intended_notional is None):
                raise ValueError(
                    "BUY MARKET proposals require exactly one of quantity or intended_notional"
                )
        return self


class SubmitProposalInput(ProposalInput):
    idempotency_key: str = Field(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-fA-F-]{36}$",
    )


@dataclass(frozen=True)
class NormalizedProposal:
    decision: AgentDecision
    committed_notional: Decimal | None
    reference_price: Decimal
    policy: PolicyEvaluation
    policy_evidence: dict[str, Any]


@dataclass(frozen=True)
class ProposalEvaluation:
    allowed: bool
    reasons: tuple[str, ...]
    normalized: dict[str, str | None]
    policy: dict[str, str | None]

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": "PASS" if self.allowed else "REJECT",
            "reasons": list(self.reasons),
            "normalized": self.normalized,
            "policy": self.policy,
        }


@dataclass(frozen=True)
class DurableProposalResult:
    accepted: bool
    deduplicated: bool
    intent_id: str | None
    approval_id: str | None
    intent_state: str | None
    approval_state: str | None
    evaluation: ProposalEvaluation

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "deduplicated": self.deduplicated,
            "intentId": self.intent_id,
            "approvalId": self.approval_id,
            "intentState": self.intent_state,
            "approvalState": self.approval_state,
            "evaluation": self.evaluation.as_dict(),
        }


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def _fresh(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return False
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware <= now and now - aware.astimezone(UTC) <= timedelta(seconds=60)


def _policy_dict(evaluation: PolicyEvaluation) -> dict[str, str | None]:
    return {
        "mandate": evaluation.mandate_result,
        "risk": evaluation.risk_result,
        "budget": evaluation.budget_result,
        "executionPolicy": evaluation.execution_policy_result,
        "computedNotional": (
            str(evaluation.computed_notional) if evaluation.computed_notional is not None else None
        ),
        "reason": evaluation.reason,
    }


class HumanApprovalApplication:
    """Deep application seam for untrusted external HUMAN_APPROVAL proposals."""

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.repo = Repository(db)

    async def validate_proposal(self, proposal: ProposalInput) -> ProposalEvaluation:
        try:
            normalized = await self._evaluate(proposal)
        except (ApprovalError, FinancialWriteBlocked, ValueError, RuntimeError) as exc:
            return ProposalEvaluation(
                allowed=False,
                reasons=(str(exc),),
                normalized={"symbol": proposal.symbol, "side": proposal.side},
                policy={},
            )
        return self._evaluation_result(normalized)

    async def submit_proposal(
        self, proposal: ProposalInput, idempotency_key: str
    ) -> DurableProposalResult:
        existing = self.repo.find_intent_by_idempotency_key(idempotency_key)
        if existing is not None:
            approval = self._approval_for_intent(existing.id)
            evaluation = self._evaluation_from_intent(existing)
            if not self._matches_existing(existing, proposal):
                raise ValueError("idempotency key is already bound to a different proposal")
            return DurableProposalResult(
                accepted=True,
                deduplicated=True,
                intent_id=existing.id,
                approval_id=approval.approval_id if approval else None,
                intent_state=existing.local_state,
                approval_state=approval.status if approval else None,
                evaluation=evaluation,
            )

        normalized = await self._evaluate(proposal)
        evaluation = self._evaluation_result(normalized)
        if not evaluation.allowed:
            return DurableProposalResult(False, False, None, None, None, None, evaluation)

        run = self.repo.start_run("MCP_PROPOSAL", "external-mcp-host")
        self.repo.record_decision(
            run.id,
            normalized.decision.model_dump(mode="json"),
            {"source": "external_mcp_host", "policy": normalized.policy_evidence},
        )
        try:
            intent, approval = self.repo.create_waiting_intent(
                run_id=run.id,
                decision=normalized.decision.model_dump(mode="json"),
                evaluation=normalized.policy,
                policy_evidence=normalized.policy_evidence,
                operator_user_id="MCP_OWNER",
                operator_chat_id="MCP_CONTROL_PANEL",
                ttl_seconds=self.settings.approval_ttl_seconds,
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            self.db.rollback()
            existing = self.repo.find_intent_by_idempotency_key(idempotency_key)
            if existing is None or not self._matches_existing(existing, proposal):
                raise ValueError("proposal idempotency conflict") from None
            approval = self._approval_for_intent(existing.id)
            if approval is None:
                raise ValueError("idempotent intent has no approval record") from None
            return DurableProposalResult(
                True,
                True,
                existing.id,
                approval.approval_id,
                existing.local_state,
                approval.status,
                self._evaluation_from_intent(existing),
            )
        self.repo.complete_run(
            run.id,
            "WAITING_FOR_APPROVAL",
            None,
            "external MCP proposal admitted",
        )
        return DurableProposalResult(
            True,
            False,
            intent.id,
            approval.approval_id,
            intent.local_state,
            approval.status,
            evaluation,
        )

    def approve_trade(self, intent_id: str) -> ApprovalResult:
        return self._decide(intent_id, "APPROVE")

    def reject_trade(self, intent_id: str) -> ApprovalResult:
        return self._decide(intent_id, "REJECT")

    def queue_execution_confirmation(
        self, intent_id: str, action: ConfirmationAction
    ) -> dict[str, str]:
        intent = self.db.get(TradeIntent, intent_id)
        if intent is None:
            raise ValueError("intent not found")
        if (
            intent.execution_mode != ExecutionMode.HUMAN_APPROVAL
            or intent.local_state != "WAITING_FOR_EXECUTION_CONFIRMATION"
            or not intent.confirmation_request_id
        ):
            raise ValueError("intent is not awaiting provider confirmation")
        enqueue_unique(
            self.db,
            kind=CONFIRMATION_KIND,
            aggregate_id=intent.id,
            payload={"intent_id": intent.id, "action": action},
            dedupe_key=f"resolve-confirmation:{intent.id}:{action}",
        )
        self.db.commit()
        return {"intentId": intent.id, "state": "CONFIRMATION_RESOLUTION_QUEUED"}

    async def _evaluate(self, proposal: ProposalInput) -> NormalizedProposal:
        config = self.repo.get_or_create_agent()
        policy = self.repo.current_policy()
        budget = self.repo.budget_snapshot()
        if policy is None or budget is None:
            raise ValueError("current mandate and budget are required")
        if config.emergency_stop:
            raise ValueError("emergency stop is active")
        if proposal.symbol not in policy.configured_symbols:
            raise ValueError("symbol is not in configured trading universe")
        if proposal.symbol not in policy.allowed_symbols:
            raise ValueError("symbol is not in allowed_symbols")

        client = build_binance_client(
            self.settings,
            self.repo.current_connection(),
            mode=ExecutionMode.HUMAN_APPROVAL,
        )
        try:
            catalog = ToolCatalog(await client.discover_tools())
            live_market = map_spot_market_universe(
                await client.call_tool(catalog.arguments("market_universe", {}))
            )
            universe = effective_symbols(
                self.repo.supported_symbols(), policy.allowed_symbols, live_market
            )
            if proposal.symbol not in universe.eligible:
                raise ValueError(
                    "symbol is not currently valid in the effective Spot/USDT universe"
                )
            observed_at = datetime.now(UTC)
            market = map_mcp_result(
                "get_ticker",
                await client.call_tool(catalog.arguments("market", {"symbol": proposal.symbol})),
                observed_at=observed_at,
            )
            balances = map_balances(
                await client.call_tool(catalog.arguments("balances", {})), observed_at=observed_at
            )
            open_orders = map_open_orders(
                await client.call_tool(
                    catalog.arguments("open_orders", {"symbol": proposal.symbol})
                ),
                observed_at=observed_at,
            )
            recent_activity = map_recent_activity(
                await client.call_tool(
                    catalog.arguments(
                        "recent_activity",
                        {
                            "symbol": proposal.symbol,
                            "startTime": int(
                                (observed_at - timedelta(hours=24)).timestamp() * 1000
                            ),
                            "endTime": int(observed_at.timestamp() * 1000),
                        },
                    )
                ),
                observed_at=observed_at,
            )
            filters = map_symbol_filters(
                await client.call_tool(
                    catalog.arguments("symbol_filters", {"symbol": proposal.symbol})
                ),
                observed_at=observed_at,
            )
        finally:
            transport = getattr(client, "transport", None)
            if transport is not None:
                await transport.close()

        now = datetime.now(UTC)
        for name, timestamp, observed in (
            ("market", market.timestamp, market.observed_at),
            ("balances", balances.timestamp, balances.observed_at),
            ("open_orders", open_orders.timestamp, open_orders.observed_at),
            ("recent_activity", recent_activity.timestamp, recent_activity.observed_at),
            ("symbol_filters", filters.timestamp, filters.observed_at),
        ):
            if not _fresh(timestamp or observed, now):
                raise ValueError(f"{name} evidence is stale")

        quantity = proposal.quantity
        price = proposal.price
        reference_price = market.price
        if proposal.order_type == "LIMIT":
            if price is None or quantity is None:
                raise ValueError("LIMIT proposal requires quantity and price")
            price = _floor_to_step(price, filters.tick_size)
            quantity = _floor_to_step(quantity, filters.step_size)
            reference_price = price
        elif proposal.side == "BUY" and proposal.intended_notional is not None:
            quantity = _floor_to_step(proposal.intended_notional / market.price, filters.step_size)
        elif quantity is not None:
            quantity = _floor_to_step(quantity, filters.step_size)
        if quantity is None or quantity <= 0:
            raise ValueError("normalized quantity is not positive")

        decision = AgentDecision(
            action=proposal.side,
            pair=proposal.symbol,
            order_type=proposal.order_type,
            side=proposal.side,
            quantity=quantity,
            price=price,
            rationale=proposal.rationale or "external MCP proposal",
            evidence=["fresh_market", "fresh_balances", "fresh_filters", "fresh_open_orders"],
            confidence=proposal.confidence or Decimal("0"),
            supporting_factors=proposal.supporting_factors or ["external_mcp_proposal"],
            risk_factors=proposal.risk_factors or ["host_input_untrusted"],
        )
        evaluation = evaluate_execution_policy(
            policy,
            decision=decision,
            market=market,
            balances=balances,
            filters=filters,
            open_orders=open_orders,
            budget=budget,
            emergency_stop=config.emergency_stop,
            actionable_intent_count=self.repo.actionable_intent_count(),
            eligible_symbols=universe.eligible,
        )
        mandate = self.repo.current_mandate()
        policy_evidence = {
            "mandate_result": evaluation.mandate_result,
            "risk_result": evaluation.risk_result,
            "budget_result": evaluation.budget_result,
            "execution_policy_result": evaluation.execution_policy_result,
            "reason": evaluation.reason,
            "computed_notional": (
                str(evaluation.computed_notional)
                if evaluation.computed_notional is not None
                else None
            ),
            "mandate_version": mandate.id if mandate is not None else None,
            "reference_price": str(reference_price),
            "observed_at": observed_at.isoformat(),
        }
        if not evaluation.allowed:
            return NormalizedProposal(
                decision,
                evaluation.computed_notional,
                reference_price,
                evaluation,
                policy_evidence,
            )
        try:
            ensure_financial_write_allowed()
        except FinancialWriteBlocked as exc:
            raise ValueError(exc.reason_code) from exc
        return NormalizedProposal(
            decision,
            evaluation.computed_notional,
            reference_price,
            evaluation,
            policy_evidence,
        )

    def _evaluation_result(self, normalized: NormalizedProposal) -> ProposalEvaluation:
        reasons = tuple(reason for reason in (normalized.policy.reason,) if reason is not None)
        return ProposalEvaluation(
            allowed=normalized.policy.allowed,
            reasons=reasons,
            normalized={
                "symbol": normalized.decision.pair,
                "side": normalized.decision.side,
                "orderType": normalized.decision.order_type,
                "quantity": str(normalized.decision.quantity)
                if normalized.decision.quantity is not None
                else None,
                "price": str(normalized.decision.price)
                if normalized.decision.price is not None
                else None,
                "committedNotional": (
                    str(normalized.committed_notional)
                    if normalized.committed_notional is not None
                    else None
                ),
                "referencePrice": str(normalized.reference_price),
            },
            policy=_policy_dict(normalized.policy),
        )

    def _decide(self, intent_id: str, decision: Literal["APPROVE", "REJECT"]) -> ApprovalResult:
        approval = self._approval_for_intent(intent_id)
        if approval is None:
            raise ValueError("intent has no approval record")
        return TradeIntentApprovalService(
            self.db, default_ttl_seconds=self.settings.approval_ttl_seconds
        ).decide(
            approval.approval_id,
            decision,
            operator_user_id="MCP_OWNER",
            operator_chat_id="MCP_CONTROL_PANEL",
            source="MCP",
        )

    def _approval_for_intent(self, intent_id: str) -> TradeIntentApproval | None:
        return self.db.scalar(
            select(TradeIntentApproval).where(TradeIntentApproval.intent_id == intent_id).limit(1)
        )

    @staticmethod
    def _matches_existing(intent: TradeIntent, proposal: ProposalInput) -> bool:
        return (
            intent.pair == proposal.symbol
            and intent.side == proposal.side
            and intent.order_type == proposal.order_type
            and (proposal.rationale or "external MCP proposal") == intent.rationale
        )

    @staticmethod
    def _evaluation_from_intent(intent: TradeIntent) -> ProposalEvaluation:
        policy = cast(dict[str, Any], json.loads(intent.policy_evidence or "{}"))
        return ProposalEvaluation(
            allowed=True,
            reasons=(),
            normalized={
                "symbol": intent.pair,
                "side": intent.side,
                "orderType": intent.order_type,
                "quantity": str(intent.quantity),
                "price": str(intent.price) if intent.price is not None else None,
                "committedNotional": (
                    str(intent.committed_notional)
                    if intent.committed_notional is not None
                    else None
                ),
                "referencePrice": policy.get("reference_price"),
            },
            policy={
                "mandate": policy.get("mandate_result"),
                "risk": policy.get("risk_result"),
                "budget": policy.get("budget_result"),
                "executionPolicy": policy.get("execution_policy_result"),
                "computedNotional": policy.get("computed_notional"),
                "reason": policy.get("reason"),
            },
        )
