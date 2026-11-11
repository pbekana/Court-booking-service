import uuid
from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, SmallInteger, String, Time, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RecurringSchedule(Base):
    __tablename__ = "recurring_schedules"  # Replace with your exact table name

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    day_of_week: Mapped[int] = mapped_column(
        SmallInteger, nullable=False
    )
    start_time: Mapped[time] = mapped_column(
        Time(timezone=False), nullable=False
    )
    end_time: Mapped[time] = mapped_column(
        Time(timezone=False), nullable=False
    )
    recurrence_start_date: Mapped[date] = mapped_column(
        Date, nullable=False
    )
    recurrence_end_date: Mapped[date] = mapped_column(
        Date, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'ACTIVE'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
