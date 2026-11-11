import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Payment(Base):
    __tablename__ = "payments"  # Replace with your exact table name if different

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    booking_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    hold_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    provider_transaction_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    payment_reference: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'ETB'")
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'PENDING'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
