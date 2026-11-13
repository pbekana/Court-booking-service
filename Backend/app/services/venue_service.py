from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.venue import Venue
from app.repositories.venue_repository import VenueRepository
from app.schemas.venue import VenueCreate, VenueUpdate


class VenueService:
    @staticmethod
    def create_venue(db: Session, venue_in: VenueCreate) -> Venue:
        if venue_in.opening_time >= venue_in.closing_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Opening time must be earlier than closing time",
            )
        return VenueRepository.create(db, venue_in)

    @staticmethod
    def get_venues(db: Session, is_active_only: bool = True) -> list[Venue]:
        return VenueRepository.get_all(db, is_active_only=is_active_only)

    @staticmethod
    def get_venue_by_id(
        db: Session, venue_id: UUID, is_active_only: bool = False
    ) -> Venue:
        venue = VenueRepository.get_by_id(db, venue_id)
        if venue is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Venue not found",
            )
        if is_active_only and not venue.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Venue not found",
            )
        return venue

    @staticmethod
    def update_venue(
        db: Session, venue_id: UUID, venue_in: VenueUpdate
    ) -> Venue:
        venue = VenueService.get_venue_by_id(db, venue_id, is_active_only=False)

        update_data = venue_in.model_dump(exclude_unset=True)
        if not update_data:
            return venue

        new_opening = update_data.get("opening_time", venue.opening_time)
        new_closing = update_data.get("closing_time", venue.closing_time)
        if new_opening >= new_closing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Opening time must be earlier than closing time",
            )

        return VenueRepository.update(db, venue, update_data)

    @staticmethod
    def deactivate_venue(db: Session, venue_id: UUID) -> Venue:
        venue = VenueService.get_venue_by_id(db, venue_id, is_active_only=False)

        if VenueRepository.has_active_future_reservations(db, venue_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot deactivate venue with active future reservations",
            )

        return VenueRepository.deactivate(db, venue)
