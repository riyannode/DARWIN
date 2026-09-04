"""Add the canonical Trading Mandate field."""

import sqlalchemy as sa
from alembic import op

revision = "0006_canonical_trading_mandate"
down_revision = "0005_confirmation_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mandate_versions",
        sa.Column("trading_mandate", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mandate_versions", "trading_mandate")
