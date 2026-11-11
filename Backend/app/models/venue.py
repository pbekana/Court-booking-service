import uuid
from datetime import datetime, time
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Time, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Venue(Base):
    __tablename__ = "venues"  # Replace with your exact table name (e.g., "facilities" or "clubs")

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    address: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    timezone: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default=text("'Africa/Addis_Ababa'"),
    )
    opening_time: Mapped[time] = mapped_column(
        Time(timezone=False), nullable=False
    )
    closing_time: Mapped[time] = mapped_column(
        Time(timezone=False), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
