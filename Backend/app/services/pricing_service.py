import itertools
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.venue import Venue
from app.repositories.pricing_repository import PricingRepository
from app.schemas.court import PricingBreakdown, PricingSegment


class PricingService:
    @staticmethod
    def calculate_pricing(
        db: Session,
        court_id: UUID,
        start_at: datetime,
        end_at: datetime,
        venue: Venue,
    ) -> PricingBreakdown:
        """Calculates exact pricing breakdown for the requested interval across

        peak and off-peak periods, day-of-week overrides, and effective date ranges.
        Raises HTTP 422 if no valid pricing rule covers the requested interval.
        """
        try:
            venue_tz = ZoneInfo(venue.timezone)
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            venue_tz = ZoneInfo("Africa/Addis_Ababa")

        start_local = start_at.astimezone(venue_tz)
        end_local = end_at.astimezone(venue_tz)
        booking_date = start_local.date()
        day_of_week = booking_date.weekday()

        candidates = PricingRepository.get_candidate_rules(
            db=db,
            court_id=court_id,
            booking_date=booking_date,
            day_of_week=day_of_week,
        )
        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="No valid pricing rule found for the requested court and time interval",
            )

        # Collect all boundary and transition points within the interval
        transition_points = {start_local, end_local}
        for rule in candidates:
            rule_start_dt = datetime.combine(booking_date, rule.start_time, tzinfo=venue_tz)
            rule_end_dt = datetime.combine(booking_date, rule.end_time, tzinfo=venue_tz)
            if start_local < rule_start_dt < end_local:
                transition_points.add(rule_start_dt)
            if start_local < rule_end_dt < end_local:
                transition_points.add(rule_end_dt)

        sorted_pts = sorted(transition_points)
        raw_segments: list[PricingSegment] = []
        rule_currency = "ETB"

        for seg_start, seg_end in itertools.pairwise(sorted_pts):
            mid_dt = seg_start + (seg_end - seg_start) / 2
            mid_time = mid_dt.time()

            matching_rules = [
                r for r in candidates if r.start_time <= mid_time < r.end_time
            ]
            if not matching_rules:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="No valid pricing rule found for the requested court and time interval",
                )

            # Precedence: day-specific rules first, then latest effective_from, then created_at
            matching_rules.sort(
                key=lambda r: (
                    r.day_of_week is not None,
                    r.effective_from,
                    r.created_at,
                ),
                reverse=True,
            )
            winner = matching_rules[0]
            rule_currency = winner.currency

            seg_seconds = Decimal((seg_end - seg_start).total_seconds())
            seg_hours = seg_seconds / Decimal(3600)
            hourly_rate = Decimal(str(winner.hourly_rate))
            subtotal = (hourly_rate * seg_hours).quantize(Decimal("0.01"))

            # Format start_at and end_at preserving caller's requested timezone
            raw_segments.append(
                PricingSegment(
                    pricing_type=winner.pricing_type,
                    start_at=seg_start.astimezone(start_at.tzinfo),
                    end_at=seg_end.astimezone(start_at.tzinfo),
                    hourly_rate=hourly_rate,
                    subtotal=subtotal,
                )
            )

        # Merge adjacent segments with matching pricing_type and hourly_rate
        merged_segments: list[PricingSegment] = []
        for seg in raw_segments:
            if (
                merged_segments
                and merged_segments[-1].pricing_type == seg.pricing_type
                and merged_segments[-1].hourly_rate == seg.hourly_rate
            ):
                prev = merged_segments[-1]
                merged_segments[-1] = PricingSegment(
                    pricing_type=prev.pricing_type,
                    start_at=prev.start_at,
                    end_at=seg.end_at,
                    hourly_rate=prev.hourly_rate,
                    subtotal=(prev.subtotal + seg.subtotal).quantize(Decimal("0.01")),
                )
            else:
                merged_segments.append(seg)

        total_price = sum((s.subtotal for s in merged_segments), Decimal("0.00")).quantize(
            Decimal("0.01")
        )

        return PricingBreakdown(
            currency=rule_currency,
            total_price=total_price,
            segments=merged_segments,
        )
