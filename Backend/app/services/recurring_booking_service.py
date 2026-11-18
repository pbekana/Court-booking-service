from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.booking_ocurrences import BookingOccurrence
from app.models.court import Court
from app.models.hold import Hold
from app.models.recurring_series import RecurringSeries
from app.models.reservations import Reservation
from app.models.user import User
from app.repositories.availability_repository import AvailabilityRepository
from app.repositories.court_repository import CourtRepository
from app.repositories.pricing_repository import PricingRepository
from app.repositories.venue_repository import VenueRepository
from app.schemas.recurring_series import RecurringSeriesCreate
from app.services.booking_limit_service import (
    MAX_ACTIVE_FUTURE_BOOKINGS,
    BookingLimitExceededException,
    BookingLimitService,
)
from app.services.pricing_service import PricingService


class RecurringBookingService:
    @staticmethod
    def create_recurring_series(
        db: Session,
        user_id: UUID,
        series_in: RecurringSeriesCreate,
    ) -> RecurringSeries:
        # 1. Acquire concurrency lock on the member
        BookingLimitService.acquire_member_lock(db, user_id)
        BookingLimitService.expire_stale_member_holds(db, user_id)

        # 2. Verify court exists and is active
        court = CourtRepository.get_by_id_with_venue(db, series_in.court_id)
        if court is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Court not found",
            )
        if not court.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Court is inactive",
            )

        venue = court.venue
        if venue is None and court.venue_id is not None:
            venue = VenueRepository.get_by_id(db, court.venue_id)
        if venue is None or not venue.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot book court in an inactive venue",
            )

        try:
            venue_tz = (
                ZoneInfo(venue.timezone)
                if venue.timezone
                else ZoneInfo("Africa/Addis_Ababa")
            )
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            venue_tz = ZoneInfo("Africa/Addis_Ababa")

        # 3. Compute future occurrences
        now = datetime.now(UTC)
        future_occurrences: list[tuple[date, datetime, datetime]] = []

        cur_date = series_in.recurrence_start_date
        while cur_date <= series_in.recurrence_end_date:
            if cur_date.weekday() == series_in.day_of_week:
                occ_start_local = datetime.combine(
                    cur_date, series_in.start_time, tzinfo=venue_tz
                )
                occ_end_local = datetime.combine(
                    cur_date, series_in.end_time, tzinfo=venue_tz
                )
                occ_start_utc = occ_start_local.astimezone(UTC)
                occ_end_utc = occ_end_local.astimezone(UTC)

                if occ_start_utc > now:
                    future_occurrences.append(
                        (cur_date, occ_start_utc, occ_end_utc)
                    )

            cur_date += timedelta(days=1)

        if not future_occurrences:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No future occurrences found in the requested recurrence date range",
            )

        # 4. Enforce member booking limit across all requested future occurrences
        current_active = BookingLimitService.count_active_future_reservations(
            db=db,
            user_id=user_id,
        )
        if current_active + len(future_occurrences) > MAX_ACTIVE_FUTURE_BOOKINGS:
            raise BookingLimitExceededException(
                active_bookings=current_active,
                booking_limit=MAX_ACTIVE_FUTURE_BOOKINGS,
                message=f"Requested {len(future_occurrences)} recurring bookings would exceed the maximum limit of {MAX_ACTIVE_FUTURE_BOOKINGS} active future bookings.",
            )

        # 5. Lock court row during availability checks and creation
        db.execute(
            select(Court.id)
            .where(Court.id == series_in.court_id)
            .with_for_update()
        ).first()

        # 6. Validate availability for every occurrence
        for occ_date, occ_start, occ_end in future_occurrences:
            if AvailabilityRepository.has_conflicting_reservations(
                db=db,
                court_id=series_in.court_id,
                start_at=occ_start,
                end_at=occ_end,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Court is not available on {occ_date.isoformat()} for the requested recurring slot",
                )

        # 7. Create RecurringSeries and occurrences transactionally
        series = RecurringSeries(
            user_id=user_id,
            court_id=series_in.court_id,
            day_of_week=series_in.day_of_week,
            start_time=series_in.start_time,
            end_time=series_in.end_time,
            recurrence_start_date=series_in.recurrence_start_date,
            recurrence_end_date=series_in.recurrence_end_date,
            status="ACTIVE",
        )
        db.add(series)
        db.flush()

        has_rules = PricingRepository.court_has_any_rules(db, series_in.court_id)

        for occ_date, occ_start, occ_end in future_occurrences:
            total_price = Decimal("0.00")
            currency = "ETB"
            if has_rules:
                pricing = PricingService.calculate_pricing(
                    db=db,
                    court_id=series_in.court_id,
                    start_at=occ_start,
                    end_at=occ_end,
                    venue=venue,
                )
                total_price = pricing.total_price
                currency = pricing.currency

            res = Reservation(
                user_id=user_id,
                court_id=series_in.court_id,
                start_at=occ_start,
                end_at=occ_end,
                status="CONFIRMED",
                expires_at=None,
            )
            db.add(res)
            db.flush()

            hold = Hold(
                user_id=user_id,
                court_id=series_in.court_id,
                start_time=occ_start,
                end_time=occ_end,
                expires_at=occ_start,
                status="CONFIRMED",
                reservation_id=res.id,
            )
            db.add(hold)
            db.flush()

            booking = Booking(
                hold_id=hold.id,
                reservation_id=res.id,
                user_id=user_id,
                court_id=series_in.court_id,
                start_at=occ_start,
                end_at=occ_end,
                total_price=total_price,
                currency=currency,
                status="CONFIRMED",
            )
            db.add(booking)
            db.flush()

            occurrence = BookingOccurrence(
                recurring_series_id=series.id,
                booking_id=booking.id,
                occurrence_date=occ_date,
                status="CONFIRMED",
            )
            db.add(occurrence)

        db.commit()
        db.refresh(series)
        return series

    @staticmethod
    def get_series_by_id(
        db: Session,
        series_id: UUID,
    ) -> RecurringSeries | None:
        return db.get(RecurringSeries, series_id)

    @staticmethod
    def get_user_series(
        db: Session,
        user_id: UUID,
    ) -> list[RecurringSeries]:
        stmt = (
            select(RecurringSeries)
            .where(RecurringSeries.user_id == user_id)
            .order_by(RecurringSeries.created_at.desc())
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def cancel_occurrence(
        db: Session,
        occurrence_id: UUID,
        current_user: User,
    ) -> BookingOccurrence:
        occ = db.get(BookingOccurrence, occurrence_id)
        if occ is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking occurrence not found",
            )

        booking = db.get(Booking, occ.booking_id)
        if booking is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found for occurrence",
            )

        if booking.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to cancel this occurrence",
            )

        now = datetime.now(UTC)
        occ.status = "CANCELLED"
        booking.status = "CANCELLED"
        booking.cancelled_at = now

        if booking.reservation_id is not None:
            res = db.get(Reservation, booking.reservation_id)
            if res is not None:
                res.status = "CANCELLED"
                res.expires_at = None

        db.commit()
        db.refresh(occ)
        return occ
