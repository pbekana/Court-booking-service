from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.booking_ocurrences import BookingOccurrence
from app.models.hold import Hold
from app.models.reservations import Reservation


class AvailabilityRepository:
    @staticmethod
    def has_conflicting_reservations(
        db: Session,
        court_id: UUID,
        start_at: datetime,
        end_at: datetime,
    ) -> bool:
        """Checks whether the requested interval conflicts with any active reservation,

        confirmed booking, active hold, or confirmed recurring booking occurrence.
        Interval convention is [start_at, end_at) so adjacent intervals do not overlap.
        """
        now = datetime.now(UTC)

        # 1. Check reservations table (central source of truth)
        stmt_res = (
            select(Reservation.id)
            .where(
                Reservation.court_id == court_id,
                or_(
                    Reservation.status == "CONFIRMED",
                    and_(
                        Reservation.status == "HELD",
                        Reservation.expires_at > now,
                    ),
                ),
                Reservation.start_at < end_at,
                Reservation.end_at > start_at,
            )
            .limit(1)
        )
        if db.scalar(stmt_res) is not None:
            return True

        # 2. Check bookings table
        stmt_booking = (
            select(Booking.id)
            .where(
                Booking.court_id == court_id,
                Booking.status == "CONFIRMED",
                Booking.start_at < end_at,
                Booking.end_at > start_at,
            )
            .limit(1)
        )
        if db.scalar(stmt_booking) is not None:
            return True

        # 3. Check holds table
        stmt_hold = (
            select(Hold.id)
            .where(
                Hold.court_id == court_id,
                Hold.status.in_(["ACTIVE", "HELD"]),
                Hold.expires_at > now,
                Hold.start_time < end_at,
                Hold.end_time > start_at,
            )
            .limit(1)
        )
        if db.scalar(stmt_hold) is not None:
            return True

        # 4. Check recurring booking occurrences
        stmt_occ = (
            select(BookingOccurrence.id)
            .join(Booking, BookingOccurrence.booking_id == Booking.id)
            .where(
                Booking.court_id == court_id,
                BookingOccurrence.status == "CONFIRMED",
                Booking.status == "CONFIRMED",
                Booking.start_at < end_at,
                Booking.end_at > start_at,
            )
            .limit(1)
        )
        return db.scalar(stmt_occ) is not None
