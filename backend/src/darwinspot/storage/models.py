from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OwnerSession(Base):
    __tablename__ = "owner_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BinanceConnection(Base):
    __tablename__ = "binance_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_reference: Mapped[str | None] = mapped_column(String(128))
    encrypted_material: Mapped[str | None] = mapped_column(Text)
    capabilities: Mapped[str] = mapped_column(Text, default="[]")
    state: Mapped[str] = mapped_column(String(32), default="DISCONNECTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oauth_state: Mapped[str | None] = mapped_column(String(128))
    oauth_code: Mapped[str | None] = mapped_column(Text)
    oauth_iss: Mapped[str | None] = mapped_column(String(256))
    oauth_error: Mapped[str | None] = mapped_column(Text)


class AgentConfig(Base):
    __tablename__ = "agent_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), default="HUMAN_APPROVAL")
    supported_symbols: Mapped[str] = mapped_column(
        Text, default='["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]'
    )
    active_mandate_version: Mapped[str | None] = mapped_column(String(36))
    schedule_interval: Mapped[int] = mapped_column(default=300)
    state: Mapped[str] = mapped_column(String(32), default="DISCONNECTED")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False)


class MandateVersion(Base):
    __tablename__ = "mandate_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trading_mandate: Mapped[str | None] = mapped_column(Text, nullable=True)
    assets: Mapped[str] = mapped_column(Text)
    entry_rules: Mapped[str] = mapped_column(Text)
    sizing_rules: Mapped[str] = mapped_column(Text)
    exit_rules: Mapped[str] = mapped_column(Text)
    allowed_symbols: Mapped[str] = mapped_column(Text, default="[]")
    max_order_notional: Mapped[Decimal] = mapped_column(Numeric(30, 12), default=Decimal("1"))
    max_open_actionable_intents: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))


class BudgetVersion(Base):
    __tablename__ = "budget_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    daily_budget: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    budget_hash: Mapped[str] = mapped_column(String(64))


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trigger_type: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    mandate_version: Mapped[str | None] = mapped_column(String(36))
    budget_version: Mapped[str | None] = mapped_column(String(36))
    evidence_timestamps: Mapped[str] = mapped_column(Text, default="[]")
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    decision: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_state: Mapped[str] = mapped_column(String(32), default="STARTED")


class TradeIntent(Base):
    __tablename__ = "trade_intents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    agent_run_id: Mapped[str] = mapped_column(String(36))
    pair: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    quote_notional: Mapped[Decimal | None] = mapped_column(Numeric(30, 12))
    price: Mapped[Decimal | None] = mapped_column(Numeric(30, 12))
    budget_result: Mapped[str] = mapped_column(String(32))
    committed_notional: Mapped[Decimal | None] = mapped_column(Numeric(30, 12))
    binance_order_id: Mapped[str | None] = mapped_column(String(128))
    local_state: Mapped[str] = mapped_column(String(32), default="PROPOSED")
    exchange_state: Mapped[str | None] = mapped_column(String(32))
    rationale: Mapped[str] = mapped_column(Text, default="")
    supporting_factors: Mapped[str] = mapped_column(Text, default="[]")
    risk_factors: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    policy_evidence: Mapped[str] = mapped_column(Text, default="{}")
    revalidation_evidence: Mapped[str | None] = mapped_column(Text)
    revalidation_failed_reason: Mapped[str | None] = mapped_column(Text)
    write_request_hash: Mapped[str | None] = mapped_column(String(64))
    external_call_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_mode: Mapped[str] = mapped_column(String(32), default="HUMAN_APPROVAL")
    execution_transport: Mapped[str] = mapped_column(String(32), default="CODEX_AGENT_OS_MCP")
    authorization_source: Mapped[str | None] = mapped_column(String(32))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_request_id: Mapped[str | None] = mapped_column(String(128))
    confirmation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderEvent(Base):
    __tablename__ = "order_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(36), index=True)
    upstream_event_type: Mapped[str] = mapped_column(String(64))
    filled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(30, 12))
    filled_notional: Mapped[Decimal | None] = mapped_column(Numeric(30, 12))
    fee: Mapped[Decimal | None] = mapped_column(Numeric(30, 12))
    exchange_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_hash: Mapped[str] = mapped_column(String(64))
    sanitized_evidence: Mapped[str] = mapped_column(Text)


class TradeIntentApproval(Base):
    __tablename__ = "trade_intent_approvals"

    approval_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    operator_user_id: Mapped[str] = mapped_column(String(64))
    operator_chat_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_source: Mapped[str | None] = mapped_column(String(16))
    telegram_chat_id: Mapped[str | None] = mapped_column(String(128))
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
