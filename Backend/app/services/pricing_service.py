import itertools
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.pricing_rules import PricingRule
from app.models.venue import Venue
from app.repositories.court_repository import CourtRepository
from app.repositories.pricing_repository import PricingRepository
from app.repositories.venue_repository import VenueRepository
from app.schemas.court import PricingBreakdown, PricingSegment
from app.schemas.pricing_rules import (
    PricingPreviewRequest,
    PricingRuleCreate,
    PricingRuleUpdate,
)


class PricingService:
    @staticmethod
    def create_pricing_rule(
        db: Session,
        rule_in: PricingRuleCreate,
    ) -> PricingRule:
        court = CourtRepository.get_by_id(db, rule_in.court_id)
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

        conflicts = PricingRepository.find_conflicts(
            db=db,
            court_id=rule_in.court_id,
            day_of_week=rule_in.day_of_week,
            start_time=rule_in.start_time,
            end_time=rule_in.end_time,
            effective_from=rule_in.effective_from,
            effective_until=rule_in.effective_until,
        )
        if conflicts:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pricing rule conflicts with existing rule for this court and schedule",
            )

        rule = PricingRule(
            court_id=rule_in.court_id,
            pricing_type=rule_in.pricing_type,
            start_time=rule_in.start_time,
            end_time=rule_in.end_time,
            day_of_week=rule_in.day_of_week,
            hourly_rate=rule_in.hourly_rate,
            currency=rule_in.currency,
            effective_from=rule_in.effective_from,
            effective_until=rule_in.effective_until,
            is_active=True,
        )
        return PricingRepository.create(db, rule)

    @staticmethod
    def get_pricing_rules(
        db: Session,
        court_id: UUID | None = None,
        active_only: bool = False,
        effective_date: date | None = None,
    ) -> list[PricingRule]:
        return PricingRepository.get_all(
            db=db,
            court_id=court_id,
            active_only=active_only,
            effective_date=effective_date,
        )

    @staticmethod
    def get_pricing_rule_by_id(
        db: Session,
        rule_id: UUID,
    ) -> PricingRule:
        rule = PricingRepository.get_by_id(db, rule_id)
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pricing rule not found",
            )
        return rule

    @staticmethod
    def update_pricing_rule(
        db: Session,
        rule_id: UUID,
        rule_in: PricingRuleUpdate,
    ) -> PricingRule:
        rule = PricingRepository.get_by_id(db, rule_id)
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pricing rule not found",
            )

        new_pricing_type = (
            rule_in.pricing_type
            if rule_in.pricing_type is not None
            else rule.pricing_type
        )
        new_start_time = (
            rule_in.start_time if rule_in.start_time is not None else rule.start_time
        )
        new_end_time = (
            rule_in.end_time if rule_in.end_time is not None else rule.end_time
        )
        new_day_of_week = (
            rule_in.day_of_week
            if "day_of_week" in rule_in.model_fields_set
            else rule.day_of_week
        )
        new_hourly_rate = (
            rule_in.hourly_rate
            if rule_in.hourly_rate is not None
            else rule.hourly_rate
        )
        new_currency = (
            rule_in.currency if rule_in.currency is not None else rule.currency
        )
        new_effective_from = (
            rule_in.effective_from
            if rule_in.effective_from is not None
            else rule.effective_from
        )
        new_effective_until = (
            rule_in.effective_until
            if "effective_until" in rule_in.model_fields_set
            else rule.effective_until
        )
        new_is_active = (
            rule_in.is_active if rule_in.is_active is not None else rule.is_active
        )

        if new_start_time == new_end_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_time and end_time cannot be equal",
            )
        if new_effective_until and new_effective_until < new_effective_from:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="effective_until cannot be earlier than effective_from",
            )

        if new_is_active:
            conflicts = PricingRepository.find_conflicts(
                db=db,
                court_id=rule.court_id,
                day_of_week=new_day_of_week,
                start_time=new_start_time,
                end_time=new_end_time,
                effective_from=new_effective_from,
                effective_until=new_effective_until,
                exclude_rule_id=rule.id,
            )
            if conflicts:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Pricing rule conflicts with existing rule for this court and schedule",
                )

        rule.pricing_type = new_pricing_type
        rule.start_time = new_start_time
        rule.end_time = new_end_time
        rule.day_of_week = new_day_of_week
        rule.hourly_rate = new_hourly_rate
        rule.currency = new_currency
        rule.effective_from = new_effective_from
        rule.effective_until = new_effective_until
        rule.is_active = new_is_active

        return PricingRepository.update(db, rule)

    @staticmethod
    def delete_pricing_rule(
        db: Session,
        rule_id: UUID,
    ) -> None:
        rule = PricingRepository.get_by_id(db, rule_id)
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pricing rule not found",
            )
        # Soft-deactivate to preserve audit history and historical booking price snapshots
        PricingRepository.delete(db, rule, soft=True)

    @staticmethod
    def calculate_pricing(
        db: Session,
        court_id: UUID,
        start_at: datetime,
        end_at: datetime,
        venue: Venue | None = None,
    ) -> PricingBreakdown:
        """Calculates exact pricing breakdown for the requested interval across

        peak and off-peak periods, day-of-week schedules, effective date ranges,
        intervals crossing midnight, and multi-day bookings.
        Uses accurate decimal arithmetic.
        Raises HTTP 400 if end_at <= start_at.
        Raises HTTP 422 if no valid rule covers any billable interval or if ambiguous.
        """
        if end_at <= start_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="End time must be later than start time",
            )

        if venue is None:
            court = CourtRepository.get_by_id_with_venue(db, court_id)
            if court is not None and court.venue is not None:
                venue = court.venue
            elif court is not None and court.venue_id is not None:
                venue = VenueRepository.get_by_id(db, court.venue_id)

        try:
            venue_tz = ZoneInfo(venue.timezone) if venue and venue.timezone else ZoneInfo("Africa/Addis_Ababa")
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            venue_tz = ZoneInfo("Africa/Addis_Ababa")

        start_local = start_at.astimezone(venue_tz)
        end_local = end_at.astimezone(venue_tz)

        start_date = start_local.date()
        end_date = end_local.date()

        # Query candidate rules covering all dates involved (plus day before for overnight rules)
        candidates = PricingRepository.get_active_candidate_rules_for_range(
            db=db,
            court_id=court_id,
            start_date=start_date - timedelta(days=1),
            end_date=end_date,
        )

        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="No valid pricing rule found for the requested court and time interval",
            )

        # Collect transition points within the interval
        transition_points = {start_local, end_local}

        # Add midnight boundaries
        cur_d = start_date
        while cur_d <= end_date:
            midnight_dt = datetime.combine(cur_d, time.min, tzinfo=venue_tz)
            if start_local < midnight_dt < end_local:
                transition_points.add(midnight_dt)

            # Check rule boundaries for date cur_d
            for rule in candidates:
                if rule.effective_from <= cur_d and (
                    rule.effective_until is None or rule.effective_until >= cur_d
                ):
                    if rule.start_time < rule.end_time:
                        rule_start_dt = datetime.combine(
                            cur_d, rule.start_time, tzinfo=venue_tz
                        )
                        if rule.end_time >= time(23, 59, 59):
                            rule_end_dt = datetime.combine(
                                cur_d + timedelta(days=1), time.min, tzinfo=venue_tz
                            )
                        else:
                            rule_end_dt = datetime.combine(
                                cur_d, rule.end_time, tzinfo=venue_tz
                            )
                        if start_local < rule_start_dt < end_local:
                            transition_points.add(rule_start_dt)
                        if start_local < rule_end_dt < end_local:
                            transition_points.add(rule_end_dt)
                    else:
                        # Overnight rule: starts on cur_d, ends next morning
                        rule_start_dt = datetime.combine(
                            cur_d, rule.start_time, tzinfo=venue_tz
                        )
                        rule_end_dt = datetime.combine(
                            cur_d + timedelta(days=1), rule.end_time, tzinfo=venue_tz
                        )
                        if start_local < rule_start_dt < end_local:
                            transition_points.add(rule_start_dt)
                        if start_local < rule_end_dt < end_local:
                            transition_points.add(rule_end_dt)

            cur_d += timedelta(days=1)

        sorted_pts = sorted(transition_points)
        raw_segments: list[PricingSegment] = []
        rule_currency = "ETB"

        for seg_start, seg_end in itertools.pairwise(sorted_pts):
            mid_dt = seg_start + (seg_end - seg_start) / 2
            mid_date = mid_dt.date()
            mid_dow = mid_date.weekday()
            mid_time = mid_dt.time()

            matching_rules: list[PricingRule] = []

            for r in candidates:
                # Normal rule: start_time < end_time
                if r.start_time < r.end_time:
                    r_effective = (
                        r.effective_from <= mid_date
                        and (r.effective_until is None or r.effective_until >= mid_date)
                        and (r.day_of_week is None or r.day_of_week == mid_dow)
                    )
                    if (
                        r_effective
                        and r.start_time <= mid_time
                        and (r.end_time >= time(23, 59, 59) or mid_time < r.end_time)
                    ):
                        matching_rules.append(r)
                else:
                    # Overnight rule: start_time > end_time
                    # Evening part on r's day
                    if (
                        r.effective_from <= mid_date
                        and (r.effective_until is None or r.effective_until >= mid_date)
                        and (r.day_of_week is None or r.day_of_week == mid_dow)
                        and mid_time >= r.start_time
                    ):
                        matching_rules.append(r)
                    # Morning part on (r's day + 1)
                    prev_date = mid_date - timedelta(days=1)
                    if (
                        r.effective_from <= prev_date
                        and (r.effective_until is None or r.effective_until >= prev_date)
                        and (r.day_of_week is None or r.day_of_week == prev_date.weekday())
                        and mid_time < r.end_time
                    ):
                        matching_rules.append(r)

            if not matching_rules:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="No valid pricing rule found for the requested court and time interval",
                )

            # Prefer day-specific rules over general (day_of_week is None) rules
            day_specific = [r for r in matching_rules if r.day_of_week is not None]
            candidates_for_winner = day_specific if day_specific else matching_rules

            # Check for ambiguous conflicting rules at the same specificity level
            distinct_rates = {(r.hourly_rate, r.pricing_type) for r in candidates_for_winner}
            if len(distinct_rates) > 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Ambiguous pricing: multiple conflicting pricing rules apply to this time interval",
                )

            candidates_for_winner.sort(
                key=lambda r: (
                    r.effective_from,
                    r.created_at,
                ),
                reverse=True,
            )
            winner = candidates_for_winner[0]
            rule_currency = winner.currency

            seg_seconds = Decimal(str((seg_end - seg_start).total_seconds()))
            seg_hours = seg_seconds / Decimal(3600)
            hourly_rate = Decimal(str(winner.hourly_rate))
            subtotal = (hourly_rate * seg_hours).quantize(Decimal("0.01"))

            caller_tz = start_at.tzinfo or UTC
            raw_segments.append(
                PricingSegment(
                    pricing_type=winner.pricing_type,
                    start_at=seg_start.astimezone(caller_tz),
                    end_at=seg_end.astimezone(caller_tz),
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

    @staticmethod
    def preview_pricing(
        db: Session,
        preview_in: PricingPreviewRequest,
    ) -> PricingBreakdown:
        court = CourtRepository.get_by_id_with_venue(db, preview_in.court_id)
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
                detail="Venue is inactive",
            )

        return PricingService.calculate_pricing(
            db=db,
            court_id=preview_in.court_id,
            start_at=preview_in.start_at,
            end_at=preview_in.end_at,
            venue=venue,
        )
