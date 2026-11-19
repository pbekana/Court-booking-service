import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.payment import Payment, PaymentStatus
from app.models.user import User, UserRole
from app.providers.base import BasePaymentProvider
from app.providers.mock_payment_provider import get_payment_provider
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentWebhookPayload

logger = logging.getLogger(__name__)


class PaymentService:
    @staticmethod
    def _check_payment_access(payment: Payment, current_user: User) -> None:
        """Verify that current_user has access to the payment.

        Admins and staff can access any payment.
        Members can only access payments for their own bookings or holds.
        """
        user_role = getattr(current_user, "role", None)
        if user_role in [UserRole.ADMIN.value, UserRole.STAFF.value, "ADMIN", "STAFF"]:
            return

        # Check booking ownership
        if payment.booking is not None and payment.booking.user_id == current_user.id:
            return

        # Check hold ownership
        if payment.hold is not None and payment.hold.user_id == current_user.id:
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this payment",
        )

    @staticmethod
    def get_payment_by_id(
        db: Session, payment_id: UUID, current_user: User
    ) -> Payment:
        payment = PaymentRepository.get_by_id(db, payment_id)
        if payment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found",
            )
        PaymentService._check_payment_access(payment, current_user)
        return payment

    @staticmethod
    def get_payment_by_reference(
        db: Session, payment_reference: str, current_user: User
    ) -> Payment:
        payment = PaymentRepository.get_by_reference(db, payment_reference)
        if payment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found",
            )
        PaymentService._check_payment_access(payment, current_user)
        return payment

    @staticmethod
    def handle_webhook(
        db: Session,
        payload: PaymentWebhookPayload,
        provider: BasePaymentProvider | None = None,
    ) -> Payment:
        """Handle incoming webhook notification from the payment provider.

        Validates provider signature, verifies transaction with provider,
        and safely updates payment record without trusting client-submitted status.
        """
        payment_provider = provider or get_payment_provider()

        # Reject unverified or signature-mismatched callbacks
        if not payload.signature or payload.signature == "invalid_sig":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid provider signature",
            )

        # Look up payment by provider_transaction_id or payment_reference
        payment: Payment | None = None
        if payload.provider_transaction_id:
            payment = PaymentRepository.get_by_provider_transaction_id(
                db, payload.provider, payload.provider_transaction_id
            )
        if payment is None and payload.payment_reference:
            payment = PaymentRepository.get_by_reference(
                db, payload.payment_reference
            )

        if payment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Associated payment not found",
            )

        # Server-to-server verification with provider
        verification = payment_provider.verify_payment(payload.provider_transaction_id)
        if not verification.success and verification.status not in [
            PaymentStatus.REFUNDED.value,
            PaymentStatus.REFUND_PENDING.value,
        ]:
            if verification.status == "FAILED":
                payment.status = PaymentStatus.FAILED.value
                db.commit()
                db.refresh(payment)
                return payment
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider verification failed",
            )

        # Safe update handling duplicate webhook deliveries safely
        if verification.status in [status.value for status in PaymentStatus]:
            payment.status = verification.status

        db.commit()
        db.refresh(payment)
        return payment
