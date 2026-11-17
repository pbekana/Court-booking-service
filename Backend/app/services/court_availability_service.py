from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.venue import Venue
from app.repositories.availability_repository import AvailabilityRepository
from app.repositories.court_repository import CourtRepository
from app.repositories.venue_repository import VenueRepository
from app.schemas.court import (
    AvailabilityInterval,
    CourtAvailabilityRequest,
    CourtAvailabilityResponse,
)
from app.services.pricing_service import PricingService
from app.workers.hold_expiration import cleanup_expired_holds


class CourtAvailabilityService:
    @staticmethod
    def check_court_availability(
        db: Session,
        court_id: UUID,
        request: CourtAvailabilityRequest,
    ) -> CourtAvailabilityResponse:
        """Determines whether a court is available for the requested time interval.

        Enforces court and venue active status, venue operating hours, conflict
        detection against reservations, bookings, holds, and recurring occurrences,
        synchronizes expired holds safely in a transaction, and calculates pricing.
        """
        # 1. Check whether the court exists
        court = CourtRepository.get_by_id_with_venue(db, court_id)
        if court is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Court not found",
            )

        # 2. Check whether the court is active
        if not court.is_active:
            return CourtAvailabilityResponse(
                court_id=court.id,
                venue_id=court.venue_id,
                available=False,
                message="Court is inactive.",
            )

        # 3. Check whether venue exists and is active
        venue: Venue | None = court.venue
        if venue is None and court.venue_id is not None:
            venue = VenueRepository.get_by_id(db, court.venue_id)

        if venue is None or not venue.is_active:
            return CourtAvailabilityResponse(
                court_id=court.id,
                venue_id=court.venue_id,
                available=False,
                message="Venue is inactive.",
            )

        # 4. Validate that requested end time is later than start time
        now = datetime.now(UTC)
        start_utc = request.start_at.astimezone(UTC)
        end_utc = request.end_at.astimezone(UTC)

        if end_utc <= start_utc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="End time must be later than start time",
            )

        # 5. Validate that requested time is in the future
        if start_utc <= now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reservation start time must be in the future",
            )

        # 6. Check venue operating hours (interpret in venue local timezone)
        if venue.opening_time >= venue.closing_time:
            # Business rules do not support overnight operating schedules
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Venue operating schedule is unsupported",
            )

        try:
            venue_tz = ZoneInfo(venue.timezone)
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            venue_tz = ZoneInfo("Africa/Addis_Ababa")

        start_local = request.start_at.astimezone(venue_tz)
        end_local = request.end_at.astimezone(venue_tz)

        # Multi-day booking interval spans closed overnight hours
        if start_local.date() != end_local.date():
            return CourtAvailabilityResponse(
                court_id=court.id,
                venue_id=court.venue_id,
                available=False,
                message="Requested time falls outside venue operating hours.",
            )

        if (
            start_local.time() < venue.opening_time
            or end_local.time() > venue.closing_time
        ):
            return CourtAvailabilityResponse(
                court_id=court.id,
                venue_id=court.venue_id,
                available=False,
                message="Requested time falls outside venue operating hours.",
            )

        # 7. Safely process expired holds using the background worker in a transaction
        cleanup_expired_holds(db, court_id=court.id)
        db.commit()

        # 8. Detect overlapping active reservations, bookings, holds, and recurring occurrences
        if AvailabilityRepository.has_conflicting_reservations(
            db, court_id=court.id, start_at=start_utc, end_at=end_utc
        ):
            return CourtAvailabilityResponse(
                court_id=court.id,
                venue_id=court.venue_id,
                available=False,
                message="Court is already reserved for the requested time.",
            )

        # 9. Court is available - calculate applicable pricing breakdown
        pricing = PricingService.calculate_pricing(
            db=db,
            court_id=court.id,
            start_at=request.start_at,
            end_at=request.end_at,
            venue=venue,
        )

        return CourtAvailabilityResponse(
            court_id=court.id,
            venue_id=court.venue_id,
            available=True,
            requested_interval=AvailabilityInterval(
                start_at=request.start_at,
                end_at=request.end_at,
            ),
            pricing=pricing,
            message="Court is available for the requested time.",
        )
