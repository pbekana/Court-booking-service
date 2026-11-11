import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Booking(Base):  # Replace 'Booking' with your actual table name
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    hold_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'ETB'")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'CONFIRMED'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
