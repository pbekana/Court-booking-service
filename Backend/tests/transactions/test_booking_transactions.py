import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingStatus
from app.models.court import Court
from app.models.hold import Hold
from app.models.payment import Payment, PaymentStatus
from app.models.refund import Refund
from app.models.reservations import Reservation
from app.models.user import User
from app.providers.mock_payment_provider import (
    MockPaymentProvider,
    get_payment_provider,
)
from app.services.booking_service import BookingService


def test_tx_01_failed_booking_confirmation_rollback(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TX-01: Force a failure during booking confirmation (payment failure).
    Verify that no partial booking remains, reservation status is not CONFIRMED,
    and no dangling successful payment record exists.
    """
    provider = get_payment_provider()
    assert isinstance(provider, MockPaymentProvider)
    provider.set_next_payment_outcome("FAILED", error_message="Simulated transaction gateway abort")

    now = datetime.now(UTC)
    start_time = now + timedelta(days=3)
    end_time = start_time + timedelta(hours=1)

    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers=member_headers,
    )
    assert hold_res.status_code == 201
    hold_id = uuid.UUID(hold_res.json()["id"])

    # Attempt confirmation -> fails
    confirm_res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_res.status_code == 400
    provider.reset()

    # DB Verification:
    # 1. No booking record exists for this hold
    booking = db_session.scalar(select(Booking).where(Booking.hold_id == hold_id))
    assert booking is None

    # 2. Hold status is not CONFIRMED
    hold_db = db_session.get(Hold, hold_id)
    assert hold_db is not None
    assert hold_db.status != "CONFIRMED"

    # 3. Reservation status is not CONFIRMED
    if hold_db.reservation_id:
        res_db = db_session.get(Reservation, hold_db.reservation_id)
        assert res_db is not None
        assert res_db.status != "CONFIRMED"

    # 4. No SUCCESS payment exists for this hold
    payments = db_session.scalars(
        select(Payment).where(Payment.hold_id == hold_id)
    ).all()
    for p in payments:
        assert p.status != PaymentStatus.SUCCESS.value


def test_tx_03_failed_cancellation_rollback(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TX-03: Force an error during cancellation commit.
    Verify that booking and reservation states remain consistently CONFIRMED,
    and no partial or orphaned refund records exist.
    """
    now = datetime.now(UTC)
    start_at = now + timedelta(days=4)
    end_at = start_at + timedelta(hours=1)

    # Create confirmed booking and payment
    res = Reservation(
        user_id=member_user.id,
        court_id=test_court.id,
        start_at=start_at,
        end_at=end_at,
        status="CONFIRMED",
        expires_at=None,
    )
    db_session.add(res)
    db_session.flush()

    hold = Hold(
        user_id=member_user.id,
        court_id=test_court.id,
        reservation_id=res.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=start_at,
        status="CONFIRMED",
    )
    db_session.add(hold)
    db_session.flush()

    booking = Booking(
        hold_id=hold.id,
        reservation_id=res.id,
        user_id=member_user.id,
        court_id=test_court.id,
        start_at=start_at,
        end_at=end_at,
        total_price=Decimal("150.00"),
        status="CONFIRMED",
    )
    db_session.add(booking)
    db_session.flush()

    payment = Payment(
        booking_id=booking.id,
        hold_id=None,
        provider="MOCK",
        payment_reference=f"PAY-{uuid.uuid4().hex[:10].upper()}",
        amount=Decimal("150.00"),
        status=PaymentStatus.SUCCESS.value,
    )
    db_session.add(payment)
    db_session.commit()

    booking_id = booking.id

    # Injected failure: monkeypatch db.commit in BookingService.cancel_booking to simulate DB crash
    original_commit = db_session.commit

    def failing_commit():
        raise RuntimeError("Simulated DB commit error during cancellation")

    # Call cancellation service directly with failing commit to inspect transaction rollback
    monkeypatch.setattr(db_session, "commit", failing_commit)

    with pytest.raises(RuntimeError, match="Simulated DB commit error"):
        BookingService.cancel_booking(
            db=db_session,
            booking_id=booking_id,
            current_user=member_user,
        )

    # Restore commit and rollback session
    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.rollback()

    # Verify atomic consistency:
    # Booking must still be CONFIRMED
    db_session.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED.value
    assert booking.cancelled_at is None

    # Reservation must still be CONFIRMED
    db_session.refresh(res)
    assert res.status == "CONFIRMED"

    # No SUCCESS refund must exist
    refunds = db_session.scalars(
        select(Refund).where(Refund.booking_id == booking_id)
    ).all()
    assert len(refunds) == 0


def test_tx_04_database_integrity_constraints(
    db_session: Session,
    member_user: User,
    test_court: Court,
) -> None:
    """TX-04: Database integrity constraints.
    Verifies: Foreign keys, Check constraints, Unique constraints, and GiST Exclusion constraints.
    """
    now = datetime.now(UTC)

    # 1. Foreign Key check: nonexistent court_id
    with pytest.raises(IntegrityError):
        invalid_court_res = Reservation(
            user_id=member_user.id,
            court_id=uuid.uuid4(),
            start_at=now + timedelta(days=1),
            end_at=now + timedelta(days=1, hours=1),
            status="HELD",
            expires_at=now + timedelta(minutes=15),
        )
        db_session.add(invalid_court_res)
        db_session.commit()
    db_session.rollback()

    # 2. Check constraint: end_at <= start_at on reservations
    with pytest.raises(IntegrityError):
        invalid_time_res = Reservation(
            user_id=member_user.id,
            court_id=test_court.id,
            start_at=now + timedelta(days=2),
            end_at=now + timedelta(days=2) - timedelta(hours=1),
            status="HELD",
            expires_at=now + timedelta(minutes=15),
        )
        db_session.add(invalid_time_res)
        db_session.commit()
    db_session.rollback()

    # 3. Check constraint: negative total_price on bookings
    with pytest.raises(IntegrityError):
        invalid_price_booking = Booking(
            hold_id=uuid.uuid4(),
            user_id=member_user.id,
            court_id=test_court.id,
            start_at=now + timedelta(days=3),
            end_at=now + timedelta(days=3, hours=1),
            total_price=Decimal("-10.00"),
            status="CONFIRMED",
        )
        db_session.add(invalid_price_booking)
        db_session.commit()
    db_session.rollback()

    # 4. Check constraint: invalid hold status
    with pytest.raises(IntegrityError):
        invalid_status_hold = Hold(
            user_id=member_user.id,
            court_id=test_court.id,
            start_time=now + timedelta(days=4),
            end_time=now + timedelta(days=4, hours=1),
            expires_at=now + timedelta(minutes=15),
            status="INVALID_STATUS",
        )
        db_session.add(invalid_status_hold)
        db_session.commit()
    db_session.rollback()

    # 5. Unique constraint: duplicate court name in same venue
    with pytest.raises(IntegrityError):
        dup_court = Court(
            venue_id=test_court.venue_id,
            name=test_court.name,
            sport_type="Tennis",
            is_active=True,
        )
        db_session.add(dup_court)
        db_session.commit()
    db_session.rollback()

    # 6. GiST exclusion constraint: overlapping active reservations
    slot_start = now + timedelta(days=10)
    slot_end = slot_start + timedelta(hours=2)

    valid_res = Reservation(
        user_id=member_user.id,
        court_id=test_court.id,
        start_at=slot_start,
        end_at=slot_end,
        status="CONFIRMED",
        expires_at=None,
    )
    db_session.add(valid_res)
    db_session.commit()

    with pytest.raises(IntegrityError):
        overlap_res = Reservation(
            user_id=member_user.id,
            court_id=test_court.id,
            start_at=slot_start + timedelta(minutes=30),
            end_at=slot_end + timedelta(minutes=30),
            status="HELD",
            expires_at=now + timedelta(minutes=15),
        )
        db_session.add(overlap_res)
        db_session.commit()
    db_session.rollback()
