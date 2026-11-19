from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_db
from app.models.user import User, UserRole
from app.schemas.booking import BookingResponse
from app.services.booking_service import BookingService

router = APIRouter(tags=["Bookings"])


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a confirmed booking",
    description="Cancel a booking. Eligible for full refund if cancelled at least 24 hours prior to booking start time.",
)
def cancel_booking(
    booking_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> BookingResponse:
    booking = BookingService.cancel_booking(
        db=db,
        booking_id=booking_id,
        current_user=current_user,
    )
    return BookingResponse.model_validate(booking)


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Get booking details",
    description="Retrieve details of a booking by ID. Requester must be booking owner or staff/admin.",
)
def get_booking(
    booking_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> BookingResponse:
    booking = BookingService.get_by_id(db, booking_id)
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )
    user_role = getattr(current_user, "role", None)
    is_staff_or_admin = user_role in [
        UserRole.ADMIN.value,
        UserRole.STAFF.value,
        "ADMIN",
        "STAFF",
    ]
    if not is_staff_or_admin and booking.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this booking",
        )
    return BookingResponse.model_validate(booking)


@router.get(
    "",
    response_model=list[BookingResponse],
    status_code=status.HTTP_200_OK,
    summary="List user bookings",
    description="List all bookings for the authenticated user.",
)
def list_user_bookings(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[BookingResponse]:
    bookings = BookingService.get_user_bookings(db, current_user.id)
    return [BookingResponse.model_validate(b) for b in bookings]
