"""Add explicit execution modes and persisted Spot universe configuration."""

from alembic import op
import sqlalchemy as sa

revision = "0004_dual_execution_and_universe"
down_revision = "0003_approval_outbox"
branch_labels = None
depends_on = None


_DEFAULT_SYMBOLS = '["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]'


def upgrade() -> None:
    op.add_column(
        "agent_configs",
        sa.Column("supported_symbols", sa.Text(), nullable=False, server_default=_DEFAULT_SYMBOLS),
    )
    op.add_column(
        "trade_intents",
        sa.Column("execution_mode", sa.String(32), nullable=False, server_default="HUMAN_APPROVAL"),
    )
    op.add_column(
        "trade_intents",
        sa.Column(
            "execution_transport",
            sa.String(32),
            nullable=False,
            server_default="CODEX_AGENT_OS_MCP",
        ),
    )
    op.add_column("trade_intents", sa.Column("authorization_source", sa.String(32)))
    op.add_column("trade_intents", sa.Column("authorized_at", sa.DateTime(timezone=True)))
    op.execute(
        sa.text(
            "UPDATE agent_configs SET mode = 'HUMAN_APPROVAL' "
            "WHERE mode IN ('READ_ONLY', 'APPROVAL_REQUIRED')"
        )
    )


def downgrade() -> None:
    op.drop_column("trade_intents", "authorized_at")
    op.drop_column("trade_intents", "authorization_source")
    op.drop_column("trade_intents", "execution_transport")
    op.drop_column("trade_intents", "execution_mode")
    op.drop_column("agent_configs", "supported_symbols")
