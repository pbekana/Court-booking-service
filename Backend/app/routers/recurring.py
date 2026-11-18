from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.booking_occurences import BookingOccurrenceResponse
from app.schemas.recurring_series import (
    RecurringSeriesCreate,
    RecurringSeriesResponse,
)
from app.services.recurring_booking_service import RecurringBookingService

router = APIRouter(tags=["Recurring Bookings"])


@router.post(
    "/recurring-series",
    response_model=RecurringSeriesResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recurring booking series",
    description="Creates a recurring series and all its future occurrences atomically under the 3-booking member limit.",
)
def create_recurring_series(
    series_in: RecurringSeriesCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RecurringSeriesResponse:
    series = RecurringBookingService.create_recurring_series(
        db=db,
        user_id=current_user.id,
        series_in=series_in,
    )
    return RecurringSeriesResponse.model_validate(series)


@router.get(
    "/recurring-series",
    response_model=list[RecurringSeriesResponse],
    status_code=status.HTTP_200_OK,
    summary="Get user's recurring series",
)
def get_user_recurring_series(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[RecurringSeriesResponse]:
    series_list = RecurringBookingService.get_user_series(
        db=db,
        user_id=current_user.id,
    )
    return [RecurringSeriesResponse.model_validate(s) for s in series_list]


@router.get(
    "/recurring-series/{series_id}",
    response_model=RecurringSeriesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get recurring series by ID",
)
def get_recurring_series_by_id(
    series_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RecurringSeriesResponse:
    series = RecurringBookingService.get_series_by_id(db=db, series_id=series_id)
    if series is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Recurring series not found")
    return RecurringSeriesResponse.model_validate(series)


@router.delete(
    "/recurring-occurrences/{occurrence_id}",
    response_model=BookingOccurrenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a single recurring booking occurrence",
)
def cancel_recurring_occurrence(
    occurrence_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> BookingOccurrenceResponse:
    occ = RecurringBookingService.cancel_occurrence(
        db=db,
        occurrence_id=occurrence_id,
        current_user=current_user,
    )
    return BookingOccurrenceResponse.model_validate(occ)
