import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.payment import Payment, PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.providers.base import BasePaymentProvider
from app.providers.mock_payment_provider import get_payment_provider
from app.repositories.refund_repository import RefundRepository

logger = logging.getLogger(__name__)


def calculate_refund_eligibility(
    booking_start_at: datetime,
    cancellation_time: datetime,
) -> bool:
    """Calculate whether a booking cancellation is eligible for a full refund.

    Business Rules:
    - If member cancels at least 24 hours before start: Full refund (True).
    - Exactly 24 hours before: Full refund (True).
    - Less than 24 hours before start (e.g., 23h, 12h, 1h): No refund (False).
    - If booking has already started or passed: Rejects cancellation with ValueError.

    Uses UTC-aware timestamps and actual timedelta difference (not calendar dates).
    """
    start_utc = (
        booking_start_at
        if booking_start_at.tzinfo
        else booking_start_at.replace(tzinfo=UTC)
    )
    cancellation_utc = (
        cancellation_time
        if cancellation_time.tzinfo
        else cancellation_time.replace(tzinfo=UTC)
    )

    if cancellation_utc >= start_utc:
        raise ValueError("Cannot cancel a booking that has already started")

    time_remaining = start_utc - cancellation_utc
    return time_remaining >= timedelta(hours=24)


class RefundService:
    @staticmethod
    def calculate_refund_eligibility(
        booking_start_at: datetime,
        cancellation_time: datetime,
    ) -> bool:
        return calculate_refund_eligibility(booking_start_at, cancellation_time)

    @staticmethod
    def get_refund_by_booking_id(db: Session, booking_id: UUID) -> Refund | None:
        return RefundRepository.get_by_booking_id(db, booking_id)

    @staticmethod
    def get_refund_by_id(db: Session, refund_id: UUID) -> Refund | None:
        return RefundRepository.get_by_id(db, refund_id)

    @staticmethod
    def get_successful_payment_for_booking(
        db: Session, booking_id: UUID
    ) -> Payment | None:
        """Find the successful payment associated with the booking."""
        stmt = (
            select(Payment)
            .where(
                Payment.booking_id == booking_id,
                Payment.status.in_(
                    [
                        PaymentStatus.SUCCESS.value,
                        PaymentStatus.REFUND_PENDING.value,
                        PaymentStatus.REFUNDED.value,
                    ]
                ),
            )
            .order_by(Payment.created_at.desc())
        )
        return db.scalars(stmt).first()

    @staticmethod
    def create_refund_record(
        db: Session,
        booking: Booking,
        payment: Payment,
        idempotency_key: str | None = None,
    ) -> Refund:
        """Create a new refund record in PENDING status.

        Enforces idempotency and prevents duplicate refund records.
        """
        effective_key = idempotency_key or f"refund-booking-{booking.id}-{payment.id}"

        existing = RefundRepository.get_by_idempotency_key(db, effective_key)
        if existing is not None:
            return existing

        existing_for_booking = RefundRepository.get_by_booking_id(db, booking.id)
        if existing_for_booking is not None:
            return existing_for_booking

        refund = Refund(
            payment_id=payment.id,
            booking_id=booking.id,
            amount=payment.amount,
            currency=payment.currency,
            idempotency_key=effective_key,
            status=RefundStatus.PENDING.value,
        )
        RefundRepository.create(db, refund)
        db.flush()
        return refund

    @staticmethod
    def process_refund(
        db: Session,
        refund_id: UUID,
        provider: BasePaymentProvider | None = None,
    ) -> Refund:
        """Request the refund through the payment provider and update status.

        Idempotent:
        - If already SUCCESS, returns existing record without repeating request.
        - Uses stable idempotency_key for provider interaction.
        - Handles provider errors gracefully without raising 500.
        """
        # Lock refund row for update
        refund = db.execute(
            select(Refund).where(Refund.id == refund_id).with_for_update()
        ).scalar_one_or_none()

        if refund is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Refund record not found",
            )

        if refund.status == RefundStatus.SUCCESS.value:
            logger.info("Refund %s already processed successfully", refund.id)
            return refund

        payment = db.execute(
            select(Payment).where(Payment.id == refund.payment_id).with_for_update()
        ).scalar_one_or_none()

        if payment is None:
            refund.status = RefundStatus.FAILED.value
            refund.failure_reason = "Associated payment record not found"
            db.commit()
            return refund

        payment_provider = provider or get_payment_provider()

        try:
            refund_result = payment_provider.refund_payment(
                provider_transaction_id=payment.provider_transaction_id or "",
                amount=refund.amount,
                currency=refund.currency,
                idempotency_key=refund.idempotency_key,
                reason="Booking cancellation refund",
            )

            if refund_result.success and refund_result.status in [
                "REFUNDED",
                "SUCCESS",
                RefundStatus.SUCCESS.value,
            ]:
                refund.status = RefundStatus.SUCCESS.value
                refund.provider_refund_id = refund_result.refund_transaction_id
                refund.failure_reason = None
                payment.status = PaymentStatus.REFUNDED.value
            elif refund_result.status in [
                "REFUND_PENDING",
                "PENDING",
                "PROCESSING",
                RefundStatus.PENDING.value,
                RefundStatus.PROCESSING.value,
            ]:
                refund.status = RefundStatus.PENDING.value
                refund.provider_refund_id = refund_result.refund_transaction_id
                refund.failure_reason = None
                payment.status = PaymentStatus.REFUND_PENDING.value
            else:
                refund.status = RefundStatus.FAILED.value
                refund.failure_reason = (
                    refund_result.error_message
                    or "Refund processing rejected by provider"
                )

        except (RuntimeError, ValueError, TypeError, ConnectionError, OSError) as exc:
            logger.exception("Provider error while processing refund %s", refund.id)
            refund.status = RefundStatus.FAILED.value
            refund.failure_reason = f"Provider request failed: {exc}"

        db.commit()
        db.refresh(refund)
        return refund

    @staticmethod
    def retry_refund(
        db: Session,
        refund_id: UUID,
        provider: BasePaymentProvider | None = None,
    ) -> Refund:
        """Retry a failed or pending refund safely."""
        refund = RefundRepository.get_by_id(db, refund_id)
        if refund is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Refund record not found",
            )

        if refund.status == RefundStatus.SUCCESS.value:
            return refund

        return RefundService.process_refund(db, refund_id, provider=provider)

    @staticmethod
    def process_pending_refunds(
        db: Session,
        provider: BasePaymentProvider | None = None,
    ) -> list[Refund]:
        """Process or retry all pending and failed refunds in the outbox queue."""
        retryable = RefundRepository.get_retryable_refunds(db)
        results: list[Refund] = []
        for ref in retryable:
            try:
                processed = RefundService.process_refund(
                    db, ref.id, provider=provider
                )
                results.append(processed)
            except (
                HTTPException,
                RuntimeError,
                ValueError,
                TypeError,
                ConnectionError,
                OSError,
            ) as exc:
                logger.error("Failed to process refund %s: %s", ref.id, exc)
        return results
