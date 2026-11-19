import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import HOLD_DURATION_MINUTES
from app.models.booking import Booking
from app.models.court import Court
from app.models.hold import Hold
from app.models.payment import Payment, PaymentStatus
from app.models.reservations import Reservation
from app.models.user import User
from app.providers.base import BasePaymentProvider
from app.providers.mock_payment_provider import get_payment_provider
from app.repositories.court_repository import CourtRepository
from app.repositories.hold_repository import HoldRepository
from app.repositories.idempotency_repository import IdempotencyRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.pricing_repository import PricingRepository
from app.repositories.venue_repository import VenueRepository
from app.schemas.hold import HoldCreate
from app.services.booking_limit_service import BookingLimitService
from app.services.pricing_service import PricingService


class HoldService:
    @staticmethod
    def create_hold(
        db: Session,
        user_id: UUID,
        hold_in: HoldCreate,
        idempotency_key_header: str | None = None,
    ) -> Hold:
        effective_key = hold_in.idempotency_key or idempotency_key_header

        # Check idempotency first if key is present
        if effective_key:
            existing = HoldRepository.get_by_idempotency_key(
                db, user_id, effective_key
            )
            if existing is not None:
                if (
                    existing.court_id == hold_in.court_id
                    and existing.start_time == hold_in.start_time
                    and existing.end_time == hold_in.end_time
                ):
                    return existing
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key already used with different parameters",
                )

        # 1. Verify court exists and is active
        court = CourtRepository.get_by_id(db, hold_in.court_id)
        if court is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Court not found",
            )
        if not court.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Court is inactive",
            )
        if court.venue_id is not None:
            venue = VenueRepository.get_by_id(db, court.venue_id)
            if venue is not None and not venue.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot hold court in an inactive venue",
                )

        # 2 & 3. Validate time ranges
        now = datetime.now(UTC)
        start_time = (
            hold_in.start_time.replace(tzinfo=UTC)
            if hold_in.start_time.tzinfo is None
            else hold_in.start_time.astimezone(UTC)
        )
        end_time = (
            hold_in.end_time.replace(tzinfo=UTC)
            if hold_in.end_time.tzinfo is None
            else hold_in.end_time.astimezone(UTC)
        )

        if start_time <= now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Start time must be in the future",
            )
        if end_time <= start_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="End time must be later than start time",
            )

        # Concurrency protection & member booking limit enforcement
        BookingLimitService.enforce_booking_limit(
            db=db,
            user_id=user_id,
            additional_count=1,
        )

        # Concurrency protection: lock court row during availability evaluation & creation
        db.execute(
            select(Court.id)
            .where(Court.id == hold_in.court_id)
            .with_for_update()
        ).first()

        # Handle expired holds prior to checking availability
        HoldRepository.expire_stale_holds(db, court_id=hold_in.court_id)

        # 4. Check for conflicting confirmed bookings
        if HoldRepository.has_conflicting_booking(
            db, hold_in.court_id, start_time, end_time
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Court time slot conflicts with an existing confirmed booking",
            )

        # 5. Check for conflicting active holds
        if HoldRepository.has_conflicting_hold(
            db, hold_in.court_id, start_time, end_time
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Court time slot conflicts with an existing active hold",
            )

        expires_at = now + timedelta(minutes=HOLD_DURATION_MINUTES)

        try:
            reservation = Reservation(
                user_id=user_id,
                court_id=hold_in.court_id,
                start_at=start_time,
                end_at=end_time,
                status="HELD",
                expires_at=expires_at,
            )
            hold = Hold(
                user_id=user_id,
                court_id=hold_in.court_id,
                start_time=start_time,
                end_time=end_time,
                expires_at=expires_at,
                status="ACTIVE",
                idempotency_key=effective_key,
            )
            HoldRepository.create(db, hold, reservation=reservation)
            db.commit()
            db.refresh(hold)
            return hold
        except IntegrityError as exc:
            db.rollback()
            err_str = str(exc)
            if "holds_user_id_idempotency_key_key" in err_str and effective_key:
                existing = HoldRepository.get_by_idempotency_key(
                    db, user_id, effective_key
                )
                if (
                    existing is not None
                    and existing.court_id == hold_in.court_id
                    and existing.start_time == start_time
                    and existing.end_time == end_time
                ):
                    return existing
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key already used with different parameters",
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Requested court time slot is not available",
            )

    @staticmethod
    def get_hold_by_id(
        db: Session,
        hold_id: UUID,
        current_user: User,
    ) -> Hold:
        hold = HoldRepository.get_by_id(db, hold_id)
        if hold is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hold not found",
            )

        # Members can only access their own holds
        if hold.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this hold",
            )

        # Auto-expire if expired
        now = datetime.now(UTC)
        if hold.status in ["ACTIVE", "HELD"] and hold.expires_at <= now:
            hold.status = "EXPIRED"
            if hold.reservation is not None:
                hold.reservation.status = "EXPIRED"
                hold.reservation.expires_at = None
            db.commit()
            db.refresh(hold)

        return hold

    @staticmethod
    def confirm_hold(
        db: Session,
        hold_id: UUID,
        current_user: User,
        idempotency_key_header: str | None = None,
        provider: BasePaymentProvider | None = None,
    ) -> Booking:
        effective_key = idempotency_key_header
        expected_hash = IdempotencyRepository.compute_hash(f"confirm_hold:{hold_id}")

        # Idempotency check via idempotency_records
        if effective_key:
            record = IdempotencyRepository.get(db, current_user.id, effective_key)
            if record is not None:
                if record.request_hash != expected_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key already used with different parameters",
                    )
                if record.response_reference is not None:
                    existing_booking = db.get(Booking, record.response_reference)
                    if existing_booking is not None:
                        return existing_booking

        hold = HoldRepository.get_by_id(db, hold_id)
        if hold is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hold not found",
            )

        # Ownership check
        if hold.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to confirm this hold",
            )

        # Idempotency check: if already confirmed, return existing booking
        if hold.status == "CONFIRMED":
            booking = db.scalar(
                select(Booking).where(Booking.hold_id == hold.id)
            )
            if booking is not None:
                return booking

        if hold.status == "CANCELLED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot confirm a cancelled hold",
            )

        if hold.status == "EXPIRED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot confirm an expired hold",
            )

        now = datetime.now(UTC)
        if hold.expires_at <= now:
            hold.status = "EXPIRED"
            if hold.reservation is not None:
                hold.reservation.status = "EXPIRED"
                hold.reservation.expires_at = None
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot confirm an expired hold",
            )

        # Row-level locking for member & court for atomic confirmation
        BookingLimitService.acquire_member_lock(db, current_user.id)
        db.execute(
            select(Court.id).where(Court.id == hold.court_id).with_for_update()
        ).first()
        locked_hold = HoldRepository.get_by_id_for_update(db, hold_id)
        if locked_hold is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hold not found",
            )

        if locked_hold.status == "CONFIRMED":
            existing_booking = db.scalar(
                select(Booking).where(Booking.hold_id == locked_hold.id)
            )
            if existing_booking is not None:
                return existing_booking

        if locked_hold.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Hold is not active (current status: {locked_hold.status})",
            )

        if locked_hold.expires_at <= datetime.now(UTC):
            locked_hold.status = "EXPIRED"
            if locked_hold.reservation is not None:
                locked_hold.reservation.status = "EXPIRED"
                locked_hold.reservation.expires_at = None
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot confirm an expired hold",
            )

        # Enforce member booking limit (excluding this hold's reservation)
        BookingLimitService.enforce_booking_limit(
            db=db,
            user_id=current_user.id,
            additional_count=1,
            exclude_reservation_id=locked_hold.reservation_id,
        )

        # Verify court time slot is still available
        if HoldRepository.has_conflicting_booking(
            db, locked_hold.court_id, locked_hold.start_time, locked_hold.end_time
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Court time slot is no longer available",
            )

        # Calculate pricing snapshot
        total_price = Decimal("0.00")
        currency = "ETB"
        if PricingRepository.court_has_any_rules(db, locked_hold.court_id):
            court = CourtRepository.get_by_id_with_venue(db, locked_hold.court_id)
            venue = court.venue if court else None
            pricing = PricingService.calculate_pricing(
                db=db,
                court_id=locked_hold.court_id,
                start_at=locked_hold.start_time,
                end_at=locked_hold.end_time,
                venue=venue,
            )
            total_price = pricing.total_price
            currency = pricing.currency

        # Payment processing
        payment_provider = provider or get_payment_provider()
        existing_payment = PaymentRepository.get_by_hold_id(db, locked_hold.id)

        payment: Payment
        if existing_payment is not None and existing_payment.status == PaymentStatus.SUCCESS.value:
            # Payment already succeeded in previous attempt; proceed with reconciliation
            payment = existing_payment
        elif (
            existing_payment is not None
            and existing_payment.status in [PaymentStatus.PENDING.value, PaymentStatus.PROCESSING.value]
            and existing_payment.provider_transaction_id is not None
        ):
            # Check provider for asynchronous or existing transaction
            verification = payment_provider.verify_payment(existing_payment.provider_transaction_id)
            if verification.success and verification.status == PaymentStatus.SUCCESS.value:
                existing_payment.status = PaymentStatus.SUCCESS.value
                payment = existing_payment
            elif verification.status in [PaymentStatus.PENDING.value, PaymentStatus.PROCESSING.value]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Payment is still processing",
                )
            else:
                existing_payment.status = PaymentStatus.FAILED.value
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=verification.error_message or "Payment failed",
                )
        else:
            # Initiate payment if total_price > 0
            if total_price > Decimal("0.00"):
                payment_ref = f"PAY-{uuid.uuid4().hex[:12].upper()}"
                if existing_payment is None:
                    payment = Payment(
                        hold_id=locked_hold.id,
                        booking_id=None,
                        provider=payment_provider.provider_name,
                        payment_reference=payment_ref,
                        amount=total_price,
                        currency=currency,
                        status=PaymentStatus.PENDING.value,
                    )
                    PaymentRepository.create(db, payment)
                else:
                    payment = existing_payment
                    payment.payment_reference = payment_ref
                    payment.amount = total_price
                    payment.currency = currency
                    payment.status = PaymentStatus.PENDING.value
                db.flush()

                pay_idempotency_key = f"pay-{locked_hold.id}-{payment.id}"
                initiate_result = payment_provider.initiate_payment(
                    amount=total_price,
                    currency=currency,
                    payment_reference=payment.payment_reference,
                    idempotency_key=pay_idempotency_key,
                    metadata={"hold_id": str(locked_hold.id), "user_id": str(current_user.id)},
                )
                if initiate_result.provider_transaction_id:
                    payment.provider_transaction_id = initiate_result.provider_transaction_id

                if (
                    initiate_result.success
                    and initiate_result.status == PaymentStatus.SUCCESS.value
                    and initiate_result.provider_transaction_id is not None
                ):
                    ver = payment_provider.verify_payment(initiate_result.provider_transaction_id)
                    if not ver.success or ver.status != PaymentStatus.SUCCESS.value:
                        payment.status = PaymentStatus.FAILED.value
                        db.commit()
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Payment verification failed",
                        )
                    payment.status = PaymentStatus.SUCCESS.value
                elif initiate_result.status in [PaymentStatus.PENDING.value, PaymentStatus.PROCESSING.value]:
                    payment.status = initiate_result.status
                    db.commit()
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=initiate_result.error_message or "Payment processing pending",
                    )
                else:
                    payment.status = PaymentStatus.FAILED.value
                    db.commit()
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=initiate_result.error_message or "Payment failed",
                    )
            else:
                # Free booking
                payment_ref = f"PAY-ZERO-{uuid.uuid4().hex[:12].upper()}"
                payment = Payment(
                    hold_id=locked_hold.id,
                    booking_id=None,
                    provider="FREE",
                    payment_reference=payment_ref,
                    amount=Decimal("0.00"),
                    currency=currency,
                    status=PaymentStatus.SUCCESS.value,
                )
                PaymentRepository.create(db, payment)
                db.flush()

        try:
            locked_hold.status = "CONFIRMED"
            if locked_hold.reservation is not None:
                locked_hold.reservation.status = "CONFIRMED"
                locked_hold.reservation.expires_at = None

            booking = Booking(
                hold_id=locked_hold.id,
                reservation_id=locked_hold.reservation_id,
                user_id=locked_hold.user_id,
                court_id=locked_hold.court_id,
                start_at=locked_hold.start_time,
                end_at=locked_hold.end_time,
                total_price=total_price,
                currency=currency,
                status="CONFIRMED",
            )
            db.add(booking)
            db.flush()

            payment.booking_id = booking.id
            payment.hold_id = None
            payment.status = PaymentStatus.SUCCESS.value

            if effective_key:
                IdempotencyRepository.create(
                    db=db,
                    user_id=current_user.id,
                    idempotency_key=effective_key,
                    request_hash=expected_hash,
                    response_reference=booking.id,
                )

            db.commit()
            db.refresh(booking)
            return booking
        except IntegrityError:
            db.rollback()
            existing_booking = db.scalar(
                select(Booking).where(Booking.hold_id == hold_id)
            )
            if existing_booking is not None:
                return existing_booking
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Failed to confirm booking due to conflict",
            )

    @staticmethod
    def cancel_hold(
        db: Session,
        hold_id: UUID,
        current_user: User,
    ) -> Hold:
        hold = HoldRepository.get_by_id(db, hold_id)
        if hold is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hold not found",
            )

        # Ownership check
        if hold.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to cancel this hold",
            )

        now = datetime.now(UTC)
        if hold.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only active holds can be cancelled (current status: {hold.status})",
            )

        if hold.expires_at <= now:
            hold.status = "EXPIRED"
            if hold.reservation is not None:
                hold.reservation.status = "EXPIRED"
                hold.reservation.expires_at = None
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel an expired hold",
            )

        locked_hold = HoldRepository.get_by_id_for_update(db, hold_id)
        if locked_hold is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hold not found",
            )

        locked_hold.status = "CANCELLED"
        if locked_hold.reservation is not None:
            locked_hold.reservation.status = "CANCELLED"
            locked_hold.reservation.expires_at = None

        db.commit()
        db.refresh(locked_hold)
        return locked_hold
