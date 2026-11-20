import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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
    from app.models.court import Court
    from app.models.hold import Hold
    from app.models.payment import Payment
    from app.models.refund import Refund
    from app.models.reservations import Reservation
    from app.models.user import User


class BookingStatus(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="bookings_check"),
        CheckConstraint("total_price >= 0", name="bookings_total_price_check"),
        CheckConstraint(
            "status IN ('CONFIRMED', 'CANCELLED')",
            name="bookings_status_check",
        ),
        UniqueConstraint("hold_id", name="bookings_hold_id_key"),
        UniqueConstraint("reservation_id", name="bookings_reservation_id_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reservations.id"),
        nullable=True,
    )
    hold_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("holds.id"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courts.id"),
        nullable=False,
        index=True,
    )
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    total_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="ETB",
        server_default=text("'ETB'"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="CONFIRMED",
        server_default=text("'CONFIRMED'"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.now,
        server_default=func.now(),
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    hold: Mapped["Hold"] = relationship("Hold", back_populates="booking")
    court: Mapped["Court"] = relationship("Court")
    user: Mapped["User"] = relationship("User")
    reservation: Mapped[Optional["Reservation"]] = relationship("Reservation")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="booking")
    refunds: Mapped[list["Refund"]] = relationship("Refund", back_populates="booking")

    @property
    def payment(self) -> Optional["Payment"]:
        return self.payments[0] if self.payments else None

    @property
    def refund(self) -> Optional["Refund"]:
        return self.refunds[0] if self.refunds else None
