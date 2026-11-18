import concurrent.futures
import os
import uuid
from datetime import UTC, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.court import Court
from app.models.hold import Hold
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:123456@localhost:5432/court_booking_service_test_db",
)
real_engine = create_engine(TEST_DATABASE_URL)


def test_concurrent_holds_member_limit_enforcement():
    """Critical Concurrency Test:

    A member with two active future reservations sends two simultaneous requests
    to create new holds.
    Expected:
    - Exactly one request succeeds with 201 Created.
    - The other request receives HTTP 409 Conflict with the booking limit message.
    - The member has exactly 3 active future reservations in the database afterward.
    """
    with Session(real_engine) as session:
        # Create member user
        user = User(
            full_name="Concurrency Member",
            email=f"conc_member_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("password123"),
            role="MEMBER",
            is_active=True,
        )
        session.add(user)
        session.flush()
        user_id = user.id

        # Create venue
        venue = Venue(
            name=f"Concurrency Venue {uuid.uuid4().hex[:6]}",
            address="456 Concurrency Ave",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(23, 0),
            is_active=True,
        )
        session.add(venue)
        session.flush()

        # Create 4 distinct courts
        courts = []
        for i in range(4):
            c = Court(
                venue_id=venue.id,
                name=f"Conc Court {i + 1}_{uuid.uuid4().hex[:4]}",
                sport_type="Tennis",
                is_active=True,
            )
            session.add(c)
            courts.append(c)
        session.flush()

        # Create 2 active future reservations for this member on court 0 and court 1
        now = datetime.now(UTC)
        for i in range(2):
            res = Reservation(
                user_id=user_id,
                court_id=courts[i].id,
                start_at=now + timedelta(days=2, hours=i * 2),
                end_at=now + timedelta(days=2, hours=i * 2 + 1),
                status="CONFIRMED",
                expires_at=None,
            )
            session.add(res)
            session.flush()

            hold = Hold(
                user_id=user_id,
                court_id=courts[i].id,
                start_time=now + timedelta(days=2, hours=i * 2),
                end_time=now + timedelta(days=2, hours=i * 2 + 1),
                expires_at=now + timedelta(days=2),
                status="CONFIRMED",
                reservation_id=res.id,
            )
            session.add(hold)

        session.commit()

        venue_id = venue.id
        court_ids = [c.id for c in courts]

    token = create_access_token({"sub": str(user_id), "role": "MEMBER"})
    headers = {"Authorization": f"Bearer {token}"}

    def override_get_db():
        with Session(real_engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    try:
        # Request A targets Court 2, Request B targets Court 3
        # Start and end times are distinct, courts are distinct -> NO court collision
        start_a = now + timedelta(days=3, hours=10)
        end_a = start_a + timedelta(hours=1)

        start_b = now + timedelta(days=3, hours=12)
        end_b = start_b + timedelta(hours=1)

        def make_hold_request(court_id: uuid.UUID, start_time: datetime, end_time: datetime):
            test_client = TestClient(app)
            return test_client.post(
                "/holds",
                headers=headers,
                json={
                    "court_id": str(court_id),
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                },
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut_a = executor.submit(make_hold_request, court_ids[2], start_a, end_a)
            fut_b = executor.submit(make_hold_request, court_ids[3], start_b, end_b)
            resp_a = fut_a.result()
            resp_b = fut_b.result()

        status_codes = sorted([resp_a.status_code, resp_b.status_code])
        # Exactly one request must succeed (201), the other must be rejected (409)
        assert status_codes == [201, 409], f"Expected [201, 409], got {status_codes}"

        conflict_resp = resp_a if resp_a.status_code == 409 else resp_b
        conflict_data = conflict_resp.json()
        assert conflict_data["success"] is False
        assert "limit of 3" in conflict_data["message"]
        assert conflict_data["data"]["booking_limit"] == 3
        assert conflict_data["data"]["active_bookings"] == 3
        assert conflict_data["data"]["remaining_bookings"] == 0

        # Verify in database: the member has exactly THREE active reservations
        with Session(real_engine) as session:
            active_res = session.scalars(
                select(Reservation).where(
                    Reservation.user_id == user_id,
                    Reservation.status.in_(["HELD", "CONFIRMED"]),
                )
            ).all()
            assert len(active_res) == 3

    finally:
        app.dependency_overrides.clear()
        with Session(real_engine) as session:
            session.query(Hold).filter(Hold.user_id == user_id).delete()
            session.query(Reservation).filter(Reservation.user_id == user_id).delete()
            session.query(Court).filter(Court.id.in_(court_ids)).delete()
            session.query(Venue).filter(Venue.id == venue_id).delete()
            session.query(User).filter(User.id == user_id).delete()
            session.commit()
