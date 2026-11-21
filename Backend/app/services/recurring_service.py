import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import HOLD_DURATION_MINUTES
from app.models.booking import Booking
from app.models.booking_ocurrences import BookingOccurrence
from app.models.court import Court
from app.models.hold import Hold
from app.models.recurring_series import RecurringSeries
from app.models.reservations import Reservation
from app.models.user import User, UserRole
from app.repositories.availability_repository import AvailabilityRepository
from app.repositories.court_repository import CourtRepository
from app.repositories.hold_repository import HoldRepository
from app.repositories.venue_repository import VenueRepository
from app.schemas.court import CourtResponse
from app.schemas.hold import HoldResponse
from app.schemas.recurring_series import (
    OccurrenceCancellationResponse,
    RecurringOccurrenceDetail,
    RecurringSeriesCancellationResponse,
    RecurringSeriesCreate,
    RecurringSeriesDetailResponse,
)
from app.schemas.refund import RefundInfo
from app.services.booking_limit_service import (
    MAX_ACTIVE_FUTURE_BOOKINGS,
    BookingLimitExceededException,
    BookingLimitService,
)
from app.services.booking_service import BookingService

logger = logging.getLogger(__name__)


def generate_occurrence_dates(
    start_date: date,
    end_date: date,
    day_of_week: int,
) -> list[date]:
    """Generates an ordered list of weekly recurring dates for a specific weekday.

    Weekday convention: Monday = 0, ..., Sunday = 6.
    """
    if not 0 <= day_of_week <= 6:
        raise ValueError("day_of_week must be between 0 (Monday) and 6 (Sunday)")

    if end_date < start_date:
        raise ValueError("end_date cannot be earlier than start_date")

    days_until_target = (day_of_week - start_date.weekday()) % 7
    current_date = start_date + timedelta(days=days_until_target)

    occurrences: list[date] = []
    while current_date <= end_date:
        occurrences.append(current_date)
        current_date += timedelta(weeks=1)

    return occurrences


class RecurringService:
    @staticmethod
    def _is_staff_or_admin(user: User) -> bool:
        user_role = getattr(user, "role", None)
        return user_role in [
            UserRole.ADMIN.value,
            UserRole.STAFF.value,
            "ADMIN",
            "STAFF",
        ]

    @staticmethod
    def create_recurring_booking(
        db: Session,
        user_id: UUID,
        series_in: RecurringSeriesCreate,
        idempotency_key: str | None = None,
    ) -> RecurringSeriesDetailResponse:
        """Coordinates the entire weekly recurring booking creation process.

        Validates member, court, venue operating hours, and date/time rules.
        Enforces maximum 3 active future bookings per member with row-level locking.
        Generates weekly occurrences atomically as temporary holds and reservations.
        Rolls back completely if any occurrence conflicts.
        """
        # Step 1: Validate the request
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Member is inactive",
            )

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

        if not 0 <= series_in.day_of_week <= 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="day_of_week must be between 0 (Monday) and 6 (Sunday)",
            )

        if series_in.recurrence_end_date < series_in.recurrence_start_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="recurrence_end_date cannot be earlier than recurrence_start_date",
            )

        if series_in.start_time >= series_in.end_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_time must be strictly later than start_time",
            )

        if venue.opening_time >= venue.closing_time:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Venue operating schedule is unsupported",
            )

        if (
            series_in.start_time < venue.opening_time
            or series_in.end_time > venue.closing_time
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Requested time falls outside venue operating hours",
            )

        try:
            venue_tz = (
                ZoneInfo(venue.timezone)
                if venue and venue.timezone
                else ZoneInfo("Africa/Addis_Ababa")
            )
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            venue_tz = ZoneInfo("Africa/Addis_Ababa")

        # Step 2: Generate occurrences
        try:
            occurrence_dates = generate_occurrence_dates(
                series_in.recurrence_start_date,
                series_in.recurrence_end_date,
                series_in.day_of_week,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        if not occurrence_dates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No matching occurrences generated for the requested date range and weekday",
            )

        now = datetime.now(UTC)
        future_occurrences: list[tuple[date, datetime, datetime]] = []
        for occ_date in occurrence_dates:
            occ_start_local = datetime.combine(
                occ_date, series_in.start_time, tzinfo=venue_tz
            )
            occ_end_local = datetime.combine(
                occ_date, series_in.end_time, tzinfo=venue_tz
            )
            occ_start_utc = occ_start_local.astimezone(UTC)
            occ_end_utc = occ_end_local.astimezone(UTC)

            if occ_start_utc <= now:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Occurrence on {occ_date.isoformat()} is in the past. All occurrences must be in the future.",
                )
            future_occurrences.append((occ_date, occ_start_utc, occ_end_utc))

        # Step 3: Enforce member booking limit
        BookingLimitService.acquire_member_lock(db, user_id)
        BookingLimitService.expire_stale_member_holds(db, user_id)

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

        # Lock court row for concurrency protection
        db.execute(
            select(Court.id)
            .where(Court.id == series_in.court_id)
            .with_for_update()
        ).first()

        HoldRepository.expire_stale_holds(db, court_id=series_in.court_id)

        # Pre-check availability for each occurrence
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

        # Step 4, 5, 6: Create RecurringSeries, Reservations, and Holds in a single transaction
        expires_at = now + timedelta(minutes=HOLD_DURATION_MINUTES)
        created_holds: list[Hold] = []

        try:
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

            for occ_date, occ_start, occ_end in future_occurrences:
                res = Reservation(
                    user_id=user_id,
                    court_id=series_in.court_id,
                    start_at=occ_start,
                    end_at=occ_end,
                    status="HELD",
                    expires_at=expires_at,
                )
                db.add(res)
                db.flush()

                hold_key = (
                    f"recurring:{series.id}:{occ_date.isoformat()}"
                    if not idempotency_key
                    else f"{idempotency_key}:recurring:{series.id}:{occ_date.isoformat()}"
                )
                hold = Hold(
                    user_id=user_id,
                    court_id=series_in.court_id,
                    start_time=occ_start,
                    end_time=occ_end,
                    expires_at=expires_at,
                    status="ACTIVE",
                    reservation_id=res.id,
                    idempotency_key=hold_key,
                )
                db.add(hold)
                db.flush()
                created_holds.append(hold)

            db.commit()
            db.refresh(series)
            for h in created_holds:
                db.refresh(h)
        except IntegrityError as exc:
            db.rollback()
            logger.warning("IntegrityError creating recurring booking: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Court time slot conflicts with an existing reservation or hold",
            )
        except Exception:
            db.rollback()
            raise

        return RecurringService.build_series_detail_response(db, series)

    @staticmethod
    def build_series_detail_response(
        db: Session,
        series: RecurringSeries,
    ) -> RecurringSeriesDetailResponse:
        """Constructs a detailed response for a recurring series including court, occurrences, and holds."""
        court = CourtRepository.get_by_id_with_venue(db, series.court_id)
        venue = court.venue if court else None
        if venue is None and court is not None and court.venue_id is not None:
            venue = VenueRepository.get_by_id(db, court.venue_id)

        try:
            venue_tz = (
                ZoneInfo(venue.timezone)
                if venue and venue.timezone
                else ZoneInfo("Africa/Addis_Ababa")
            )
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            venue_tz = ZoneInfo("Africa/Addis_Ababa")

        dates = generate_occurrence_dates(
            series.recurrence_start_date,
            series.recurrence_end_date,
            series.day_of_week,
        )

        # Retrieve all BookingOccurrences for this series
        stmt_occ = select(BookingOccurrence).where(
            BookingOccurrence.recurring_series_id == series.id
        )
        occurrences_by_date: dict[date, BookingOccurrence] = {
            occ.occurrence_date: occ for occ in db.scalars(stmt_occ).all()
        }

        # Retrieve all Holds associated with this series
        stmt_holds = select(Hold).where(
            Hold.court_id == series.court_id,
            Hold.user_id == series.user_id,
        )
        series_holds: list[Hold] = []
        for h in db.scalars(stmt_holds).all():
            if h.idempotency_key and (
                f":{series.id}:" in h.idempotency_key
                or h.idempotency_key.startswith(f"recurring:{series.id}:")
            ):
                series_holds.append(h)

        holds_by_date: dict[date, Hold] = {}
        for h in series_holds:
            local_d = h.start_time.astimezone(venue_tz).date()
            holds_by_date[local_d] = h

        now = datetime.now(UTC)
        occurrence_details: list[RecurringOccurrenceDetail] = []
        for d in dates:
            occ_start = datetime.combine(d, series.start_time, tzinfo=venue_tz).astimezone(UTC)
            occ_end = datetime.combine(d, series.end_time, tzinfo=venue_tz).astimezone(UTC)

            if d in occurrences_by_date:
                occ = occurrences_by_date[d]
                booking = db.get(Booking, occ.booking_id)
                occurrence_details.append(
                    RecurringOccurrenceDetail(
                        occurrence_id=occ.id,
                        occurrence_date=d,
                        start_time=occ_start,
                        end_time=occ_end,
                        status=occ.status,
                        hold_id=booking.hold_id if booking else None,
                        reservation_id=booking.reservation_id if booking else None,
                        booking_id=occ.booking_id,
                        hold_status="CONFIRMED",
                        booking_status=booking.status if booking else None,
                        total_price=booking.total_price if booking else None,
                        currency=booking.currency if booking else None,
                    )
                )
            elif d in holds_by_date:
                hold = holds_by_date[d]
                hold_status = hold.status
                effective_status = hold.status
                if hold.status in ["ACTIVE", "HELD"] and hold.expires_at <= now:
                    effective_status = "EXPIRED"
                elif hold.status == "ACTIVE":
                    effective_status = "HELD"

                occurrence_details.append(
                    RecurringOccurrenceDetail(
                        occurrence_id=hold.id,
                        occurrence_date=d,
                        start_time=occ_start,
                        end_time=occ_end,
                        status=effective_status,
                        hold_id=hold.id,
                        reservation_id=hold.reservation_id,
                        booking_id=None,
                        hold_status=hold_status,
                        booking_status=None,
                        total_price=None,
                        currency=None,
                    )
                )
            else:
                occurrence_details.append(
                    RecurringOccurrenceDetail(
                        occurrence_id=None,
                        occurrence_date=d,
                        start_time=occ_start,
                        end_time=occ_end,
                        status="UNAVAILABLE",
                        hold_id=None,
                        reservation_id=None,
                        booking_id=None,
                        hold_status=None,
                        booking_status=None,
                        total_price=None,
                        currency=None,
                    )
                )

        court_resp = CourtResponse.model_validate(court) if court else None
        holds_resp = [HoldResponse.model_validate(h) for h in series_holds]

        return RecurringSeriesDetailResponse(
            id=series.id,
            series_id=series.id,
            user_id=series.user_id,
            court_id=series.court_id,
            court=court_resp,
            day_of_week=series.day_of_week,
            start_time=series.start_time,
            end_time=series.end_time,
            recurrence_start_date=series.recurrence_start_date,
            recurrence_end_date=series.recurrence_end_date,
            status=series.status,
            created_at=series.created_at,
            occurrences=occurrence_details,
            holds=holds_resp,
        )

    @staticmethod
    def get_user_series(
        db: Session,
        user_id: UUID,
    ) -> list[RecurringSeriesDetailResponse]:
        """Returns all recurring series belonging to the specified user."""
        stmt = (
            select(RecurringSeries)
            .where(RecurringSeries.user_id == user_id)
            .order_by(RecurringSeries.created_at.desc())
        )
        series_list = list(db.scalars(stmt).all())
        return [
            RecurringService.build_series_detail_response(db, s)
            for s in series_list
        ]

    @staticmethod
    def get_series_by_id(
        db: Session,
        series_id: UUID,
        current_user: User | None = None,
    ) -> RecurringSeriesDetailResponse:
        """Returns a single recurring series and its occurrences.

        Enforces ownership unless user is staff or admin.
        """
        series = db.get(RecurringSeries, series_id)
        if series is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recurring series not found",
            )

        if (
            current_user is not None
            and not RecurringService._is_staff_or_admin(current_user)
            and series.user_id != current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this recurring series",
            )

        return RecurringService.build_series_detail_response(db, series)

    @staticmethod
    def cancel_occurrence(
        db: Session,
        series_id: UUID,
        occurrence_id: UUID,
        current_user: User,
        idempotency_key: str | None = None,
    ) -> OccurrenceCancellationResponse:
        """Cancels an individual occurrence of a recurring series.

        Enforces ownership / staff authorization.
        Follows 24-hour refund rules for confirmed bookings.
        Cancels associated holds if unconfirmed.
        Rejects already cancelled occurrences.
        """
        series = db.get(RecurringSeries, series_id)
        if series is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recurring series not found",
            )

        if not RecurringService._is_staff_or_admin(current_user) and series.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to cancel this occurrence",
            )

        # 1. Check if occurrence is a confirmed BookingOccurrence
        occ = db.get(BookingOccurrence, occurrence_id)
        if occ is not None:
            if occ.recurring_series_id != series_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Occurrence does not belong to the specified recurring series",
                )

            if occ.status == "CANCELLED":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Occurrence has already been cancelled",
                )

            # Follow existing cancellation and refund policy via BookingService
            booking_cancel_resp = BookingService.cancel_booking(
                db=db,
                booking_id=occ.booking_id,
                current_user=current_user,
                idempotency_key=idempotency_key,
            )

            occ.status = "CANCELLED"
            db.commit()
            db.refresh(occ)

            refund_info: RefundInfo | None = None
            if booking_cancel_resp.refund:
                refund_info = RefundInfo(
                    eligible=booking_cancel_resp.refund.eligible,
                    amount=booking_cancel_resp.refund.amount,
                    currency=booking_cancel_resp.refund.currency,
                    status=booking_cancel_resp.refund.status,
                    provider_refund_id=booking_cancel_resp.refund.provider_refund_id,
                    failure_reason=booking_cancel_resp.refund.failure_reason,
                )

            return OccurrenceCancellationResponse(
                message="Occurrence cancelled successfully",
                series_id=series_id,
                occurrence_id=occ.id,
                occurrence_date=occ.occurrence_date,
                status="CANCELLED",
                booking_id=occ.booking_id,
                refund=refund_info,
                cancelled_at=booking_cancel_resp.cancelled_at,
            )

        # 2. Check if occurrence is an unconfirmed Hold
        hold = db.get(Hold, occurrence_id)
        if hold is not None:
            if hold.user_id != series.user_id or hold.court_id != series.court_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Hold does not belong to the specified recurring series",
                )

            if hold.status == "CANCELLED":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Occurrence has already been cancelled",
                )

            now = datetime.now(UTC)
            hold.status = "CANCELLED"
            if hold.reservation is not None:
                hold.reservation.status = "CANCELLED"
                hold.reservation.expires_at = None

            db.commit()
            db.refresh(hold)

            court = CourtRepository.get_by_id_with_venue(db, hold.court_id)
            venue = court.venue if court else None
            try:
                venue_tz = (
                    ZoneInfo(venue.timezone)
                    if venue and venue.timezone
                    else ZoneInfo("Africa/Addis_Ababa")
                )
            except (ZoneInfoNotFoundError, KeyError, ValueError):
                venue_tz = ZoneInfo("Africa/Addis_Ababa")

            occ_date = hold.start_time.astimezone(venue_tz).date()

            return OccurrenceCancellationResponse(
                message="Occurrence hold cancelled successfully",
                series_id=series_id,
                occurrence_id=hold.id,
                occurrence_date=occ_date,
                status="CANCELLED",
                hold_id=hold.id,
                refund=None,
                cancelled_at=now,
            )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Occurrence not found",
        )

    @staticmethod
    def cancel_series(
        db: Session,
        series_id: UUID,
        current_user: User,
    ) -> RecurringSeriesCancellationResponse:
        """Cancels an entire recurring series and all its remaining future occurrences.

        Marks series as CANCELLED.
        Cancels unconfirmed future holds.
        Applies existing cancellation/refund policy to confirmed future bookings.
        Does not cancel past occurrences.
        Idempotent: does not refund already cancelled bookings.
        """
        series = db.get(RecurringSeries, series_id)
        if series is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recurring series not found",
            )

        if not RecurringService._is_staff_or_admin(current_user) and series.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to cancel this recurring series",
            )

        series.status = "CANCELLED"

        court = CourtRepository.get_by_id_with_venue(db, series.court_id)
        venue = court.venue if court else None
        if venue is None and court is not None and court.venue_id is not None:
            venue = VenueRepository.get_by_id(db, court.venue_id)

        try:
            venue_tz = (
                ZoneInfo(venue.timezone)
                if venue and venue.timezone
                else ZoneInfo("Africa/Addis_Ababa")
            )
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            venue_tz = ZoneInfo("Africa/Addis_Ababa")

        dates = generate_occurrence_dates(
            series.recurrence_start_date,
            series.recurrence_end_date,
            series.day_of_week,
        )

        now = datetime.now(UTC)

        # Retrieve BookingOccurrences
        stmt_occ = select(BookingOccurrence).where(
            BookingOccurrence.recurring_series_id == series.id
        )
        occurrences_by_date = {
            occ.occurrence_date: occ for occ in db.scalars(stmt_occ).all()
        }

        # Retrieve Holds
        stmt_holds = select(Hold).where(
            Hold.court_id == series.court_id,
            Hold.user_id == series.user_id,
        )
        series_holds: list[Hold] = []
        for h in db.scalars(stmt_holds).all():
            if h.idempotency_key and (
                f":{series.id}:" in h.idempotency_key
                or h.idempotency_key.startswith(f"recurring:{series.id}:")
            ):
                series_holds.append(h)

        holds_by_date: dict[date, Hold] = {}
        for h in series_holds:
            local_d = h.start_time.astimezone(venue_tz).date()
            holds_by_date[local_d] = h

        cancelled_occurrences: list[OccurrenceCancellationResponse] = []
        cancelled_holds_count = 0
        cancelled_bookings_count = 0
        total_refund_amount = Decimal("0.00")
        currency = "ETB"

        for d in dates:
            occ_start = datetime.combine(d, series.start_time, tzinfo=venue_tz).astimezone(UTC)

            # Do not cancel past occurrences
            if occ_start <= now:
                continue

            # If there is a confirmed booking occurrence
            if d in occurrences_by_date:
                occ = occurrences_by_date[d]
                if occ.status != "CANCELLED":
                    booking = db.get(Booking, occ.booking_id)
                    if booking and booking.status != "CANCELLED":
                        try:
                            cancel_resp = BookingService.cancel_booking(
                                db=db,
                                booking_id=occ.booking_id,
                                current_user=current_user,
                            )
                            occ.status = "CANCELLED"
                            cancelled_bookings_count += 1
                            if cancel_resp.refund and cancel_resp.refund.eligible:
                                total_refund_amount += cancel_resp.refund.amount
                                currency = cancel_resp.refund.currency

                            refund_info = None
                            if cancel_resp.refund:
                                refund_info = RefundInfo(
                                    eligible=cancel_resp.refund.eligible,
                                    amount=cancel_resp.refund.amount,
                                    currency=cancel_resp.refund.currency,
                                    status=cancel_resp.refund.status,
                                    provider_refund_id=cancel_resp.refund.provider_refund_id,
                                    failure_reason=cancel_resp.refund.failure_reason,
                                )

                            cancelled_occurrences.append(
                                OccurrenceCancellationResponse(
                                    message="Occurrence cancelled successfully",
                                    series_id=series.id,
                                    occurrence_id=occ.id,
                                    occurrence_date=d,
                                    status="CANCELLED",
                                    booking_id=occ.booking_id,
                                    refund=refund_info,
                                    cancelled_at=cancel_resp.cancelled_at,
                                )
                            )
                        except (HTTPException, RuntimeError, ValueError, TypeError, OSError) as exc:
                            logger.error("Error cancelling booking for occurrence %s: %s", occ.id, exc)

            # If there is an unconfirmed hold
            if d in holds_by_date:
                hold = holds_by_date[d]
                if hold.status in ["ACTIVE", "HELD"]:
                    hold.status = "CANCELLED"
                    if hold.reservation is not None:
                        hold.reservation.status = "CANCELLED"
                        hold.reservation.expires_at = None
                    cancelled_holds_count += 1

                    cancelled_occurrences.append(
                        OccurrenceCancellationResponse(
                            message="Occurrence hold cancelled",
                            series_id=series.id,
                            occurrence_id=hold.id,
                            occurrence_date=d,
                            status="CANCELLED",
                            hold_id=hold.id,
                            refund=None,
                            cancelled_at=now,
                        )
                    )

        db.commit()
        db.refresh(series)

        return RecurringSeriesCancellationResponse(
            message="Recurring series cancelled successfully",
            series_id=series.id,
            status="CANCELLED",
            cancelled_occurrences_count=len(cancelled_occurrences),
            cancelled_holds_count=cancelled_holds_count,
            cancelled_bookings_count=cancelled_bookings_count,
            total_refund_amount=total_refund_amount,
            currency=currency,
            occurrences=cancelled_occurrences,
        )


# Backwards compatibility alias
RecurringBookingService = RecurringService
