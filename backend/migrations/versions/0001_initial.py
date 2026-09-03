"""Create DarwinSpot durable state tables."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "owner_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_owner_sessions_token_hash", "owner_sessions", ["token_hash"], unique=True)
    op.create_table(
        "binance_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_reference", sa.String(128)),
        sa.Column("encrypted_material", sa.Text),
        sa.Column("capabilities", sa.Text, nullable=False, server_default="[]"),
        sa.Column("state", sa.String(32), nullable=False, server_default="DISCONNECTED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.Column("disconnected_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "agent_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mode", sa.String(32), nullable=False, server_default="READ_ONLY"),
        sa.Column("active_mandate_version", sa.String(36)),
        sa.Column("schedule_interval", sa.Integer, nullable=False, server_default="300"),
        sa.Column("state", sa.String(32), nullable=False, server_default="DISCONNECTED"),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("emergency_stop", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "mandate_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("assets", sa.Text, nullable=False),
        sa.Column("entry_rules", sa.Text, nullable=False),
        sa.Column("sizing_rules", sa.Text, nullable=False),
        sa.Column("exit_rules", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
    )
    op.create_table(
        "budget_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("daily_budget", sa.Numeric(30, 12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("budget_hash", sa.String(64), nullable=False),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("mandate_version", sa.String(36)),
        sa.Column("budget_version", sa.String(36)),
        sa.Column("evidence_timestamps", sa.Text, nullable=False, server_default="[]"),
        sa.Column("evidence_hash", sa.String(64)),
        sa.Column("decision", sa.Text),
        sa.Column("rationale", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("result_state", sa.String(32), nullable=False, server_default="STARTED"),
    )
    op.create_table(
        "trade_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(36), nullable=False, unique=True),
        sa.Column("agent_run_id", sa.String(36), nullable=False),
        sa.Column("pair", sa.String(20), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 12), nullable=False),
        sa.Column("quote_notional", sa.Numeric(30, 12)),
        sa.Column("price", sa.Numeric(30, 12)),
        sa.Column("budget_result", sa.String(32), nullable=False),
        sa.Column("committed_notional", sa.Numeric(30, 12)),
        sa.Column("binance_order_id", sa.String(128)),
        sa.Column("local_state", sa.String(32), nullable=False, server_default="PROPOSED"),
        sa.Column("exchange_state", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trade_intents_idempotency_key", "trade_intents", ["idempotency_key"], unique=True)
    op.create_table(
        "order_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("intent_id", sa.String(36), nullable=False),
        sa.Column("upstream_event_type", sa.String(64), nullable=False),
        sa.Column("filled_quantity", sa.Numeric(30, 12)),
        sa.Column("filled_notional", sa.Numeric(30, 12)),
        sa.Column("fee", sa.Numeric(30, 12)),
        sa.Column("exchange_timestamp", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("sanitized_evidence", sa.Text, nullable=False),
    )
    op.create_index("ix_order_events_intent_id", "order_events", ["intent_id"])


def downgrade() -> None:
    op.drop_index("ix_order_events_intent_id", table_name="order_events")
    op.drop_table("order_events")
    op.drop_index("ix_trade_intents_idempotency_key", table_name="trade_intents")
    op.drop_table("trade_intents")
    op.drop_table("agent_runs")
    op.drop_table("budget_versions")
    op.drop_table("mandate_versions")
    op.drop_table("agent_configs")
    op.drop_table("binance_connections")
    op.drop_index("ix_owner_sessions_token_hash", table_name="owner_sessions")
    op.drop_table("owner_sessions")
