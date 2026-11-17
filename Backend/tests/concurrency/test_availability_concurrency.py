import concurrent.futures
import os
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.court import Court
from app.models.pricing_rules import PricingRule
from app.models.user import User
from app.models.venue import Venue

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:123456@localhost:5432/court_booking_service_test_db",
)
real_engine = create_engine(TEST_DATABASE_URL)


def test_concurrent_availability_checks_and_hold_creation(client: TestClient):
    with Session(real_engine) as session:
        u1 = User(
            full_name="Concurrent User 1",
            email=f"u1_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw123"),
            role="MEMBER",
            is_active=True,
        )
        u2 = User(
            full_name="Concurrent User 2",
            email=f"u2_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw123"),
            role="MEMBER",
            is_active=True,
        )
        session.add(u1)
        session.add(u2)
        session.flush()

        u1_id = u1.id
        u2_id = u2.id

        venue = Venue(
            name=f"Concurrent Venue {uuid.uuid4().hex[:6]}",
            address="Concurrency Blvd",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        session.add(venue)
        session.flush()

        court = Court(
            venue_id=venue.id,
            name=f"Concurrent Court {uuid.uuid4().hex[:6]}",
            sport_type="Tennis",
            is_active=True,
        )
        session.add(court)
        session.flush()

        rule = PricingRule(
            court_id=court.id,
            pricing_type="OFF_PEAK",
            start_time=time(6, 0),
            end_time=time(22, 0),
            hourly_rate=Decimal("500.00"),
            currency="ETB",
            effective_from=datetime.now(UTC).date(),
        )
        session.add(rule)
        session.commit()

        court_id = court.id
        venue_id = venue.id

    start_at = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    end_at = start_at + timedelta(hours=1)

    def override_get_db():
        with Session(real_engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    try:
        # 1. Multiple threads check availability simultaneously
        def check_avail():
            test_client = TestClient(app)
            resp = test_client.get(
                f"/courts/{court_id}/availability",
                params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
            )
            return resp.status_code, resp.json().get("available")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(check_avail) for _ in range(5)]
            results = [f.result() for f in futures]

        for status_code, available in results:
            assert status_code == 200
            assert available is True

        # 2. Both users attempt to hold the court concurrently
        t1 = create_access_token({"sub": str(u1_id), "role": "MEMBER"})
        t2 = create_access_token({"sub": str(u2_id), "role": "MEMBER"})

        def attempt_hold(token: str) -> int:
            test_client = TestClient(app)
            resp = test_client.post(
                "/holds",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "court_id": str(court_id),
                    "start_time": start_at.isoformat(),
                    "end_time": end_at.isoformat(),
                },
            )
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(attempt_hold, t1)
            f2 = executor.submit(attempt_hold, t2)
            hold_results = [f1.result(), f2.result()]

        # Exactly one hold creation succeeds (201), the other gets 409 conflict
        assert sorted(hold_results) == [201, 409]

        # 3. Subsequent availability check must now report available: False
        with TestClient(app) as test_client:
            resp_after = test_client.get(
                f"/courts/{court_id}/availability",
                params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
            )
            assert resp_after.status_code == 200
            assert resp_after.json()["available"] is False

    finally:
        app.dependency_overrides.clear()
        with Session(real_engine) as session:
            from app.models.hold import Hold
            from app.models.reservations import Reservation
            session.query(Hold).filter(Hold.court_id == court_id).delete()
            session.query(Reservation).filter(Reservation.court_id == court_id).delete()
            session.query(PricingRule).filter(PricingRule.court_id == court_id).delete()
            session.query(Court).filter(Court.id == court_id).delete()
            session.query(Venue).filter(Venue.id == venue_id).delete()
            session.query(User).filter(User.id.in_([u1_id, u2_id])).delete()
            session.commit()

