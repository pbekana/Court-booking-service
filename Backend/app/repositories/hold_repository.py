from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.hold import Hold
from app.models.reservations import Reservation


class HoldRepository:
    @staticmethod
    def get_by_id(db: Session, hold_id: UUID) -> Hold | None:
        return db.get(Hold, hold_id)

    @staticmethod
    def get_by_id_for_update(db: Session, hold_id: UUID) -> Hold | None:
        stmt = (
            select(Hold)
            .where(Hold.id == hold_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return db.scalar(stmt)

    @staticmethod
    def get_by_idempotency_key(
        db: Session, user_id: UUID, idempotency_key: str
    ) -> Hold | None:
        stmt = select(Hold).where(
            Hold.user_id == user_id,
            Hold.idempotency_key == idempotency_key,
        )
        return db.scalar(stmt)

    @staticmethod
    def has_conflicting_booking(
        db: Session, court_id: UUID, start_time: datetime, end_time: datetime
    ) -> bool:
        # Check bookings table
        stmt_booking = (
            select(Booking.id)
            .where(
                Booking.court_id == court_id,
                Booking.status == "CONFIRMED",
                Booking.start_at < end_time,
                Booking.end_at > start_time,
            )
            .limit(1)
        )
        if db.scalar(stmt_booking) is not None:
            return True

        # Check reservations table for confirmed reservations
        stmt_reservation = (
            select(Reservation.id)
            .where(
                Reservation.court_id == court_id,
                Reservation.status == "CONFIRMED",
                Reservation.start_at < end_time,
                Reservation.end_at > start_time,
            )
            .limit(1)
        )
        return db.scalar(stmt_reservation) is not None

    @staticmethod
    def has_conflicting_hold(
        db: Session,
        court_id: UUID,
        start_time: datetime,
        end_time: datetime,
        exclude_hold_id: UUID | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        stmt = select(Hold.id).where(
            Hold.court_id == court_id,
            Hold.status.in_(["ACTIVE", "HELD"]),
            Hold.expires_at > now,
            Hold.start_time < end_time,
            Hold.end_time > start_time,
        )
        if exclude_hold_id is not None:
            stmt = stmt.where(Hold.id != exclude_hold_id)

        if db.scalar(stmt.limit(1)) is not None:
            return True

        # Also check reservations table for active held reservations
        stmt_res = select(Reservation.id).where(
            Reservation.court_id == court_id,
            Reservation.status == "HELD",
            Reservation.expires_at > now,
            Reservation.start_at < end_time,
            Reservation.end_at > start_time,
        )
        return db.scalar(stmt_res.limit(1)) is not None

    @staticmethod
    def expire_stale_holds(db: Session, court_id: UUID | None = None) -> int:
        now = datetime.now(UTC)
        stmt = (
            update(Hold)
            .where(
                Hold.status.in_(["ACTIVE", "HELD"]),
                Hold.expires_at <= now,
            )
            .values(status="EXPIRED")
        )
        if court_id is not None:
            stmt = stmt.where(Hold.court_id == court_id)

        result = db.execute(stmt)

        res_stmt = (
            update(Reservation)
            .where(
                Reservation.status == "HELD",
                Reservation.expires_at <= now,
            )
            .values(status="EXPIRED", expires_at=None)
        )
        if court_id is not None:
            res_stmt = res_stmt.where(Reservation.court_id == court_id)
        res_result = db.execute(res_stmt)

        hold_count = getattr(result, "rowcount", 0) or 0
        res_count = getattr(res_result, "rowcount", 0) or 0
        return max(int(hold_count), int(res_count))

    @staticmethod
    def create(
        db: Session, hold: Hold, reservation: Reservation | None = None
    ) -> Hold:
        if reservation is not None:
            db.add(reservation)
            db.flush()
            hold.reservation_id = reservation.id
        db.add(hold)
        db.flush()
        return hold
