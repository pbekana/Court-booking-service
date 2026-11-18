"""add_pricing_rule_is_active_and_relax_time_check

Revision ID: 90702aa288f3
Revises: fe107379e541
Create Date: 2026-11-18 22:56:32.943308

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "90702aa288f3"
down_revision: str | Sequence[str] | None = "fe107379e541"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "pricing_rules",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_pricing_rules_active",
        "pricing_rules",
        ["court_id", "is_active"],
        if_not_exists=True,
    )
    op.execute("ALTER TABLE pricing_rules DROP CONSTRAINT IF EXISTS pricing_rules_check;")
    op.execute(
        "ALTER TABLE pricing_rules ADD CONSTRAINT pricing_rules_check CHECK (start_time != end_time);"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE pricing_rules DROP CONSTRAINT IF EXISTS pricing_rules_check;")
    op.execute(
        "ALTER TABLE pricing_rules ADD CONSTRAINT pricing_rules_check CHECK (start_time < end_time);"
    )
    op.drop_index("idx_pricing_rules_active", table_name="pricing_rules", if_exists=True)
    op.drop_column("pricing_rules", "is_active")
