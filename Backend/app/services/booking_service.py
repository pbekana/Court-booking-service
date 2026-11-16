from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking


class BookingService:
    @staticmethod
    def get_by_id(db: Session, booking_id: UUID) -> Booking | None:
        return db.get(Booking, booking_id)

    @staticmethod
    def get_by_hold_id(db: Session, hold_id: UUID) -> Booking | None:
        return db.scalar(select(Booking).where(Booking.hold_id == hold_id))

    @staticmethod
    def get_user_bookings(db: Session, user_id: UUID) -> list[Booking]:
        stmt = (
            select(Booking)
            .where(Booking.user_id == user_id)
            .order_by(Booking.start_at.desc())
        )
        return list(db.scalars(stmt).all())
