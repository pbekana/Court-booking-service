"""add_hold_fields_and_constraints

Revision ID: fe107379e541
Revises: 
Create Date: 2026-11-17 00:51:09.908916

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fe107379e541"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Ensure btree_gist extension is available for exclusion constraints
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # 2. Add court_id, start_time, end_time to holds
    op.add_column("holds", sa.Column("court_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("courts.id"), nullable=True))
    op.add_column("holds", sa.Column("start_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("holds", sa.Column("end_time", sa.DateTime(timezone=True), nullable=True))

    # Allow reservation_id to be nullable in holds
    op.alter_column("holds", "reservation_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)

    # Update status check constraint to include 'ACTIVE'
    op.execute("ALTER TABLE holds DROP CONSTRAINT IF EXISTS holds_status_check;")
    op.execute("ALTER TABLE holds ADD CONSTRAINT holds_status_check CHECK (status IN ('ACTIVE', 'HELD', 'CONFIRMED', 'EXPIRED', 'CANCELLED'));")
    op.execute("ALTER TABLE holds ALTER COLUMN status SET DEFAULT 'ACTIVE';")

    # Add time range check constraint
    op.execute("ALTER TABLE holds DROP CONSTRAINT IF EXISTS holds_time_check;")
    op.execute("ALTER TABLE holds ADD CONSTRAINT holds_time_check CHECK (end_time > start_time);")

    # Add exclusion constraint to prevent overlapping active holds on the same court
    op.execute("ALTER TABLE holds DROP CONSTRAINT IF EXISTS holds_court_id_tstzrange_excl;")
    op.execute(
        "ALTER TABLE holds ADD CONSTRAINT holds_court_id_tstzrange_excl "
        "EXCLUDE USING gist (court_id WITH =, tstzrange(start_time, end_time, '[)') WITH &&) "
        "WHERE (status = 'ACTIVE');"
    )

    # Add indexes on holds
    op.create_index("idx_holds_court", "holds", ["court_id"], if_not_exists=True)
    op.create_index("idx_holds_court_times", "holds", ["court_id", "start_time", "end_time"], if_not_exists=True)

    # 3. Bookings table modifications
    op.alter_column("bookings", "reservation_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_court_id_tstzrange_excl;")
    op.execute(
        "ALTER TABLE bookings ADD CONSTRAINT bookings_court_id_tstzrange_excl "
        "EXCLUDE USING gist (court_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&) "
        "WHERE (status = 'CONFIRMED');"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_court_id_tstzrange_excl;")
    op.alter_column("bookings", "reservation_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    op.drop_index("idx_holds_court_times", table_name="holds", if_exists=True)
    op.drop_index("idx_holds_court", table_name="holds", if_exists=True)
    op.execute("ALTER TABLE holds DROP CONSTRAINT IF EXISTS holds_court_id_tstzrange_excl;")
    op.execute("ALTER TABLE holds DROP CONSTRAINT IF EXISTS holds_time_check;")
    op.execute("ALTER TABLE holds DROP CONSTRAINT IF EXISTS holds_status_check;")
    op.execute("ALTER TABLE holds ADD CONSTRAINT holds_status_check CHECK (status IN ('HELD', 'CONFIRMED', 'EXPIRED', 'CANCELLED'));")
    op.execute("ALTER TABLE holds ALTER COLUMN status SET DEFAULT 'HELD';")
    op.alter_column("holds", "reservation_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("holds", "end_time")
    op.drop_column("holds", "start_time")
    op.drop_column("holds", "court_id")
