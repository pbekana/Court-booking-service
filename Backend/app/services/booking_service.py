from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingStatus
from app.models.payment import PaymentStatus
from app.models.user import User, UserRole
from app.providers.base import BasePaymentProvider
from app.providers.mock_payment_provider import get_payment_provider
from app.repositories.payment_repository import PaymentRepository


class BookingService:
    @staticmethod
    def get_by_id(db: Session, booking_id: UUID) -> Booking | None:
        return db.get(Booking, booking_id)

    @staticmethod
    def get_by_hold_id(db: Session, hold_id: UUID) -> Booking | None:
        return db.scalar(select(Booking).where(Booking.hold_id == hold_id))

    @staticmethod
    def get_user_bookings(db: Session, user_id: UUID) -> list[Booking]:
        stmt = (
            select(Booking)
            .where(Booking.user_id == user_id)
            .order_by(Booking.start_at.desc())
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def cancel_booking(
        db: Session,
        booking_id: UUID,
        current_user: User,
        provider: BasePaymentProvider | None = None,
    ) -> Booking:
        # Row-level lock on booking
        booking = db.execute(
            select(Booking).where(Booking.id == booking_id).with_for_update()
        ).scalar_one_or_none()

        if booking is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found",
            )

        # Authorization: owner, staff, or admin
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
                detail="You do not have permission to cancel this booking",
            )

        # Idempotency: if already cancelled, return existing booking without duplicate refund
        if booking.status == BookingStatus.CANCELLED.value:
            return booking

        now = datetime.now(UTC)
        booking_start = (
            booking.start_at
            if booking.start_at.tzinfo
            else booking.start_at.replace(tzinfo=UTC)
        )
        booking_end = (
            booking.end_at
            if booking.end_at.tzinfo
            else booking.end_at.replace(tzinfo=UTC)
        )

        if booking_end <= now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel a completed booking",
            )

        # 24-hour refund rule
        time_until_start = booking_start - now
        is_eligible_for_refund = time_until_start >= timedelta(hours=24)

        payment = PaymentRepository.get_by_booking_id(db, booking.id)
        if (
            is_eligible_for_refund
            and payment is not None
            and payment.amount > Decimal("0.00")
            and payment.status == PaymentStatus.SUCCESS.value
        ):
            payment_provider = provider or get_payment_provider()
            refund_idempotency_key = f"refund-booking-{booking.id}-{payment.id}"
            refund_result = payment_provider.refund_payment(
                provider_transaction_id=payment.provider_transaction_id or "",
                amount=payment.amount,
                currency=payment.currency,
                idempotency_key=refund_idempotency_key,
                reason="Cancellation >= 24 hours before start",
            )

            if refund_result.status == PaymentStatus.REFUND_PENDING.value:
                payment.status = PaymentStatus.REFUND_PENDING.value
            elif (
                refund_result.success
                and refund_result.status == PaymentStatus.REFUNDED.value
            ):
                payment.status = PaymentStatus.REFUNDED.value
            else:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=refund_result.error_message or "Refund failed by provider",
                )
            PaymentRepository.update(db, payment)

        booking.status = BookingStatus.CANCELLED.value
        booking.cancelled_at = now
        if booking.reservation is not None:
            booking.reservation.status = "CANCELLED"
            booking.reservation.expires_at = None

        db.commit()
        db.refresh(booking)
        return booking
