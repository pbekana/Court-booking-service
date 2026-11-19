import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.hold import Hold


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="payments_amount_check"),
        CheckConstraint(
            "(booking_id IS NOT NULL AND hold_id IS NULL) OR (booking_id IS NULL AND hold_id IS NOT NULL)",
            name="payments_check",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'REFUND_PENDING', 'REFUNDED')",
            name="payments_status_check",
        ),
        UniqueConstraint("payment_reference", name="payments_payment_reference_key"),
        UniqueConstraint(
            "provider",
            "provider_transaction_id",
            name="payments_provider_provider_transaction_id_key",
        ),
        Index("idx_payments_booking", "booking_id"),
        Index("idx_payments_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bookings.id"),
        nullable=True,
    )
    hold_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("holds.id"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    payment_reference: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'ETB'"), default="ETB"
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'"),
        default=PaymentStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=datetime.now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=datetime.now,
        onupdate=func.now(),
    )

    booking: Mapped[Optional["Booking"]] = relationship(
        "Booking", back_populates="payments"
    )
    hold: Mapped[Optional["Hold"]] = relationship(
        "Hold", back_populates="payments"
    )
