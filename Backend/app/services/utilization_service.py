from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
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

        # 1. Resolve date range
        if start_date is None and end_date is None:
            today = now_utc.date()
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

        num_days = (end_date - start_date).days + 1

        # 2. Validate filters and query target courts
        if venue_id is not None:
            venue = db.get(Venue, venue_id)
            if venue is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Venue not found",
                )

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
            target_courts = [court]
        else:
            stmt = select(Court).options(joinedload(Court.venue)).order_by(Court.name)
            if venue_id is not None:
                stmt = stmt.where(Court.venue_id == venue_id)
            target_courts = list(db.scalars(stmt).all())

        court_reports: list[CourtUtilization] = []

        total_op_hours = Decimal("0.00")
        total_bk_hours = Decimal("0.00")

        # 3. Process each court
        for c in target_courts:
            v: Venue | None = c.venue
            if v is None:
                continue

            try:
                venue_tz = ZoneInfo(v.timezone)
            except (ZoneInfoNotFoundError, KeyError, ValueError):
                venue_tz = ZoneInfo("Africa/Addis_Ababa")

            # Local day boundaries converted to UTC
            period_start_utc = datetime.combine(start_date, time.min, tzinfo=venue_tz).astimezone(UTC)
            period_end_utc = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=venue_tz).astimezone(UTC)

            # Operating hours
            if v.opening_time < v.closing_time:
                daily_seconds = (
                    datetime.combine(date.min, v.closing_time) - datetime.combine(date.min, v.opening_time)
                ).total_seconds()
                court_op_hours = Decimal(str(round((daily_seconds / 3600.0) * num_days, 2)))
            else:
                court_op_hours = Decimal("0.00")

            # Confirmed bookings within the period (excluding cancelled)
            bookings = db.scalars(
                select(Booking).where(
                    Booking.court_id == c.id,
                    Booking.status == BookingStatus.CONFIRMED.value,
                    Booking.start_at < period_end_utc,
                    Booking.end_at > period_start_utc,
                )
            ).all()

            court_booked_seconds = 0.0
            for b in bookings:
                overlap_start = max(b.start_at, period_start_utc)
                overlap_end = min(b.end_at, period_end_utc)
                if overlap_end > overlap_start:
                    court_booked_seconds += (overlap_end - overlap_start).total_seconds()

            court_bk_hours = Decimal(str(round(court_booked_seconds / 3600.0, 2)))

            # Active temporary holds within the period (not expired)
            active_holds = db.scalars(
                select(Hold).where(
                    Hold.court_id == c.id,
                    Hold.status.in_(["ACTIVE", "HELD"]),
                    Hold.expires_at > now_utc,
                    Hold.start_time < period_end_utc,
                    Hold.end_time > period_start_utc,
                )
            ).all()

            hold_seconds = 0.0
            for h in active_holds:
                h_start = h.start_time if h.start_time.tzinfo else h.start_time.replace(tzinfo=UTC)
                h_end = h.end_time if h.end_time.tzinfo else h.end_time.replace(tzinfo=UTC)
                overlap_start = max(h_start, period_start_utc)
                overlap_end = min(h_end, period_end_utc)
                if overlap_end > overlap_start:
                    hold_seconds += (overlap_end - overlap_start).total_seconds()

            hold_hours = Decimal(str(round(hold_seconds / 3600.0, 2)))

            # Utilization percentage
            if court_op_hours > Decimal("0.00"):
                util_pct = Decimal(str(round((float(court_bk_hours) / float(court_op_hours)) * 100.0, 2)))
            else:
                util_pct = Decimal("0.00")

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
                    confirmed_bookings_count=len(bookings),
                    number_of_confirmed_bookings=len(bookings),
                    active_holds_count=len(active_holds),
                    active_hold_hours=hold_hours,
                )
            )

            total_op_hours += court_op_hours
            total_bk_hours += court_bk_hours

        # 4. Overall metrics
        total_avail_hours = max(Decimal("0.00"), total_op_hours - total_bk_hours)
        if total_op_hours > Decimal("0.00"):
            overall_util_pct = Decimal(str(round((float(total_bk_hours) / float(total_op_hours)) * 100.0, 2)))
        else:
            overall_util_pct = Decimal("0.00")

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
