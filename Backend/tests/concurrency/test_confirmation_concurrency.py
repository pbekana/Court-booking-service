import concurrent.futures
import os
import threading
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

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
from app.models.payment import Payment
from app.models.pricing_rules import PricingRule
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue
from app.providers.base import PaymentResult
from app.providers.mock_payment_provider import MockPaymentProvider

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:123456@localhost:5432/court_booking_service_test_db",
)
real_engine = create_engine(TEST_DATABASE_URL)


class CountingMockPaymentProvider(MockPaymentProvider):
    def __init__(self) -> None:
        super().__init__()
        self.initiation_count = 0
        self._count_lock = threading.Lock()

    def initiate_payment(
        self,
        amount: Decimal,
        currency: str,
        payment_reference: str,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentResult:
        with self._count_lock:
            self.initiation_count += 1
        return super().initiate_payment(
            amount=amount,
            currency=currency,
            payment_reference=payment_reference,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )


def test_concurrent_confirmation_initiates_payment_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CountingMockPaymentProvider()
    monkeypatch.setattr(
        "app.services.hold_service.get_payment_provider", lambda: provider
    )

    with Session(real_engine) as session:
        user = User(
            full_name="Concurrent Confirmation User",
            email=f"confirm_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("password123"),
            role="MEMBER",
            is_active=True,
        )
        venue = Venue(
            name=f"Confirmation Venue {uuid.uuid4().hex[:6]}",
            address="Confirmation Lane",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        session.add_all([user, venue])
        session.flush()

        court = Court(
            venue_id=venue.id,
            name=f"Confirmation Court {uuid.uuid4().hex[:6]}",
            sport_type="Tennis",
            is_active=True,
        )
        session.add(court)
        session.flush()

        session.add(
            PricingRule(
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
        )

        now = datetime.now(UTC)
        start_at = now + timedelta(days=2)
        end_at = start_at + timedelta(hours=1)
        reservation = Reservation(
            user_id=user.id,
            court_id=court.id,
            start_at=start_at,
            end_at=end_at,
            status="HELD",
            expires_at=now + timedelta(minutes=15),
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
            status="ACTIVE",
        )
        session.add(hold)
        session.commit()

        user_id = user.id
        hold_id = hold.id
        court_id = court.id
        venue_id = venue.id

    token = create_access_token({"sub": str(user_id), "role": "MEMBER"})
    headers = {"Authorization": f"Bearer {token}"}

    def override_get_db():
        with Session(real_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        def confirm_hold() -> tuple[int, dict[str, Any]]:
            with TestClient(app) as client:
                response = client.post(
                    f"/holds/{hold_id}/confirm",
                    headers=headers,
                )
                return response.status_code, response.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(confirm_hold) for _ in range(2)]
            responses = [future.result() for future in futures]

        assert [response[0] for response in responses] == [200, 200], responses
        booking_ids = {response[1]["id"] for response in responses}
        assert len(booking_ids) == 1
        assert provider.initiation_count == 1

        with Session(real_engine) as session:
            bookings = session.scalars(
                select(Booking).where(Booking.hold_id == hold_id)
            ).all()
            assert len(bookings) == 1

            payments = session.scalars(
                select(Payment).where(Payment.booking_id == bookings[0].id)
            ).all()
            assert len(payments) == 1
    finally:
        app.dependency_overrides.clear()
        with Session(real_engine) as session:
            bookings = session.scalars(
                select(Booking).where(Booking.hold_id == hold_id)
            ).all()
            booking_ids = [booking.id for booking in bookings]
            if booking_ids:
                session.query(Payment).filter(
                    Payment.booking_id.in_(booking_ids)
                ).delete(synchronize_session=False)
            session.query(Payment).filter(Payment.hold_id == hold_id).delete(
                synchronize_session=False
            )
            session.query(Booking).filter(Booking.hold_id == hold_id).delete(
                synchronize_session=False
            )
            session.query(Hold).filter(Hold.id == hold_id).delete(
                synchronize_session=False
            )
            session.query(Reservation).filter(
                Reservation.user_id == user_id,
                Reservation.court_id == court_id,
            ).delete(synchronize_session=False)
            session.query(PricingRule).filter(
                PricingRule.court_id == court_id
            ).delete(synchronize_session=False)
            session.query(Court).filter(Court.id == court_id).delete(
                synchronize_session=False
            )
            session.query(Venue).filter(Venue.id == venue_id).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id == user_id).delete(
                synchronize_session=False
            )
            session.commit()
