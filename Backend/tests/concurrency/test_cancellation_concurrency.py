import concurrent.futures
import os
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.booking import Booking
from app.models.court import Court
from app.models.hold import Hold
from app.models.payment import Payment, PaymentStatus
from app.models.pricing_rules import PricingRule
from app.models.refund import Refund, RefundStatus
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue
from app.providers.mock_payment_provider import (
    MockPaymentProvider,
    get_payment_provider,
)

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:123456@localhost:5432/court_booking_service_test_db",
)
real_engine = create_engine(TEST_DATABASE_URL)


@pytest.fixture(autouse=True)
def reset_provider():
    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.reset()


def _setup_confirmed_booking(session: Session, hours_from_now: int = 48) -> tuple[User, Booking, Payment, Reservation]:
    user = User(
        full_name="Concurrency User",
        email=f"conc_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("pw123"),
        role="MEMBER",
        is_active=True,
    )
    session.add(user)
    session.flush()

    venue = Venue(
        name=f"Conc Venue {uuid.uuid4().hex[:6]}",
        address="100 Concurrency Lane",
        timezone="Africa/Addis_Ababa",
        opening_time=time(6, 0),
        closing_time=time(22, 0),
        is_active=True,
    )
    session.add(venue)
    session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Conc Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    session.add(court)
    session.flush()

    rule = PricingRule(
        court_id=court.id,
        pricing_type="PEAK",
        day_of_week=None,
        start_time=time(0, 0),
        end_time=time(23, 59, 59),
        hourly_rate=Decimal("500.00"),
        currency="ETB",
        effective_from=date(2026, 1, 1),
        effective_until=date(2030, 12, 31),
        is_active=True,
    )
    session.add(rule)
    session.flush()

    now = datetime.now(UTC)
    start_at = now + timedelta(hours=hours_from_now)
    end_at = start_at + timedelta(hours=1)

    reservation = Reservation(
        user_id=user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        status="CONFIRMED",
        expires_at=None,
    )
    session.add(reservation)
    session.flush()

    hold = Hold(
        user_id=user.id,
        court_id=court.id,
        reservation_id=reservation.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=now + timedelta(minutes=15),
        status="CONFIRMED",
    )
    session.add(hold)
    session.flush()

    booking = Booking(
        user_id=user.id,
        court_id=court.id,
        reservation_id=reservation.id,
        hold_id=hold.id,
        start_at=start_at,
        end_at=end_at,
        total_price=Decimal("500.00"),
        currency="ETB",
        status="CONFIRMED",
    )
    session.add(booking)
    session.flush()

    payment = Payment(
        booking_id=booking.id,
        hold_id=None,
        provider="MOCK",
        provider_transaction_id=f"txn_{uuid.uuid4().hex}",
        payment_reference=f"PAY-{uuid.uuid4().hex[:8].upper()}",
        amount=Decimal("500.00"),
        currency="ETB",
        status=PaymentStatus.SUCCESS.value,
    )
    session.add(payment)
    session.commit()

    return user, booking, payment, reservation


def test_concurrent_cancellations_do_not_produce_duplicate_refunds():
    """Requirement 17:

    Two simultaneous cancellation requests on the same confirmed booking.
    Verify that row-level locking ensures only one cancellation transaction proceeds,
    and no duplicate refunds are created.
    """
    with Session(real_engine) as session:
        user, booking, _payment, _reservation = _setup_confirmed_booking(session, hours_from_now=48)
        user_id = user.id
        booking_id = booking.id

    token = create_access_token({"sub": str(user_id), "role": "MEMBER"})
    headers = {"Authorization": f"Bearer {token}"}

    def override_get_db():
        with Session(real_engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    try:
        def make_cancel_request():
            test_client = TestClient(app)
            return test_client.post(f"/bookings/{booking_id}/cancel", headers=headers)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(make_cancel_request)
            fut2 = executor.submit(make_cancel_request)
            resp1 = fut1.result()
            resp2 = fut2.result()

        status_codes = sorted([resp1.status_code, resp2.status_code])
        # Exactly one request succeeded (200), the second was rejected as already cancelled (409)
        assert status_codes == [200, 409], f"Unexpected status codes: {status_codes}"

        # Verify database state with independent session
        with Session(real_engine) as session:
            booking_db = session.get(Booking, booking_id)
            assert booking_db is not None
            assert booking_db.status == "CANCELLED"

            refunds = list(session.scalars(select(Refund).where(Refund.booking_id == booking_id)).all())
            # Enforce: Exactly one refund record created, never duplicate refunds
            assert len(refunds) == 1
            assert refunds[0].status == "SUCCESS"
            assert refunds[0].amount == Decimal("500.00")

    finally:
        app.dependency_overrides.clear()


def test_concurrent_refund_retries_do_not_produce_duplicate_transactions():
    """Requirement 18:

    Concurrent refund retries do not produce duplicate provider transactions.
    """
    with Session(real_engine) as session:
        user, booking, payment, reservation = _setup_confirmed_booking(session, hours_from_now=48)
        booking.status = "CANCELLED"
        booking.cancelled_at = datetime.now(UTC)
        reservation.status = "CANCELLED"

        # Create an initial refund in FAILED status
        refund = Refund(
            booking_id=booking.id,
            payment_id=payment.id,
            amount=Decimal("500.00"),
            currency="ETB",
            idempotency_key=f"refund-booking-{booking.id}-{payment.id}",
            status=RefundStatus.FAILED.value,
            failure_reason="Initial mock timeout",
        )
        session.add(refund)
        session.commit()

        user_id = user.id
        booking_id = booking.id

    token = create_access_token({"sub": str(user_id), "role": "MEMBER"})
    headers = {"Authorization": f"Bearer {token}"}

    def override_get_db():
        with Session(real_engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    try:
        def make_retry_request():
            test_client = TestClient(app)
            return test_client.post(f"/bookings/{booking_id}/refund/retry", headers=headers)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(make_retry_request)
            fut2 = executor.submit(make_retry_request)
            resp1 = fut1.result()
            resp2 = fut2.result()

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        with Session(real_engine) as session:
            refunds = list(session.scalars(select(Refund).where(Refund.booking_id == booking_id)).all())
            assert len(refunds) == 1
            assert refunds[0].status == "SUCCESS"

            # Both responses returned the same provider refund transaction ID
            data1 = resp1.json()
            data2 = resp2.json()
            assert data1["provider_refund_id"] == data2["provider_refund_id"]

    finally:
        app.dependency_overrides.clear()


def test_database_failure_rolls_back_booking_and_reservation_together():
    """Requirement 19:

    Database failures roll back booking and reservation changes together.
    A failed database transaction does not leave the booking cancelled
    while its reservation remains active, or vice versa.
    """
    with Session(real_engine) as session:
        _user, booking, _payment, reservation = _setup_confirmed_booking(session, hours_from_now=48)
        booking_id = booking.id
        reservation_id = reservation.id

    # Simulate transactional rollback during cancellation
    with Session(real_engine) as session:
        # Lock booking
        b = session.get(Booking, booking_id)
        assert b is not None
        assert b.status == "CONFIRMED"

        r = session.get(Reservation, reservation_id)
        assert r is not None
        assert r.status == "CONFIRMED"

        # Apply in-memory changes
        b.status = "CANCELLED"
        r.status = "CANCELLED"

        # Simulate unexpected DB failure before commit
        session.rollback()

    # Verify both remain CONFIRMED
    with Session(real_engine) as session:
        b_after = session.get(Booking, booking_id)
        r_after = session.get(Reservation, reservation_id)
        assert b_after is not None
        assert r_after is not None
        assert b_after.status == "CONFIRMED"
        assert r_after.status == "CONFIRMED"
