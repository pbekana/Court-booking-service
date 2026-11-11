import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Numeric,
    SmallInteger,
    String,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CourtPricing(Base):
    __tablename__ = "court_pricings"  # Replace with your exact table name

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    pricing_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    start_time: Mapped[time] = mapped_column(
        Time(timezone=False), nullable=False
    )
    end_time: Mapped[time] = mapped_column(
        Time(timezone=False), nullable=False
    )
    day_of_week: Mapped[Optional[int]] = mapped_column(
        SmallInteger, nullable=True
    )
    hourly_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'ETB'")
    )
    effective_from: Mapped[date] = mapped_column(
        Date, nullable=False
    )
    effective_until: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
