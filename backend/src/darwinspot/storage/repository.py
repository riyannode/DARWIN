from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from darwinspot.domain import AgentState, new_idempotency_key, now_utc
from darwinspot.execution.budget import (
    BudgetExceeded,
    BudgetSnapshot,
    BuyFill,
    OpenBuyCommitment,
    calculate_budget,
)
from darwinspot.execution.orders import SubmissionBlocked
from darwinspot.observability import log_event
from darwinspot.security.sessions import hash_session_token
from darwinspot.storage.models import (
    AgentConfig,
    AgentRun,
    BinanceConnection,
    BudgetVersion,
    MandateVersion,
    OrderEvent,
    OwnerSession,
    TradeIntent,
)


class Repository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create_agent(self) -> AgentConfig:
        config = self.db.scalar(select(AgentConfig).limit(1))
        if config is None:
            config = AgentConfig(id=new_idempotency_key(), state=AgentState.DISCONNECTED)
            self.db.add(config)
            self.db.commit()
        return config

    def claim_due_run(self, interval_seconds: int) -> AgentConfig | None:
        now = now_utc()
        config = self.db.scalar(select(AgentConfig).with_for_update().limit(1))
        if (
            config is None
            or config.state != AgentState.RUNNING
            or config.next_run_at is None
            or config.next_run_at > now
        ):
            return None
        config.next_run_at = now + timedelta(seconds=interval_seconds)
        self.db.commit()
        return config

    def current_connection(self) -> BinanceConnection | None:
        return self.db.scalar(
            select(BinanceConnection).order_by(BinanceConnection.created_at.desc())
        )

    def mark_connection_unavailable(self, connection_id: str | None = None) -> None:
        connection = (
            self.db.get(BinanceConnection, connection_id)
            if connection_id is not None
            else self.current_connection()
        )
        if connection is not None and connection.state == "CONNECTED":
            connection.state = "DISCONNECTED"
            connection.disconnected_at = now_utc()

    def current_budget(self) -> BudgetVersion | None:
        return self.db.scalar(select(BudgetVersion).order_by(BudgetVersion.created_at.desc()))

    def current_mandate(self) -> MandateVersion | None:
        return self.db.scalar(select(MandateVersion).order_by(MandateVersion.created_at.desc()))

    def latest_run(self) -> AgentRun | None:
        return self.db.scalar(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(1))

    def budget_snapshot(self) -> BudgetSnapshot | None:
        budget = self.current_budget()
        if budget is None:
            return None
        intents = self.db.scalars(select(TradeIntent).where(TradeIntent.side == "BUY")).all()
        events = self.db.scalars(select(OrderEvent)).all()
        filled_by_intent: dict[str, Decimal] = {}
        fills: list[BuyFill] = []
        for event in events:
            if event.filled_notional is None:
                continue
            filled_by_intent[event.intent_id] = (
                filled_by_intent.get(event.intent_id, Decimal("0")) + event.filled_notional
            )
            intent = next((item for item in intents if item.id == event.intent_id), None)
            if (
                intent is not None
                and intent.side == "BUY"
                and event.upstream_event_type in {"FILL", "PARTIAL_FILL", "FILLED"}
            ):
                fills.append(BuyFill(event.filled_notional, event.observed_at))
        commitments: list[OpenBuyCommitment] = []
        for intent in intents:
            if intent.local_state not in {
                "OPEN",
                "PARTIALLY_FILLED",
                "SUBMITTING",
                "SUBMISSION_UNKNOWN",
                "CANCEL_PENDING",
            }:
                continue
            reserved = intent.committed_notional or intent.quote_notional or Decimal("0")
            commitments.append(
                OpenBuyCommitment(
                    max(Decimal("0"), reserved - filled_by_intent.get(intent.id, Decimal("0")))
                )
            )
        return calculate_budget(budget.daily_budget, now_utc(), fills, commitments)

    def find_intent_by_order_id(self, order_id: str) -> TradeIntent | None:
        return self.db.scalar(
            select(TradeIntent).where(
                (TradeIntent.binance_order_id == order_id) | (TradeIntent.id == order_id)
            )
        )

    def non_terminal_intents(self) -> list[TradeIntent]:
        return list(
            self.db.scalars(
                select(TradeIntent).where(
                    TradeIntent.local_state.not_in(
                        [
                            "FILLED",
                            "CANCELED",
                            "EXPIRED",
                            "REJECTED_EXCHANGE",
                        ]
                    )
                )
            ).all()
        )

    def record_order_event(
        self,
        *,
        intent: TradeIntent,
        event_type: str,
        filled_quantity: Decimal | None,
        filled_notional: Decimal | None,
        exchange_timestamp: datetime | None,
        evidence: dict[str, Any],
    ) -> OrderEvent:
        sanitized = json.dumps(evidence, default=str, sort_keys=True)
        payload_hash = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
        existing = self.db.scalar(
            select(OrderEvent)
            .where(OrderEvent.intent_id == intent.id, OrderEvent.payload_hash == payload_hash)
            .limit(1)
        )
        if existing is not None:
            return existing
        event = OrderEvent(
            id=new_idempotency_key(),
            intent_id=intent.id,
            upstream_event_type=event_type,
            filled_quantity=filled_quantity,
            filled_notional=filled_notional,
            fee=None,
            exchange_timestamp=exchange_timestamp,
            observed_at=now_utc(),
            payload_hash=payload_hash,
            sanitized_evidence=sanitized,
        )
        try:
            with self.db.begin_nested():
                self.db.add(event)
                self.db.flush()
        except IntegrityError:
            existing = self.db.scalar(
                select(OrderEvent)
                .where(
                    OrderEvent.intent_id == intent.id,
                    OrderEvent.payload_hash == payload_hash,
                )
                .limit(1)
            )
            if existing is None:
                raise
            return existing
        return event

    def apply_order_status(
        self,
        intent: TradeIntent,
        *,
        order_id: str | None,
        status: str,
        filled_quantity: Decimal | None = None,
        filled_notional: Decimal | None = None,
        exchange_timestamp: datetime | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        state = {
            "NEW": "OPEN",
            "OPEN": "OPEN",
            "PARTIALLY_FILLED": "PARTIALLY_FILLED",
            "FILLED": "FILLED",
            "CANCELED": "CANCELED",
            "EXPIRED": "EXPIRED",
            "REJECTED": "REJECTED_EXCHANGE",
            "REJECTED_EXCHANGE": "REJECTED_EXCHANGE",
        }.get(status)
        if state is None:
            if intent.local_state in {
                "FILLED",
                "CANCELED",
                "EXPIRED",
                "REJECTED_EXCHANGE",
            }:
                return
            if order_id:
                intent.binance_order_id = order_id
            intent.exchange_state = status
            if intent.local_state == "CANCEL_PENDING":
                intent.updated_at = now_utc()
                return
            intent.local_state = "SUBMISSION_UNKNOWN"
            intent.updated_at = now_utc()
            return
        if (
            intent.local_state
            in {
                "FILLED",
                "CANCELED",
                "EXPIRED",
                "REJECTED_EXCHANGE",
            }
            and intent.local_state != state
        ):
            return
        preserve_cancel_pending = intent.local_state == "CANCEL_PENDING" and state in {
            "OPEN",
            "PARTIALLY_FILLED",
        }
        if intent.local_state == "PARTIALLY_FILLED" and state == "OPEN":
            return
        if order_id:
            intent.binance_order_id = order_id
        intent.exchange_state = status
        intent.local_state = "CANCEL_PENDING" if preserve_cancel_pending else state
        intent.updated_at = now_utc()
        previous_filled = sum(
            (
                event.filled_notional or Decimal("0")
                for event in self.db.scalars(
                    select(OrderEvent).where(OrderEvent.intent_id == intent.id)
                ).all()
            ),
            Decimal("0"),
        )
        event_notional = None
        event_quantity = None
        if filled_notional is not None:
            event_notional = max(Decimal("0"), filled_notional - previous_filled)
        if filled_quantity is not None:
            previous_quantity = sum(
                (
                    event.filled_quantity or Decimal("0")
                    for event in self.db.scalars(
                        select(OrderEvent).where(OrderEvent.intent_id == intent.id)
                    ).all()
                ),
                Decimal("0"),
            )
            event_quantity = max(Decimal("0"), filled_quantity - previous_quantity)
        fill_event = status == "FILLED" and event_notional is not None and event_notional > 0
        self.record_order_event(
            intent=intent,
            event_type=(
                "FILLED"
                if fill_event
                else "PARTIAL_FILL"
                if event_notional is not None and event_notional > 0
                else {
                    "PARTIALLY_FILLED": "PARTIAL_FILL",
                    "FILLED": "FILLED",
                }.get(status, status)
            ),
            filled_quantity=event_quantity,
            filled_notional=event_notional,
            exchange_timestamp=exchange_timestamp,
            evidence=evidence or {"status": status, "orderId": order_id},
        )
        event_code = {
            "OPEN": "ORDER_OPEN",
            "PARTIALLY_FILLED": "ORDER_PARTIAL_FILL",
            "FILLED": "ORDER_FILLED",
            "CANCELED": "ORDER_CANCELED",
        }.get(state)
        if event_code is not None:
            log_event(event_code, intent_id=intent.id, order_id=order_id, state=state)

    def create_session(self, raw_token: str) -> OwnerSession:
        now = now_utc()
        session = OwnerSession(
            id=new_idempotency_key(),
            token_hash=hash_session_token(raw_token),
            created_at=now,
            expires_at=now + timedelta(hours=12),
        )
        self.db.add(session)
        self.db.commit()
        return session

    def get_session(self, raw_token: str) -> OwnerSession | None:
        session = self.db.scalar(
            select(OwnerSession).where(OwnerSession.token_hash == hash_session_token(raw_token))
        )
        if session is None or session.revoked_at is not None:
            return None
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now_utc():
            return None
        session.last_used_at = now_utc()
        self.db.commit()
        return session

    def redact_connection(self, connection: BinanceConnection | None) -> dict[str, Any]:
        if connection is None:
            return {"state": "DISCONNECTED", "accountReference": None, "capabilities": []}
        return {
            "state": connection.state,
            "accountReference": connection.account_reference,
            "capabilities": json.loads(connection.capabilities),
        }

    @staticmethod
    def content_hash(values: dict[str, str]) -> str:
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest()

    def save_budget(self, amount: Decimal) -> BudgetVersion:
        if not amount.is_finite() or amount <= Decimal("0"):
            raise ValueError("daily budget must be a finite positive decimal")
        version_id = new_idempotency_key()
        now = now_utc()
        values = {"id": version_id, "daily_budget": str(amount)}
        version = BudgetVersion(
            id=version_id,
            daily_budget=amount,
            created_at=now,
            budget_hash=self.content_hash(values),
        )
        self.db.add(version)
        self.db.commit()
        return version

    def save_mandate(self, fields: dict[str, str]) -> MandateVersion:
        version_id = new_idempotency_key()
        version = MandateVersion(
            id=version_id,
            assets=fields["assets"],
            entry_rules=fields["entry_rules"],
            sizing_rules=fields["sizing_rules"],
            exit_rules=fields["exit_rules"],
            created_at=now_utc(),
            content_hash=self.content_hash(fields),
        )
        self.db.add(version)
        config = self.get_or_create_agent()
        config.active_mandate_version = version_id
        self.db.commit()
        return version

    def start_run(self, trigger: str, model: str) -> AgentRun:
        mandate = self.current_mandate()
        budget = self.current_budget()
        run = AgentRun(
            id=new_idempotency_key(),
            trigger_type=trigger,
            model=model,
            prompt_version="darwinspot-v1",
            mandate_version=mandate.id if mandate else None,
            budget_version=budget.id if budget else None,
            started_at=now_utc(),
        )
        self.db.add(run)
        self.db.commit()
        log_event("AGENT_RUN_STARTED", run_id=run.id, trigger_type=trigger)
        return run

    def record_audit_event(
        self,
        *,
        trigger: str,
        state: str,
        model: str,
        evidence: dict[str, Any],
    ) -> AgentRun:
        mandate = self.current_mandate()
        budget = self.current_budget()
        run = AgentRun(
            id=new_idempotency_key(),
            trigger_type=trigger,
            model=model,
            prompt_version="darwinspot-v1",
            mandate_version=mandate.id if mandate else None,
            budget_version=budget.id if budget else None,
            evidence_timestamps=json.dumps(evidence, default=str, sort_keys=True),
            evidence_hash=self.content_hash(
                {"evidence": json.dumps(evidence, default=str, sort_keys=True)}
            ),
            decision=json.dumps({"action": "AUDIT", "event": trigger}, sort_keys=True),
            rationale=trigger,
            started_at=now_utc(),
            completed_at=now_utc(),
            result_state=state,
        )
        self.db.add(run)
        self.db.commit()
        log_event(trigger, run_id=run.id)
        return run

    def record_intent(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        pair: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        quote_notional: Decimal | None,
        price: Decimal | None,
        budget_result: str,
        committed_notional: Decimal | None,
        initial_state: str = "SUBMITTING",
    ) -> TradeIntent:
        if not quantity.is_finite() or quantity <= Decimal("0"):
            raise ValueError("order quantity must be finite and positive")
        stored_quote_notional = None
        if side == "BUY":
            if committed_notional is None or not committed_notional.is_finite():
                raise ValueError("backend-computed buy notional is required")
            if order_type == "LIMIT":
                if price is None or not price.is_finite() or price <= Decimal("0"):
                    raise ValueError("limit buy price is required")
                expected = quantity * price
                if committed_notional != expected:
                    raise ValueError(
                        "buy commitment does not match backend-computed limit notional"
                    )
            elif order_type != "MARKET":
                raise ValueError("unsupported buy order type")
            stored_quote_notional = committed_notional
            self.db.scalar(
                select(BudgetVersion)
                .order_by(BudgetVersion.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            snapshot = self.budget_snapshot()
            if snapshot is None:
                raise ValueError("daily budget is required before a buy")
            if committed_notional > snapshot.available_budget:
                raise BudgetExceeded("buy exceeds Available Budget")

        now = now_utc()
        intent = TradeIntent(
            id=new_idempotency_key(),
            idempotency_key=idempotency_key,
            agent_run_id=run_id,
            pair=pair,
            side=side,
            order_type=order_type,
            quantity=quantity,
            quote_notional=stored_quote_notional,
            price=price,
            budget_result=budget_result,
            committed_notional=committed_notional,
            local_state=initial_state,
            created_at=now,
            updated_at=now,
        )
        self.db.add(intent)
        self.db.commit()
        log_event(
            "ORDER_INTENT_PROPOSED" if initial_state == "PROPOSED" else "ORDER_SUBMIT_STARTED",
            intent_id=intent.id,
            pair=pair,
            side=side,
            idempotency_key=idempotency_key,
        )
        return intent

    def reserve_intent(self, intent: TradeIntent) -> None:
        """Atomically reserve a proposed buy before an external submission."""
        locked_intent = self.db.scalar(
            select(TradeIntent).where(TradeIntent.id == intent.id).with_for_update()
        )
        if locked_intent is None:
            raise ValueError("trade intent not found")
        intent = locked_intent
        if intent.local_state != "PROPOSED":
            raise ValueError("only a proposed intent can be approved")
        config = self.db.scalar(select(AgentConfig).with_for_update().limit(1))
        if config is None or config.emergency_stop:
            raise SubmissionBlocked("emergency stop is active")
        if intent.side == "BUY":
            self.db.scalar(
                select(BudgetVersion)
                .order_by(BudgetVersion.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            snapshot = self.budget_snapshot()
            committed = intent.committed_notional
            if snapshot is None or committed is None:
                raise ValueError("daily budget is required before approving a buy")
            if committed > snapshot.available_budget:
                intent.budget_result = "BUDGET_EXCEEDED"
                intent.local_state = "REJECTED_BUDGET"
                intent.updated_at = now_utc()
                self.db.commit()
                raise BudgetExceeded("buy exceeds Available Budget")
        intent.local_state = "SUBMITTING"
        intent.updated_at = now_utc()
        self.db.commit()
        log_event("ORDER_SUBMIT_STARTED", intent_id=intent.id, pair=intent.pair, side=intent.side)

    def ensure_submission_allowed(self) -> None:
        config = self.db.scalar(select(AgentConfig).with_for_update().limit(1))
        if config is None or config.emergency_stop:
            raise SubmissionBlocked("emergency stop is active")

    def complete_run(
        self, run_id: str, state: str, decision: str | None, rationale: str | None
    ) -> None:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            raise ValueError("agent run not found")
        run.result_state = state
        run.decision = decision
        run.rationale = rationale
        run.completed_at = now_utc()
        self.db.commit()

    def record_decision(
        self, run_id: str, decision: dict[str, Any], evidence: dict[str, Any]
    ) -> None:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            raise ValueError("agent run not found")
        run.decision = json.dumps(decision, default=str, sort_keys=True)
        run.rationale = str(decision.get("rationale", ""))
        run.evidence_timestamps = json.dumps(evidence, default=str, sort_keys=True)
        run.evidence_hash = self.content_hash({"evidence": run.evidence_timestamps})
        self.db.commit()
        log_event(
            "AGENT_DECISION_RECORDED",
            run_id=run_id,
            action=str(decision.get("action", "UNKNOWN")),
        )
