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
from sqlalchemy.exc import IntegrityError
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


class ConcurrencyCountingPaymentProvider(MockPaymentProvider):
    def __init__(self) -> None:
        super().__init__()
        self.initiation_count = 0
        self._lock = threading.Lock()

    def initiate_payment(
        self,
        amount: Decimal,
        currency: str,
        payment_reference: str,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentResult:
        with self._lock:
            self.initiation_count += 1
        return super().initiate_payment(
            amount=amount,
            currency=currency,
            payment_reference=payment_reference,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )


def _cleanup_test_data(
    court_ids: list[uuid.UUID] | None = None,
    venue_ids: list[uuid.UUID] | None = None,
    user_ids: list[uuid.UUID] | None = None,
) -> None:
    with Session(real_engine) as session:
        if court_ids:
            session.query(Payment).filter(
                Payment.booking_id.in_(
                    session.query(Booking.id).filter(Booking.court_id.in_(court_ids))
                )
            ).delete(synchronize_session=False)
            session.query(Booking).filter(Booking.court_id.in_(court_ids)).delete(synchronize_session=False)
            session.query(Hold).filter(Hold.court_id.in_(court_ids)).delete(synchronize_session=False)
            session.query(Reservation).filter(Reservation.court_id.in_(court_ids)).delete(synchronize_session=False)
            session.query(PricingRule).filter(PricingRule.court_id.in_(court_ids)).delete(synchronize_session=False)
            session.query(Court).filter(Court.id.in_(court_ids)).delete(synchronize_session=False)
        if venue_ids:
            session.query(Venue).filter(Venue.id.in_(venue_ids)).delete(synchronize_session=False)
        if user_ids:
            session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        session.commit()


def test_con_01_simultaneous_overlapping_reservations() -> None:
    """CON-01: Two members attempt to reserve the same court and overlapping time slots simultaneously.
    Only one reservation succeeds; conflicting request is rejected appropriately (409);
    database contains no overlapping active reservations.
    """
    with Session(real_engine) as session:
        u1 = User(
            full_name="User CON01 A",
            email=f"con01_a_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        u2 = User(
            full_name="User CON01 B",
            email=f"con01_b_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        venue = Venue(
            name=f"CON01 Venue {uuid.uuid4().hex[:6]}",
            address="Addr",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        session.add_all([u1, u2, venue])
        session.flush()

        court = Court(
            venue_id=venue.id,
            name=f"CON01 Court {uuid.uuid4().hex[:6]}",
            sport_type="Tennis",
            is_active=True,
        )
        session.add(court)
        session.flush()

        pricing = PricingRule(
            court_id=court.id,
            pricing_type="PEAK",
            day_of_week=None,
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
            hourly_rate=Decimal("150.00"),
            currency="ETB",
            effective_from=date(2025, 1, 1),
            effective_until=date(2035, 12, 31),
            is_active=True,
        )
        session.add(pricing)
        session.commit()

        u1_id, u2_id = u1.id, u2.id
        court_id = court.id
        venue_id = venue.id

    t1 = create_access_token({"sub": str(u1_id), "role": "MEMBER"})
    t2 = create_access_token({"sub": str(u2_id), "role": "MEMBER"})

    now = datetime.now(UTC)
    start_time = now + timedelta(days=2)
    end_time = start_time + timedelta(hours=2)

    def override_get_db():
        with Session(real_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    barrier = threading.Barrier(2)

    try:
        def attempt_hold(token: str) -> tuple[int, dict[str, Any]]:
            barrier.wait()
            with TestClient(app) as test_client:
                res = test_client.post(
                    "/holds",
                    json={
                        "court_id": str(court_id),
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                return res.status_code, res.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(attempt_hold, t1)
            f2 = executor.submit(attempt_hold, t2)
            r1 = f1.result()
            r2 = f2.result()

        status_codes = sorted([r1[0], r2[0]])
        assert status_codes == [201, 409], f"Results: {r1}, {r2}"

        # Check DB: exactly 1 active hold and 1 reservation
        with Session(real_engine) as session:
            active_holds = session.scalars(
                select(Hold).where(Hold.court_id == court_id, Hold.status == "ACTIVE")
            ).all()
            assert len(active_holds) == 1

            active_reservations = session.scalars(
                select(Reservation).where(
                    Reservation.court_id == court_id,
                    Reservation.status.in_(["HELD", "CONFIRMED"]),
                )
            ).all()
            assert len(active_reservations) == 1
    finally:
        app.dependency_overrides.clear()
        _cleanup_test_data([court_id], [venue_id], [u1_id, u2_id])


def test_con_02_different_courts() -> None:
    """CON-02: Two members reserve different courts simultaneously.
    Both reservations succeed.
    """
    with Session(real_engine) as session:
        u1 = User(
            full_name="User CON02 A",
            email=f"con02_a_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        u2 = User(
            full_name="User CON02 B",
            email=f"con02_b_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        venue = Venue(
            name=f"CON02 Venue {uuid.uuid4().hex[:6]}",
            address="Addr",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        session.add_all([u1, u2, venue])
        session.flush()

        court1 = Court(
            venue_id=venue.id,
            name=f"CON02 Court 1 {uuid.uuid4().hex[:6]}",
            sport_type="Tennis",
            is_active=True,
        )
        court2 = Court(
            venue_id=venue.id,
            name=f"CON02 Court 2 {uuid.uuid4().hex[:6]}",
            sport_type="Tennis",
            is_active=True,
        )
        session.add_all([court1, court2])
        session.flush()

        session.add_all([
            PricingRule(
                court_id=court1.id,
                pricing_type="PEAK",
                day_of_week=None,
                start_time=time(0, 0),
                end_time=time(23, 59, 59),
                hourly_rate=Decimal("150.00"),
                currency="ETB",
                effective_from=date(2025, 1, 1),
                effective_until=date(2035, 12, 31),
                is_active=True,
            ),
            PricingRule(
                court_id=court2.id,
                pricing_type="PEAK",
                day_of_week=None,
                start_time=time(0, 0),
                end_time=time(23, 59, 59),
                hourly_rate=Decimal("150.00"),
                currency="ETB",
                effective_from=date(2025, 1, 1),
                effective_until=date(2035, 12, 31),
                is_active=True,
            ),
        ])
        session.commit()

        u1_id, u2_id = u1.id, u2.id
        c1_id, c2_id = court1.id, court2.id
        venue_id = venue.id

    t1 = create_access_token({"sub": str(u1_id), "role": "MEMBER"})
    t2 = create_access_token({"sub": str(u2_id), "role": "MEMBER"})

    now = datetime.now(UTC)
    start_time = now + timedelta(days=2)
    end_time = start_time + timedelta(hours=1)

    def override_get_db():
        with Session(real_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    barrier = threading.Barrier(2)

    try:
        def attempt_hold(token: str, cid: uuid.UUID) -> tuple[int, dict[str, Any]]:
            barrier.wait()
            with TestClient(app) as test_client:
                res = test_client.post(
                    "/holds",
                    json={
                        "court_id": str(cid),
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                return res.status_code, res.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(attempt_hold, t1, c1_id)
            f2 = executor.submit(attempt_hold, t2, c2_id)
            r1 = f1.result()
            r2 = f2.result()

        assert r1[0] == 201, r1
        assert r2[0] == 201, r2
    finally:
        app.dependency_overrides.clear()
        _cleanup_test_data([c1_id, c2_id], [venue_id], [u1_id, u2_id])


def test_con_03_adjacent_reservations() -> None:
    """CON-03: Adjacent reservations: one ends exactly when another begins.
    Both reservations succeed.
    """
    with Session(real_engine) as session:
        u1 = User(
            full_name="User CON03 A",
            email=f"con03_a_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        u2 = User(
            full_name="User CON03 B",
            email=f"con03_b_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        venue = Venue(
            name=f"CON03 Venue {uuid.uuid4().hex[:6]}",
            address="Addr",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        session.add_all([u1, u2, venue])
        session.flush()

        court = Court(
            venue_id=venue.id,
            name=f"CON03 Court {uuid.uuid4().hex[:6]}",
            sport_type="Tennis",
            is_active=True,
        )
        session.add(court)
        session.flush()

        pricing = PricingRule(
            court_id=court.id,
            pricing_type="PEAK",
            day_of_week=None,
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
            hourly_rate=Decimal("150.00"),
            currency="ETB",
            effective_from=date(2025, 1, 1),
            effective_until=date(2035, 12, 31),
            is_active=True,
        )
        session.add(pricing)
        session.commit()

        u1_id, u2_id = u1.id, u2.id
        court_id = court.id
        venue_id = venue.id

    t1 = create_access_token({"sub": str(u1_id), "role": "MEMBER"})
    t2 = create_access_token({"sub": str(u2_id), "role": "MEMBER"})

    now = datetime.now(UTC)
    # Adjacent slots on same court: slot 1 is 10:00-11:00, slot 2 is 11:00-12:00
    slot1_start = now + timedelta(days=3)
    slot1_end = slot1_start + timedelta(hours=1)
    slot2_start = slot1_end
    slot2_end = slot2_start + timedelta(hours=1)

    def override_get_db():
        with Session(real_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    barrier = threading.Barrier(2)

    try:
        def attempt_hold(token: str, start: datetime, end: datetime) -> tuple[int, dict[str, Any]]:
            barrier.wait()
            with TestClient(app) as test_client:
                res = test_client.post(
                    "/holds",
                    json={
                        "court_id": str(court_id),
                        "start_time": start.isoformat(),
                        "end_time": end.isoformat(),
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                return res.status_code, res.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(attempt_hold, t1, slot1_start, slot1_end)
            f2 = executor.submit(attempt_hold, t2, slot2_start, slot2_end)
            r1 = f1.result()
            r2 = f2.result()

        assert r1[0] == 201, r1
        assert r2[0] == 201, r2

        with Session(real_engine) as session:
            holds = session.scalars(
                select(Hold).where(Hold.court_id == court_id, Hold.status == "ACTIVE")
            ).all()
            assert len(holds) == 2
    finally:
        app.dependency_overrides.clear()
        _cleanup_test_data([court_id], [venue_id], [u1_id, u2_id])


def test_con_04_concurrent_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    """CON-04: Concurrent confirmation: two requests attempt to confirm the same hold simultaneously.
    Only one booking created; retries return same booking; no duplicate payment created.
    """
    provider = ConcurrencyCountingPaymentProvider()
    monkeypatch.setattr(
        "app.services.hold_service.get_payment_provider", lambda: provider
    )

    with Session(real_engine) as session:
        user = User(
            full_name="User CON04",
            email=f"con04_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        venue = Venue(
            name=f"CON04 Venue {uuid.uuid4().hex[:6]}",
            address="Addr",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        session.add_all([user, venue])
        session.flush()

        court = Court(
            venue_id=venue.id,
            name=f"CON04 Court {uuid.uuid4().hex[:6]}",
            sport_type="Tennis",
            is_active=True,
        )
        session.add(court)
        session.flush()

        pricing = PricingRule(
            court_id=court.id,
            pricing_type="PEAK",
            day_of_week=None,
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
            hourly_rate=Decimal("200.00"),
            currency="ETB",
            effective_from=date(2025, 1, 1),
            effective_until=date(2035, 12, 31),
            is_active=True,
        )
        session.add(pricing)
        session.flush()

        now = datetime.now(UTC)
        start_at = now + timedelta(days=2)
        end_at = start_at + timedelta(hours=1)

        res = Reservation(
            user_id=user.id,
            court_id=court.id,
            start_at=start_at,
            end_at=end_at,
            status="HELD",
            expires_at=now + timedelta(minutes=15),
        )
        session.add(res)
        session.flush()

        hold = Hold(
            user_id=user.id,
            court_id=court.id,
            reservation_id=res.id,
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
    barrier = threading.Barrier(2)

    try:
        def confirm_call() -> tuple[int, dict[str, Any]]:
            barrier.wait()
            with TestClient(app) as test_client:
                r = test_client.post(f"/holds/{hold_id}/confirm", headers=headers)
                return r.status_code, r.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(confirm_call)
            f2 = executor.submit(confirm_call)
            r1 = f1.result()
            r2 = f2.result()

        assert [r1[0], r2[0]] == [200, 200], f"Confirmations: {r1}, {r2}"
        assert r1[1]["id"] == r2[1]["id"]
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
        _cleanup_test_data([court_id], [venue_id], [user_id])


def test_con_05_database_constraint_enforcement() -> None:
    """CON-05: Database constraint enforcement.
    Verify that the PostgreSQL GiST exclusion constraint prevents overlapping active reservations
    at the database engine level when executing raw SQL in independent transactions.
    """
    with Session(real_engine) as session:
        user = User(
            full_name="User CON05",
            email=f"con05_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        venue = Venue(
            name=f"CON05 Venue {uuid.uuid4().hex[:6]}",
            address="Addr",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        session.add_all([user, venue])
        session.flush()

        court = Court(
            venue_id=venue.id,
            name=f"CON05 Court {uuid.uuid4().hex[:6]}",
            sport_type="Tennis",
            is_active=True,
        )
        session.add(court)
        session.commit()

        user_id = user.id
        court_id = court.id
        venue_id = venue.id

    now = datetime.now(UTC)
    start_at = now + timedelta(days=5)
    end_at = start_at + timedelta(hours=2)

    try:
        # Insert first active reservation
        with Session(real_engine) as s1:
            res1 = Reservation(
                user_id=user_id,
                court_id=court_id,
                start_at=start_at,
                end_at=end_at,
                status="CONFIRMED",
                expires_at=None,
            )
            s1.add(res1)
            s1.commit()

        # Attempt raw INSERT with overlapping time slot in an independent session
        with Session(real_engine) as s2:
            overlapping_start = start_at + timedelta(minutes=30)
            overlapping_end = overlapping_start + timedelta(hours=1)
            res2 = Reservation(
                user_id=user_id,
                court_id=court_id,
                start_at=overlapping_start,
                end_at=overlapping_end,
                status="HELD",
                expires_at=now + timedelta(minutes=15),
            )
            s2.add(res2)
            with pytest.raises(IntegrityError) as exc_info:
                s2.commit()

            # Ensure error is from the PostgreSQL exclusion constraint
            err_msg = str(exc_info.value)
            assert "reservations_court_id_tstzrange_excl" in err_msg or "ExclusionViolation" in err_msg
            s2.rollback()
    finally:
        _cleanup_test_data([court_id], [venue_id], [user_id])
