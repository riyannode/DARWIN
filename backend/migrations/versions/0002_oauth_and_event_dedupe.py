"""Persist OAuth flow state and enforce order-event deduplication."""

from alembic import op
import sqlalchemy as sa

revision = "0002_oauth_and_event_dedupe"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("binance_connections", sa.Column("oauth_state", sa.String(128)))
    op.add_column("binance_connections", sa.Column("oauth_code", sa.Text()))
    op.add_column("binance_connections", sa.Column("oauth_iss", sa.String(256)))
    op.add_column("binance_connections", sa.Column("oauth_error", sa.Text()))
    op.create_index(
        "uq_order_events_intent_payload",
        "order_events",
        ["intent_id", "payload_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_order_events_intent_payload", table_name="order_events")
    op.drop_column("binance_connections", "oauth_error")
    op.drop_column("binance_connections", "oauth_iss")
    op.drop_column("binance_connections", "oauth_code")
    op.drop_column("binance_connections", "oauth_state")
