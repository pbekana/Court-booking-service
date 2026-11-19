from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.payment import PaymentResponse, PaymentWebhookPayload
from app.services.payment_service import PaymentService

router = APIRouter(tags=["Payments"])


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get payment by ID",
    description="Retrieve payment details by payment UUID. Requires authentication and ownership or staff/admin role.",
)
def get_payment_by_id(
    payment_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PaymentResponse:
    payment = PaymentService.get_payment_by_id(
        db=db,
        payment_id=payment_id,
        current_user=current_user,
    )
    return PaymentResponse.model_validate(payment)


@router.get(
    "/reference/{payment_reference}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get payment by reference",
    description="Retrieve payment details by its unique payment reference. Requires authentication and ownership or staff/admin role.",
)
def get_payment_by_reference(
    payment_reference: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PaymentResponse:
    payment = PaymentService.get_payment_by_reference(
        db=db,
        payment_reference=payment_reference,
        current_user=current_user,
    )
    return PaymentResponse.model_validate(payment)


@router.post(
    "/webhook",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Payment provider callback / webhook",
    description="Secure endpoint to receive asynchronous status updates from payment providers with signature verification.",
)
def payment_webhook(
    payload: PaymentWebhookPayload,
    db: Annotated[Session, Depends(get_db)],
) -> PaymentResponse:
    payment = PaymentService.handle_webhook(
        db=db,
        payload=payload,
    )
    return PaymentResponse.model_validate(payment)
