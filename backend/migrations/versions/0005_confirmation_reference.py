"""Persist the opaque Codex confirmation reference."""

from alembic import op
import sqlalchemy as sa

revision = "0005_confirmation_reference"
down_revision = "0004_dual_execution_and_universe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trade_intents", sa.Column("confirmation_request_id", sa.String(128)))
    op.add_column("trade_intents", sa.Column("confirmation_expires_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("trade_intents", "confirmation_expires_at")
    op.drop_column("trade_intents", "confirmation_request_id")