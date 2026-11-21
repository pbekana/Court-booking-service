from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.recurring_series import (
    OccurrenceCancellationResponse,
    RecurringSeriesCancellationResponse,
    RecurringSeriesCreate,
    RecurringSeriesDetailResponse,
)
from app.services.recurring_service import RecurringService

router = APIRouter(tags=["Recurring Bookings"])


@router.post(
    "/recurring-bookings",
    response_model=RecurringSeriesDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a weekly recurring booking",
    description="Creates a weekly recurring booking series and temporary holds for all occurrences atomically under the 3-booking member limit.",
)
@router.post(
    "/recurring-series",
    response_model=RecurringSeriesDetailResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_recurring_booking(
    series_in: RecurringSeriesCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="Optional request idempotency key"),
    ] = None,
) -> RecurringSeriesDetailResponse:
    return RecurringService.create_recurring_booking(
        db=db,
        user_id=current_user.id,
        series_in=series_in,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/recurring-bookings",
    response_model=list[RecurringSeriesDetailResponse],
    status_code=status.HTTP_200_OK,
    summary="Get authenticated member's recurring bookings",
    description="Retrieve all recurring series and occurrences belonging to the authenticated member.",
)
@router.get(
    "/recurring-series",
    response_model=list[RecurringSeriesDetailResponse],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_user_recurring_bookings(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[RecurringSeriesDetailResponse]:
    return RecurringService.get_user_series(
        db=db,
        user_id=current_user.id,
    )


@router.get(
    "/recurring-bookings/{series_id}",
    response_model=RecurringSeriesDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one recurring booking series by ID",
    description="Retrieve a recurring booking series and its occurrences. Requires ownership or staff/admin permissions.",
)
@router.get(
    "/recurring-series/{series_id}",
    response_model=RecurringSeriesDetailResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_recurring_booking_by_id(
    series_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RecurringSeriesDetailResponse:
    return RecurringService.get_series_by_id(
        db=db,
        series_id=series_id,
        current_user=current_user,
    )


@router.post(
    "/recurring-bookings/{series_id}/occurrences/{occurrence_id}/cancel",
    response_model=OccurrenceCancellationResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an individual recurring booking occurrence",
    description="Cancels an individual occurrence of a recurring series. Applies standard 24-hour refund rules if confirmed.",
)
def cancel_individual_occurrence(
    series_id: UUID,
    occurrence_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="Optional request idempotency key"),
    ] = None,
) -> OccurrenceCancellationResponse:
    return RecurringService.cancel_occurrence(
        db=db,
        series_id=series_id,
        occurrence_id=occurrence_id,
        current_user=current_user,
        idempotency_key=idempotency_key,
    )


@router.delete(
    "/recurring-occurrences/{occurrence_id}",
    response_model=OccurrenceCancellationResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def cancel_recurring_occurrence_legacy(
    occurrence_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OccurrenceCancellationResponse:
    # Find series_id for the occurrence
    from app.models.booking_ocurrences import BookingOccurrence
    occ = db.get(BookingOccurrence, occurrence_id)
    if occ is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Occurrence not found")
    return RecurringService.cancel_occurrence(
        db=db,
        series_id=occ.recurring_series_id,
        occurrence_id=occurrence_id,
        current_user=current_user,
    )


@router.post(
    "/recurring-bookings/{series_id}/cancel",
    response_model=RecurringSeriesCancellationResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an entire recurring series",
    description="Cancels the recurring series and all future occurrences. Confirmed bookings are refunded according to policy.",
)
def cancel_entire_recurring_series(
    series_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RecurringSeriesCancellationResponse:
    return RecurringService.cancel_series(
        db=db,
        series_id=series_id,
        current_user=current_user,
    )
