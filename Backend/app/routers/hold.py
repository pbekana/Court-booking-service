from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.booking import BookingResponse
from app.schemas.hold import HoldCreate, HoldResponse
from app.services.hold_service import HoldService

router = APIRouter(tags=["Holds"])


@router.post(
    "",
    response_model=HoldResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a temporary court hold",
    description="Temporarily hold a court time slot before booking and payment.",
)
def create_hold(
    hold_in: HoldCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="Optional request idempotency key"),
    ] = None,
) -> HoldResponse:
    hold = HoldService.create_hold(
        db=db,
        user_id=current_user.id,
        hold_in=hold_in,
        idempotency_key_header=idempotency_key,
    )
    return HoldResponse.model_validate(hold)


@router.get(
    "/{hold_id}",
    response_model=HoldResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve hold details",
    description="Retrieve the hold's current status and expiration timestamp. Members can only view their own holds.",
)
def get_hold(
    hold_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> HoldResponse:
    hold = HoldService.get_hold_by_id(
        db=db,
        hold_id=hold_id,
        current_user=current_user,
    )
    return HoldResponse.model_validate(hold)


@router.post(
    "/{hold_id}/confirm",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm a temporary hold",
    description="Convert an active hold into a confirmed booking atomically.",
)
def confirm_hold(
    hold_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> BookingResponse:
    booking = HoldService.confirm_hold(
        db=db,
        hold_id=hold_id,
        current_user=current_user,
    )
    return BookingResponse.model_validate(booking)


@router.delete(
    "/{hold_id}",
    response_model=HoldResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a temporary hold",
    description="Cancel an active temporary hold and immediately release the held time slot.",
)
def cancel_hold(
    hold_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> HoldResponse:
    cancelled_hold = HoldService.cancel_hold(
        db=db,
        hold_id=hold_id,
        current_user=current_user,
    )
    return HoldResponse.model_validate(cancelled_hold)
