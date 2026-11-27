from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.booking import Booking, BookingStatus
from app.models.court import Court
from app.models.hold import Hold
from app.models.venue import Venue
from app.schemas.staff_report import CourtUtilization, WeeklyUtilizationReport

TWO_DECIMAL_PLACES = Decimal("0.01")
SECONDS_PER_HOUR = Decimal(3600)
HUNDRED = Decimal(100)


def _parse_venue_timezone(venue: Venue) -> ZoneInfo:
    """Validate and return the venue's configured IANA timezone."""
    tz_name = venue.timezone.strip() if isinstance(venue.timezone, str) else ""
    if not tz_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid timezone configuration for venue '{venue.name}'",
        )
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid timezone '{tz_name}' configured for venue '{venue.name}'",
        ) from exc


def _to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _seconds_to_hours(seconds: Decimal) -> Decimal:
    """Convert elapsed seconds to hours rounded to 2 decimal places."""
    return (seconds / SECONDS_PER_HOUR).quantize(
        TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP
    )


def _calculate_utilization_percentage(
    booked_seconds: Decimal, operating_seconds: Decimal
) -> Decimal:
    """Compute (Confirmed Booked Hours / Total Operating Hours) * 100 safely."""
    if operating_seconds <= Decimal(0):
        return Decimal("0.00")
    return ((booked_seconds * HUNDRED) / operating_seconds).quantize(
        TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP
    )


def _build_operating_windows(
    start_date: date,
    end_date: date,
    opening_time: time,
    closing_time: time,
    venue_tz: ZoneInfo,
    period_start_utc: datetime,
    period_end_utc: datetime,
) -> tuple[list[tuple[datetime, datetime]], Decimal]:
    """Build daily UTC operating intervals for [start_date, end_date] in venue_tz.

    Iterates each calendar day in the venue's local timezone so DST transitions
    are reflected accurately in elapsed UTC seconds. Assumes uniform daily
    opening/closing times per the Venue schema.
    """
    if opening_time >= closing_time:
        return [], Decimal(0)

    windows: list[tuple[datetime, datetime]] = []
    total_operating_seconds = Decimal(0)
    current_day = start_date
    while current_day <= end_date:
        day_open_utc = datetime.combine(
            current_day, opening_time, tzinfo=venue_tz
        ).astimezone(UTC)
        day_close_utc = datetime.combine(
            current_day, closing_time, tzinfo=venue_tz
        ).astimezone(UTC)

        win_start = max(day_open_utc, period_start_utc)
        win_end = min(day_close_utc, period_end_utc)
        if win_end > win_start:
            windows.append((win_start, win_end))
            total_operating_seconds += Decimal(
                str((win_end - win_start).total_seconds())
            )
        current_day += timedelta(days=1)

    return windows, total_operating_seconds


class UtilizationService:
    @staticmethod
    def get_weekly_utilization_report(
        db: Session,
        venue_id: UUID | None = None,
        court_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> WeeklyUtilizationReport:
        now_utc = datetime.now(UTC)

        # 1. Validate venue/court filters and determine reference timezone
        filter_venue: Venue | None = None
        if venue_id is not None:
            filter_venue = db.get(Venue, venue_id)
            if filter_venue is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Venue not found",
                )
            _parse_venue_timezone(filter_venue)

        target_courts: list[Court]
        if court_id is not None:
            court = db.execute(
                select(Court).options(joinedload(Court.venue)).where(Court.id == court_id)
            ).scalar_one_or_none()
            if court is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Court not found",
                )
            if venue_id is not None and court.venue_id != venue_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Court does not belong to specified venue",
                )
            if court.venue is not None:
                _parse_venue_timezone(court.venue)
                if filter_venue is None:
                    filter_venue = court.venue

            # Consistent with active-only court/venue rules: exclude inactive entities
            if court.is_active and court.venue is not None and court.venue.is_active:
                target_courts = [court]
            else:
                target_courts = []
        else:
            stmt = (
                select(Court)
                .join(Venue, Court.venue_id == Venue.id)
                .options(joinedload(Court.venue))
                .where(Court.is_active.is_(True), Venue.is_active.is_(True))
                .order_by(Court.name)
            )
            if venue_id is not None:
                stmt = stmt.where(Court.venue_id == venue_id)
            target_courts = list(db.scalars(stmt).all())

        # 2. Resolve date range (using venue timezone when scoped to a single venue)
        ref_tz: ZoneInfo | None = (
            _parse_venue_timezone(filter_venue) if filter_venue is not None else None
        )
        if start_date is None and end_date is None:
            today = (
                now_utc.astimezone(ref_tz).date()
                if ref_tz is not None
                else now_utc.date()
            )
            start_date = today - timedelta(days=today.weekday())  # Current week Monday
            end_date = start_date + timedelta(days=6)  # Current week Sunday
        elif start_date is None and end_date is not None:
            start_date = end_date - timedelta(days=6)
        elif start_date is not None and end_date is None:
            end_date = start_date + timedelta(days=6)

        assert start_date is not None and end_date is not None

        if end_date < start_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_date cannot be earlier than start_date",
            )

        court_reports: list[CourtUtilization] = []
        total_op_seconds = Decimal(0)
        total_bk_seconds = Decimal(0)
        total_op_hours = Decimal("0.00")
        total_bk_hours = Decimal("0.00")

        # 3. Process each active court
        for c in target_courts:
            v: Venue | None = c.venue
            if v is None:
                continue

            venue_tz = _parse_venue_timezone(v)

            # Local calendar day boundaries converted to UTC
            period_start_utc = datetime.combine(
                start_date, time.min, tzinfo=venue_tz
            ).astimezone(UTC)
            period_end_utc = datetime.combine(
                end_date + timedelta(days=1), time.min, tzinfo=venue_tz
            ).astimezone(UTC)

            operating_windows, court_op_seconds = _build_operating_windows(
                start_date=start_date,
                end_date=end_date,
                opening_time=v.opening_time,
                closing_time=v.closing_time,
                venue_tz=venue_tz,
                period_start_utc=period_start_utc,
                period_end_utc=period_end_utc,
            )
            court_op_hours = _seconds_to_hours(court_op_seconds)

            # Confirmed bookings within the period (cancelled excluded)
            bookings = db.scalars(
                select(Booking).where(
                    Booking.court_id == c.id,
                    Booking.status == BookingStatus.CONFIRMED.value,
                    Booking.start_at < period_end_utc,
                    Booking.end_at > period_start_utc,
                )
            ).all()

            court_booked_seconds = Decimal(0)
            confirmed_booking_count = 0
            seen_booking_ids: set[UUID] = set()

            for b in bookings:
                if b.id in seen_booking_ids:
                    continue
                seen_booking_ids.add(b.id)

                b_start = _to_utc(b.start_at)
                b_end = _to_utc(b.end_at)
                booking_overlap_seconds = Decimal(0)
                for win_start, win_end in operating_windows:
                    overlap_start = max(b_start, win_start)
                    overlap_end = min(b_end, win_end)
                    if overlap_end > overlap_start:
                        booking_overlap_seconds += Decimal(
                            str((overlap_end - overlap_start).total_seconds())
                        )

                if booking_overlap_seconds > Decimal(0):
                    court_booked_seconds += booking_overlap_seconds
                    confirmed_booking_count += 1

            court_bk_hours = _seconds_to_hours(court_booked_seconds)

            # Active temporary holds within the period (not expired, reported separately)
            active_holds = db.scalars(
                select(Hold).where(
                    Hold.court_id == c.id,
                    Hold.status.in_(["ACTIVE", "HELD"]),
                    Hold.expires_at > now_utc,
                    Hold.start_time < period_end_utc,
                    Hold.end_time > period_start_utc,
                )
            ).all()

            hold_seconds = Decimal(0)
            seen_hold_ids: set[UUID] = set()
            for h in active_holds:
                if h.id in seen_hold_ids:
                    continue
                seen_hold_ids.add(h.id)

                h_start = _to_utc(h.start_time)
                h_end = _to_utc(h.end_time)
                overlap_start = max(h_start, period_start_utc)
                overlap_end = min(h_end, period_end_utc)
                if overlap_end > overlap_start:
                    hold_seconds += Decimal(
                        str((overlap_end - overlap_start).total_seconds())
                    )

            hold_hours = _seconds_to_hours(hold_seconds)
            util_pct = _calculate_utilization_percentage(
                court_booked_seconds, court_op_seconds
            )
            avail_hours = max(Decimal("0.00"), court_op_hours - court_bk_hours)

            court_reports.append(
                CourtUtilization(
                    court_id=c.id,
                    court_name=c.name,
                    venue_id=v.id,
                    venue_name=v.name,
                    sport_type=c.sport_type,
                    total_operating_hours=court_op_hours,
                    total_booked_hours=court_bk_hours,
                    total_available_hours=avail_hours,
                    utilization_percentage=util_pct,
                    confirmed_bookings_count=confirmed_booking_count,
                    number_of_confirmed_bookings=confirmed_booking_count,
                    active_holds_count=len(seen_hold_ids),
                    active_hold_hours=hold_hours,
                )
            )

            total_op_seconds += court_op_seconds
            total_bk_seconds += court_booked_seconds
            total_op_hours += court_op_hours
            total_bk_hours += court_bk_hours

        # 4. Overall metrics
        total_avail_hours = max(Decimal("0.00"), total_op_hours - total_bk_hours)
        overall_util_pct = _calculate_utilization_percentage(
            total_bk_seconds, total_op_seconds
        )

        return WeeklyUtilizationReport(
            start_date=start_date,
            end_date=end_date,
            total_courts=len(court_reports),
            total_operating_hours=total_op_hours,
            total_booked_hours=total_bk_hours,
            total_available_hours=total_avail_hours,
            overall_utilization_percentage=overall_util_pct,
            courts=court_reports,
        )
