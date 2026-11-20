"""create_refunds_table

Revision ID: a305ff6e6967
Revises: 90702aa288f3
Create Date: 2026-11-20 23:36:48.713971

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a305ff6e6967"
down_revision: str | Sequence[str] | None = "90702aa288f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "refunds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'ETB'"),
            nullable=False,
        ),
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("amount >= 0", name="refunds_amount_check"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED')",
            name="refunds_status_check",
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"], ["bookings.id"], name="refunds_booking_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name="refunds_payment_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="refunds_pkey"),
        sa.UniqueConstraint("idempotency_key", name="refunds_idempotency_key_key"),
    )
    op.create_index("idx_refunds_booking", "refunds", ["booking_id"], unique=False)
    op.create_index("idx_refunds_payment", "refunds", ["payment_id"], unique=False)
    op.create_index("idx_refunds_status", "refunds", ["status"], unique=False)
    op.create_index(
        "idx_refunds_booking_payment_success",
        "refunds",
        ["booking_id", "payment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SUCCESS'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "idx_refunds_booking_payment_success",
        table_name="refunds",
        postgresql_where=sa.text("status = 'SUCCESS'"),
    )
    op.drop_index("idx_refunds_status", table_name="refunds")
    op.drop_index("idx_refunds_payment", table_name="refunds")
    op.drop_index("idx_refunds_booking", table_name="refunds")
    op.drop_table("refunds")
