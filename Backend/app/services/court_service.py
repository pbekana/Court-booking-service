from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.court import Court
from app.repositories.court_repository import CourtRepository
from app.repositories.venue_repository import VenueRepository
from app.schemas.court import CourtCreate, CourtUpdate


class CourtService:
    @staticmethod
    def create_court(db: Session, court_in: CourtCreate) -> Court:
        venue = VenueRepository.get_by_id(db, court_in.venue_id)
        if venue is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Venue not found",
            )
        if not venue.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create court in an inactive venue",
            )

        existing = CourtRepository.get_by_venue_and_name(
            db, court_in.venue_id, court_in.name
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A court with the name '{court_in.name.strip()}' already exists in this venue",
            )

        return CourtRepository.create(db, court_in)

    @staticmethod
    def get_courts(
        db: Session,
        venue_id: Optional[UUID] = None,
        sport_type: Optional[str] = None,
        is_active_only: bool = True,
    ) -> list[Court]:
        return CourtRepository.get_all(
            db,
            venue_id=venue_id,
            sport_type=sport_type,
            is_active_only=is_active_only,
        )

    @staticmethod
    def get_court_by_id(
        db: Session, court_id: UUID, is_active_only: bool = False
    ) -> Court:
        court = CourtRepository.get_by_id_with_venue(db, court_id)
        if court is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Court not found",
            )
        if is_active_only and not court.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Court not found",
            )
        return court

    @staticmethod
    def update_court(
        db: Session, court_id: UUID, court_in: CourtUpdate
    ) -> Court:
        court = CourtService.get_court_by_id(db, court_id, is_active_only=False)

        update_data = court_in.model_dump(exclude_unset=True)
        if not update_data:
            return court

        target_venue_id = update_data.get("venue_id", court.venue_id)
        if "venue_id" in update_data:
            venue = VenueRepository.get_by_id(db, target_venue_id)
            if venue is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Target venue not found",
                )
            if not venue.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot move court to an inactive venue",
                )

        target_name = update_data.get("name", court.name)
        if "name" in update_data or "venue_id" in update_data:
            existing = CourtRepository.get_by_venue_and_name(
                db, target_venue_id, target_name, exclude_id=court.id
            )
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A court with the name '{target_name.strip()}' already exists in this venue",
                )

        return CourtRepository.update(db, court, update_data)

    @staticmethod
    def deactivate_court(db: Session, court_id: UUID) -> Court:
        court = CourtService.get_court_by_id(db, court_id, is_active_only=False)

        if CourtRepository.has_active_future_reservations(db, court_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot deactivate court with active future reservations",
            )

        return CourtRepository.deactivate(db, court)
