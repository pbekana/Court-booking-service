from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.orm import Session

from app.models.hold import Hold
from app.models.reservations import Reservation
from app.models.user import User
from app.schemas.booking_limit import (
    ActiveReservationInfo,
    BookingLimitData,
    BookingLimitResponse,
)

MAX_ACTIVE_FUTURE_BOOKINGS = 3


class BookingLimitExceededException(HTTPException):
    def __init__(
        self,
        active_bookings: int,
        booking_limit: int = MAX_ACTIVE_FUTURE_BOOKINGS,
        message: str | None = None,
    ):
        msg = (
            message
            or f"You have reached the maximum limit of {booking_limit} active future bookings."
        )
        self.active_bookings = active_bookings
        self.booking_limit = booking_limit
        self.remaining_bookings = max(0, booking_limit - active_bookings)
        payload = {
            "success": False,
            "message": msg,
            "detail": msg,
            "data": {
                "booking_limit": booking_limit,
                "active_bookings": active_bookings,
                "remaining_bookings": self.remaining_bookings,
            },
        }
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=payload,
        )


class BookingLimitService:
    @staticmethod
    def acquire_member_lock(db: Session, user_id: UUID) -> None:
        """Serializes booking operations for the specific member using PostgreSQL row locking

        and transaction-scoped advisory locks.
        """
        # 1. Row-level lock on the users table
        db.execute(select(User.id).where(User.id == user_id).with_for_update())

        # 2. Transaction-scoped PostgreSQL advisory lock (released on commit/rollback)
        lock_id = user_id.int & 0x7FFFFFFFFFFFFFFF
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": lock_id},
        )

    @staticmethod
    def expire_stale_member_holds(db: Session, user_id: UUID) -> None:
        """Transitions any outdated holds and reservations belonging to this member to EXPIRED."""
        now = datetime.now(UTC)

        # Expire stale holds
        db.execute(
            update(Hold)
            .where(
                Hold.user_id == user_id,
                Hold.status.in_(["ACTIVE", "HELD"]),
                Hold.expires_at <= now,
            )
            .values(status="EXPIRED")
        )

        # Expire stale reservations
        db.execute(
            update(Reservation)
            .where(
                Reservation.user_id == user_id,
                Reservation.status == "HELD",
                Reservation.expires_at <= now,
            )
            .values(status="EXPIRED", expires_at=None)
        )

    @staticmethod
    def get_active_future_reservations(
        db: Session,
        user_id: UUID,
        exclude_reservation_id: UUID | None = None,
    ) -> list[Reservation]:
        """Returns all active future reservations for the member from the central reservations table.

        Counts:
        1. Confirmed reservations whose end time is still in the future.
        2. Active unexpired temporary holds (HELD) whose expiration time is still in the future.
        Excludes cancelled, expired, and past reservations.
        """
        now = datetime.now(UTC)
        stmt = select(Reservation).where(
            Reservation.user_id == user_id,
            or_(
                and_(
                    Reservation.status == "HELD",
                    Reservation.expires_at > now,
                ),
                and_(
                    Reservation.status == "CONFIRMED",
                    Reservation.end_at > now,
                ),
            ),
        )
        if exclude_reservation_id is not None:
            stmt = stmt.where(Reservation.id != exclude_reservation_id)

        stmt = stmt.order_by(Reservation.start_at.asc())
        return list(db.scalars(stmt).all())

    @staticmethod
    def count_active_future_reservations(
        db: Session,
        user_id: UUID,
        exclude_reservation_id: UUID | None = None,
    ) -> int:
        return len(
            BookingLimitService.get_active_future_reservations(
                db=db,
                user_id=user_id,
                exclude_reservation_id=exclude_reservation_id,
            )
        )

    @staticmethod
    def enforce_booking_limit(
        db: Session,
        user_id: UUID,
        additional_count: int = 1,
        exclude_reservation_id: UUID | None = None,
    ) -> int:
        """Enforces that member cannot exceed 3 active future reservations.

        Must be called within a transaction after acquiring member lock.
        """
        BookingLimitService.acquire_member_lock(db, user_id)
        BookingLimitService.expire_stale_member_holds(db, user_id)

        current_active = BookingLimitService.count_active_future_reservations(
            db=db,
            user_id=user_id,
            exclude_reservation_id=exclude_reservation_id,
        )

        if current_active + additional_count > MAX_ACTIVE_FUTURE_BOOKINGS:
            raise BookingLimitExceededException(
                active_bookings=current_active,
                booking_limit=MAX_ACTIVE_FUTURE_BOOKINGS,
            )

        return current_active

    @staticmethod
    def get_member_booking_limit_status(
        db: Session,
        user_id: UUID,
    ) -> BookingLimitResponse:
        """Returns the authenticated member's booking limit status."""
        BookingLimitService.expire_stale_member_holds(db, user_id)
        active_reservations = BookingLimitService.get_active_future_reservations(
            db=db,
            user_id=user_id,
        )
        active_count = len(active_reservations)

        return BookingLimitResponse(
            success=True,
            data=BookingLimitData(
                booking_limit=MAX_ACTIVE_FUTURE_BOOKINGS,
                active_bookings=active_count,
                remaining_bookings=max(0, MAX_ACTIVE_FUTURE_BOOKINGS - active_count),
                active_reservations=[
                    ActiveReservationInfo.model_validate(r)
                    for r in active_reservations
                ],
            ),
        )
