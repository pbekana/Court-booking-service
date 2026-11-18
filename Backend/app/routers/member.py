from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.booking_limit import BookingLimitResponse
from app.services.booking_limit_service import BookingLimitService

router = APIRouter(tags=["Members"])


@router.get(
    "/me/booking-limit",
    response_model=BookingLimitResponse,
    status_code=status.HTTP_200_OK,
    summary="Get member's current booking limit status",
    description="Allows the authenticated member to view their current active future bookings count and remaining allowed bookings.",
)
def get_my_booking_limit(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BookingLimitResponse:
    return BookingLimitService.get_member_booking_limit_status(
        db=db,
        user_id=current_user.id,
    )
