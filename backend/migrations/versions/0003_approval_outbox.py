"""Add deterministic execution policy, approvals, and durable work outbox."""

import sqlalchemy as sa
from alembic import op

revision = "0003_approval_outbox"
down_revision = "0002_oauth_and_event_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mandate_versions",
        sa.Column("allowed_symbols", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "mandate_versions",
        sa.Column("max_order_notional", sa.Numeric(30, 12), nullable=False, server_default="1"),
    )
    op.add_column(
        "mandate_versions",
        sa.Column("max_open_actionable_intents", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "trade_intents", sa.Column("rationale", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "trade_intents",
        sa.Column("supporting_factors", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "trade_intents", sa.Column("risk_factors", sa.Text(), nullable=False, server_default="[]")
    )
    op.add_column(
        "trade_intents",
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "trade_intents",
        sa.Column("policy_evidence", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column("trade_intents", sa.Column("revalidation_evidence", sa.Text()))
    op.add_column("trade_intents", sa.Column("revalidation_failed_reason", sa.Text()))
    op.add_column("trade_intents", sa.Column("write_request_hash", sa.String(64)))
    op.add_column(
        "trade_intents", sa.Column("external_call_started_at", sa.DateTime(timezone=True))
    )
    op.create_table(
        "trade_intent_approvals",
        sa.Column("approval_id", sa.String(36), primary_key=True),
        sa.Column("intent_id", sa.String(36), nullable=False, unique=True),
        sa.Column("operator_user_id", sa.String(64), nullable=False),
        sa.Column("operator_chat_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_source", sa.String(16)),
        sa.Column("telegram_chat_id", sa.String(128)),
        sa.Column("telegram_message_id", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["intent_id"], ["trade_intents.id"]),
    )
    op.create_index(
        "ix_trade_intent_approvals_intent_id", "trade_intent_approvals", ["intent_id"], unique=True
    )
    op.create_index(
        "ix_trade_intent_approvals_expires_at", "trade_intent_approvals", ["expires_at"]
    )
    op.create_index("ix_trade_intent_approvals_status", "trade_intent_approvals", ["status"])
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dedupe_key", sa.String(255), nullable=False, unique=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outbox_messages_dedupe_key", "outbox_messages", ["dedupe_key"], unique=True)
    op.create_index("ix_outbox_messages_kind", "outbox_messages", ["kind"])
    op.create_index("ix_outbox_messages_aggregate_id", "outbox_messages", ["aggregate_id"])
    op.create_index("ix_outbox_messages_status", "outbox_messages", ["status"])
    op.create_index("ix_outbox_messages_available_at", "outbox_messages", ["available_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_messages_available_at", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_status", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_aggregate_id", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_kind", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_dedupe_key", table_name="outbox_messages")
    op.drop_table("outbox_messages")
    op.drop_index("ix_trade_intent_approvals_status", table_name="trade_intent_approvals")
    op.drop_index("ix_trade_intent_approvals_expires_at", table_name="trade_intent_approvals")
    op.drop_index("ix_trade_intent_approvals_intent_id", table_name="trade_intent_approvals")
    op.drop_table("trade_intent_approvals")
    op.drop_column("trade_intents", "external_call_started_at")
    op.drop_column("trade_intents", "write_request_hash")
    op.drop_column("trade_intents", "revalidation_failed_reason")
    op.drop_column("trade_intents", "revalidation_evidence")
    op.drop_column("trade_intents", "policy_evidence")
    op.drop_column("trade_intents", "confidence")
    op.drop_column("trade_intents", "risk_factors")
    op.drop_column("trade_intents", "supporting_factors")
    op.drop_column("trade_intents", "rationale")
    op.drop_column("mandate_versions", "max_open_actionable_intents")
    op.drop_column("mandate_versions", "max_order_notional")
    op.drop_column("mandate_versions", "allowed_symbols")
