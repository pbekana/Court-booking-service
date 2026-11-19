import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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
    from app.models.court import Court
    from app.models.payment import Payment
    from app.models.reservations import Reservation
    from app.models.user import User


class HoldStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    HELD = "HELD"


class Hold(Base):
    __tablename__ = "holds"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="holds_time_check"),
        CheckConstraint(
            "status IN ('ACTIVE', 'HELD', 'CONFIRMED', 'EXPIRED', 'CANCELLED')",
            name="holds_status_check",
        ),
        UniqueConstraint("user_id", "idempotency_key", name="holds_user_id_idempotency_key_key"),
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
        unique=True,
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
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ACTIVE",
        server_default=text("'ACTIVE'"),
        index=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.now,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship("User")
    court: Mapped["Court"] = relationship("Court")
    booking: Mapped[Optional["Booking"]] = relationship(
        "Booking",
        back_populates="hold",
        uselist=False,
    )
    reservation: Mapped[Optional["Reservation"]] = relationship("Reservation")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="hold")

    @property
    def payment(self) -> Optional["Payment"]:
        return self.payments[0] if self.payments else None
