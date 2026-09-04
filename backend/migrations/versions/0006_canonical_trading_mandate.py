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
    op.execute(
        sa.text(
            "UPDATE mandate_versions "
            "SET entry_rules = trading_mandate "
            "WHERE trading_mandate IS NOT NULL "
            "AND COALESCE(TRIM(assets), '') = '' "
            "AND COALESCE(TRIM(entry_rules), '') = '' "
            "AND COALESCE(TRIM(sizing_rules), '') = '' "
            "AND COALESCE(TRIM(exit_rules), '') = ''"
        )
    )
    op.drop_column("mandate_versions", "trading_mandate")
