import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingStatus
from app.models.refund import Refund
from app.models.reservations import Reservation
from app.models.user import User, UserRole
from app.providers.base import BasePaymentProvider
from app.repositories.idempotency_repository import IdempotencyRepository
from app.repositories.refund_repository import RefundRepository
from app.schemas.refund import (
    BookingCancellationResponse,
    BookingRefundResponse,
    RefundInfo,
)
from app.services.refund_service import RefundService, calculate_refund_eligibility

logger = logging.getLogger(__name__)


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
    def _is_staff_or_admin(user: User) -> bool:
        user_role = getattr(user, "role", None)
        return user_role in [
            UserRole.ADMIN.value,
            UserRole.STAFF.value,
            "ADMIN",
            "STAFF",
        ]

    @staticmethod
    def _check_booking_access(booking: Booking, current_user: User) -> None:
        if not BookingService._is_staff_or_admin(current_user) and booking.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this booking",
            )

    @staticmethod
    def _build_cancellation_response(
        booking: Booking,
        refund: Refund | None,
        is_eligible: bool,
    ) -> BookingCancellationResponse:
        if is_eligible and refund is not None:
            refund_info = RefundInfo(
                eligible=True,
                amount=refund.amount,
                currency=refund.currency,
                status=refund.status,
                provider_refund_id=refund.provider_refund_id,
                failure_reason=refund.failure_reason,
            )
            message = "Booking cancelled successfully"
        else:
            refund_info = RefundInfo(
                eligible=False,
                amount=Decimal("0.00"),
                currency=booking.currency,
                status=None,
            )
            message = (
                "Booking cancelled successfully. "
                "This booking is not eligible for a refund."
            )

        return BookingCancellationResponse(
            message=message,
            booking_id=booking.id,
            booking_status=booking.status,
            status=booking.status,
            cancelled_at=booking.cancelled_at,
            refund=refund_info,
        )

    @staticmethod
    def cancel_booking(
        db: Session,
        booking_id: UUID,
        current_user: User,
        idempotency_key: str | None = None,
        provider: BasePaymentProvider | None = None,
    ) -> BookingCancellationResponse:
        # Check idempotency record first if an idempotency key is supplied
        if idempotency_key:
            existing_record = IdempotencyRepository.get(
                db, current_user.id, idempotency_key
            )
            if existing_record and existing_record.response_reference:
                existing_booking = db.get(
                    Booking, existing_record.response_reference
                )
                if (
                    existing_booking
                    and existing_booking.status == BookingStatus.CANCELLED.value
                ):
                    existing_refund = RefundRepository.get_by_booking_id(
                        db, existing_booking.id
                    )
                    is_eligible = existing_refund is not None
                    return BookingService._build_cancellation_response(
                        existing_booking, existing_refund, is_eligible
                    )

        # 1. Begin database transaction & lock booking row with SELECT FOR UPDATE
        booking = db.execute(
            select(Booking).where(Booking.id == booking_id).with_for_update()
        ).scalar_one_or_none()

        # 2. Verify booking exists
        if booking is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found",
            )

        # 3. Verify user authorization (owner or staff/admin)
        if (
            not BookingService._is_staff_or_admin(current_user)
            and booking.user_id != current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to cancel this booking",
            )

        # 4. Verify booking is currently CONFIRMED; reject if already CANCELLED
        if booking.status == BookingStatus.CANCELLED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Booking has already been cancelled",
            )

        if booking.status != BookingStatus.CONFIRMED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel booking with status {booking.status}",
            )

        now = datetime.now(UTC)
        booking_start = (
            booking.start_at
            if booking.start_at.tzinfo
            else booking.start_at.replace(tzinfo=UTC)
        )

        # 5. Check if booking already started
        if now >= booking_start:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot cancel a booking that has already started",
            )

        # 6. Calculate refund eligibility
        is_eligible_for_refund = calculate_refund_eligibility(
            booking_start, now
        )

        # 7. Update booking status to CANCELLED and set cancelled_at
        booking.status = BookingStatus.CANCELLED.value
        booking.cancelled_at = now

        # 8. Update corresponding reservation status to CANCELLED and clear expires_at
        if booking.reservation_id is not None:
            reservation = db.get(Reservation, booking.reservation_id)
            if reservation is not None:
                reservation.status = "CANCELLED"
                reservation.expires_at = None
        elif booking.reservation is not None:
            booking.reservation.status = "CANCELLED"
            booking.reservation.expires_at = None

        # 9. If eligible, create a refund record with PENDING status in same transaction
        refund: Refund | None = None
        refund_id: UUID | None = None
        if is_eligible_for_refund:
            payment = RefundService.get_successful_payment_for_booking(
                db, booking.id
            )
            if payment is not None and payment.amount > Decimal("0.00"):
                refund_key = (
                    f"refund-booking-{booking.id}-{payment.id}"
                )
                refund = RefundService.create_refund_record(
                    db=db,
                    booking=booking,
                    payment=payment,
                    idempotency_key=refund_key,
                )
                refund_id = refund.id

        # 10. Store idempotency record if idempotency_key was provided
        if idempotency_key:
            req_hash = IdempotencyRepository.compute_hash(
                {"booking_id": str(booking.id), "action": "cancel"}
            )
            IdempotencyRepository.create(
                db=db,
                user_id=current_user.id,
                idempotency_key=idempotency_key,
                request_hash=req_hash,
                response_reference=booking.id,
            )

        # 11. Commit the transaction atomically
        # This guarantees booking and reservation are cancelled and court slot is freed
        db.commit()
        db.refresh(booking)

        # 12. Process refund with provider AFTER transaction is committed
        # Failed provider call does NOT rollback the cancellation
        if refund_id is not None:
            refund = RefundService.process_refund(
                db=db,
                refund_id=refund_id,
                provider=provider,
            )

        # 13. Return clear cancellation and refund response
        return BookingService._build_cancellation_response(
            booking=booking,
            refund=refund,
            is_eligible=is_eligible_for_refund,
        )

    @staticmethod
    def get_refund(
        db: Session,
        booking_id: UUID,
        current_user: User,
    ) -> BookingRefundResponse:
        booking = db.get(Booking, booking_id)
        if booking is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found",
            )

        BookingService._check_booking_access(booking, current_user)

        refund = RefundRepository.get_by_booking_id(db, booking.id)
        if refund is None:
            return BookingRefundResponse(
                booking_id=booking.id,
                refund_eligible=False,
                refund_amount=Decimal("0.00"),
                currency=booking.currency,
                refund_status=None,
                provider_refund_id=None,
                created_at=None,
                message="No refund was initiated for this booking",
            )

        return BookingRefundResponse(
            booking_id=booking.id,
            refund_eligible=True,
            refund_amount=refund.amount,
            currency=refund.currency,
            refund_status=refund.status,
            provider_refund_id=refund.provider_refund_id,
            created_at=refund.created_at,
            message=None,
        )

    @staticmethod
    def retry_refund(
        db: Session,
        booking_id: UUID,
        current_user: User,
        provider: BasePaymentProvider | None = None,
    ) -> BookingRefundResponse:
        booking = db.get(Booking, booking_id)
        if booking is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Booking not found",
            )

        BookingService._check_booking_access(booking, current_user)

        refund = RefundRepository.get_by_booking_id(db, booking.id)
        if refund is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No refund was initiated for this booking",
            )

        updated_refund = RefundService.retry_refund(
            db=db, refund_id=refund.id, provider=provider
        )

        return BookingRefundResponse(
            booking_id=booking.id,
            refund_eligible=True,
            refund_amount=updated_refund.amount,
            currency=updated_refund.currency,
            refund_status=updated_refund.status,
            provider_refund_id=updated_refund.provider_refund_id,
            created_at=updated_refund.created_at,
            message=None,
        )
