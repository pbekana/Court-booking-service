import concurrent.futures
import os
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.court import Court
from app.models.pricing_rules import PricingRule
from app.models.recurring_series import RecurringSeries
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:123456@localhost:5432/court_booking_service_test_db",
)
real_engine = create_engine(TEST_DATABASE_URL)


def test_concurrent_recurring_bookings_overlapping_court():
    """Concurrency Test:

    Two distinct users simultaneously attempt to create weekly recurring bookings
    for the exact same court and time slot.
    Expected:
    - Exactly one user succeeds with 201 Created.
    - The other user receives 409 Conflict.
    - PostgreSQL exclusion constraint on reservations / holds guarantees no double booking.
    """
    with Session(real_engine) as session:
        u1 = User(
            full_name="Recurring User 1",
            email=f"rec_u1_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw123"),
            role="MEMBER",
            is_active=True,
        )
        u2 = User(
            full_name="Recurring User 2",
            email=f"rec_u2_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw123"),
            role="MEMBER",
            is_active=True,
        )
        session.add(u1)
        session.add(u2)
        session.flush()

        venue = Venue(
            name=f"Conc Rec Venue {uuid.uuid4().hex[:6]}",
            address="100 Concurrency Ave",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(23, 0),
            is_active=True,
        )
        session.add(venue)
        session.flush()

        court = Court(
            venue_id=venue.id,
            name=f"Conc Rec Court {uuid.uuid4().hex[:6]}",
            sport_type="Tennis",
            is_active=True,
        )
        session.add(court)
        session.flush()

        rule = PricingRule(
            court_id=court.id,
            pricing_type="OFF_PEAK",
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
            hourly_rate=Decimal("500.00"),
            currency="ETB",
            effective_from=datetime.now(UTC).date() - timedelta(days=5),
            is_active=True,
        )
        session.add(rule)
        session.commit()

        u1_id = u1.id
        u2_id = u2.id
        court_id = court.id

    token1 = create_access_token({"sub": str(u1_id), "role": "MEMBER"})
    token2 = create_access_token({"sub": str(u2_id), "role": "MEMBER"})
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    def override_get_db():
        with Session(real_engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    now = datetime.now(UTC)
    start_date = (now + timedelta(days=7)).date()
    end_date = start_date + timedelta(days=7)  # 2 occurrences

    payload = {
        "court_id": str(court_id),
        "day_of_week": start_date.weekday(),
        "start_time": "14:00:00",
        "end_time": "15:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    try:
        def make_request(headers):
            test_client = TestClient(app)
            return test_client.post(
                "/recurring-bookings",
                headers=headers,
                json=payload,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(make_request, headers1)
            fut2 = executor.submit(make_request, headers2)
            resp1 = fut1.result()
            resp2 = fut2.result()

        status_codes = sorted([resp1.status_code, resp2.status_code])
        assert status_codes == [201, 409], f"Expected [201, 409], got {status_codes}"

        with Session(real_engine) as session:
            series_list = list(
                session.scalars(
                    select(RecurringSeries).where(RecurringSeries.court_id == court_id)
                ).all()
            )
            assert len(series_list) == 1
    finally:
        app.dependency_overrides.clear()


def test_concurrent_recurring_bookings_cannot_bypass_booking_limit():
    """Concurrency Test:

    A single member with 2 existing active reservations sends 2 simultaneous
    requests to create 1-occurrence recurring bookings on different courts.
    Expected:
    - Member lock serializes the operations.
    - Exactly one request succeeds with 201 Created (total reaches 3).
    - The other request fails with 409 Conflict.
    - Total active future reservations for the member in PostgreSQL never exceeds 3.
    """
    with Session(real_engine) as session:
        user = User(
            full_name="Limit Conc User",
            email=f"lim_conc_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw123"),
            role="MEMBER",
            is_active=True,
        )
        session.add(user)
        session.flush()
        user_id = user.id

        venue = Venue(
            name=f"Limit Conc Venue {uuid.uuid4().hex[:6]}",
            address="200 Concurrency Ave",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(23, 0),
            is_active=True,
        )
        session.add(venue)
        session.flush()

        # Create 3 courts
        courts = []
        for i in range(3):
            c = Court(
                venue_id=venue.id,
                name=f"Limit Court {i + 1}_{uuid.uuid4().hex[:4]}",
                sport_type="Tennis",
                is_active=True,
            )
            session.add(c)
            courts.append(c)
        session.flush()

        # Add 2 existing active reservations for this user on court 0
        now = datetime.now(UTC)
        for i in range(2):
            res = Reservation(
                user_id=user_id,
                court_id=courts[0].id,
                start_at=now + timedelta(days=2, hours=i * 2),
                end_at=now + timedelta(days=2, hours=i * 2 + 1),
                status="CONFIRMED",
                expires_at=None,
            )
            session.add(res)

        session.commit()
        court_ids = [c.id for c in courts]

    token = create_access_token({"sub": str(user_id), "role": "MEMBER"})
    headers = {"Authorization": f"Bearer {token}"}

    def override_get_db():
        with Session(real_engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    start_date = (now + timedelta(days=7)).date()
    # End date equals start date -> exactly 1 occurrence per request
    end_date = start_date

    payload1 = {
        "court_id": str(court_ids[1]),
        "day_of_week": start_date.weekday(),
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }
    payload2 = {
        "court_id": str(court_ids[2]),
        "day_of_week": start_date.weekday(),
        "start_time": "14:00:00",
        "end_time": "15:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    try:
        def send_request(p):
            test_client = TestClient(app)
            return test_client.post("/recurring-bookings", headers=headers, json=p)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(send_request, payload1)
            fut2 = executor.submit(send_request, payload2)
            resp1 = fut1.result()
            resp2 = fut2.result()

        status_codes = sorted([resp1.status_code, resp2.status_code])
        assert status_codes == [201, 409], f"Expected [201, 409], got {status_codes}"

        # Verify in DB: active reservations for user = exactly 3
        with Session(real_engine) as session:
            from app.services.booking_limit_service import BookingLimitService
            active_count = BookingLimitService.count_active_future_reservations(session, user_id)
            assert active_count == 3
    finally:
        app.dependency_overrides.clear()
