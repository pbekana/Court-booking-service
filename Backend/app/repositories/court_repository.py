from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload

from app.models.court import Court
from app.models.reservations import Reservation
from app.schemas.court import CourtCreate


class CourtRepository:
    @staticmethod
    def get_by_id(db: Session, court_id: UUID) -> Court | None:
        return db.get(Court, court_id)

    @staticmethod
    def get_by_id_with_venue(db: Session, court_id: UUID) -> Court | None:
        stmt = (
            select(Court)
            .options(joinedload(Court.venue))
            .where(Court.id == court_id)
        )
        return db.scalar(stmt)

    @staticmethod
    def get_by_venue_and_name(
        db: Session, venue_id: UUID, name: str, exclude_id: Optional[UUID] = None
    ) -> Court | None:
        stmt = select(Court).where(
            Court.venue_id == venue_id,
            func.lower(Court.name) == func.lower(name.strip()),
        )
        if exclude_id is not None:
            stmt = stmt.where(Court.id != exclude_id)
        return db.scalar(stmt)

    @staticmethod
    def get_all(
        db: Session,
        venue_id: Optional[UUID] = None,
        sport_type: Optional[str] = None,
        is_active_only: bool = True,
    ) -> list[Court]:
        stmt = select(Court)
        if is_active_only:
            stmt = stmt.where(Court.is_active.is_(True))
        if venue_id is not None:
            stmt = stmt.where(Court.venue_id == venue_id)
        if sport_type is not None:
            stmt = stmt.where(func.lower(Court.sport_type) == func.lower(sport_type.strip()))
        stmt = stmt.order_by(Court.name.asc())
        return list(db.scalars(stmt).all())

    @staticmethod
    def create(db: Session, court_in: CourtCreate) -> Court:
        court = Court(
            venue_id=court_in.venue_id,
            name=court_in.name.strip(),
            sport_type=court_in.sport_type.strip(),
            is_active=True,
        )
        db.add(court)
        db.commit()
        db.refresh(court)
        return court

    @staticmethod
    def update(db: Session, court: Court, update_data: dict[str, Any]) -> Court:
        for field, value in update_data.items():
            setattr(court, field, value)
        db.commit()
        db.refresh(court)
        return court

    @staticmethod
    def deactivate(db: Session, court: Court) -> Court:
        court.is_active = False
        db.commit()
        db.refresh(court)
        return court

    @staticmethod
    def has_active_future_reservations(db: Session, court_id: UUID) -> bool:
        now = datetime.now(UTC)

        reservation_exists = db.scalar(
            select(Reservation.id)
            .where(
                Reservation.court_id == court_id,
                Reservation.end_at > now,
                Reservation.status.in_(["HELD", "CONFIRMED"]),
            )
            .limit(1)
        )
        if reservation_exists is not None:
            return True

        try:
            booking_check = db.execute(
                text(
                    """
                    SELECT 1 FROM bookings
                    WHERE court_id = :court_id
                      AND end_at > :now
                      AND status = 'CONFIRMED'
                    LIMIT 1
                    """
                ),
                {"court_id": court_id, "now": now},
            ).first()
            if booking_check is not None:
                return True
        except Exception:
            pass

        return False
