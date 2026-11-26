import concurrent.futures
import os
import threading
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.booking import Booking
from app.models.court import Court
from app.models.hold import Hold
from app.models.pricing_rules import PricingRule
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:123456@localhost:5432/court_booking_service_test_db",
)
real_engine = create_engine(TEST_DATABASE_URL)


def test_member_three_active_booking_limit_lifecycle(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_venue: Venue,
    db_session: Session,
) -> None:
    """Tests sequential creation of 1st, 2nd, 3rd bookings, rejection of 4th,
    and release of limit quota after cancellation and hold expiration.
    """
    # Create 4 distinct courts under venue so court availability doesn't conflict
    courts = []
    for i in range(4):
        c = Court(
            venue_id=test_venue.id,
            name=f"Limit Court {i} {uuid.uuid4().hex[:4]}",
            sport_type="Tennis",
            is_active=True,
        )
        db_session.add(c)
        db_session.flush()
        rule = PricingRule(
            court_id=c.id,
            pricing_type="PEAK",
            start_time=time(0, 0),
            end_time=time(23, 59, 59),
            hourly_rate=Decimal("100.00"),
            currency="ETB",
            effective_from=date(2025, 1, 1),
            effective_until=date(2035, 12, 31),
            is_active=True,
        )
        db_session.add(rule)
        courts.append(c)
    db_session.commit()

    now = datetime.now(UTC)
    start_time = now + timedelta(days=2)
    end_time = start_time + timedelta(hours=1)

    # 1. Check initial limit status (0 active, 3 remaining)
    limit_res = client.get("/members/me/booking-limit", headers=member_headers)
    assert limit_res.status_code == 200
    assert limit_res.json()["data"]["active_bookings"] == 0
    assert limit_res.json()["data"]["remaining_bookings"] == 3

    # 2. Create 1st hold & confirm
    h1 = client.post(
        "/holds",
        json={"court_id": str(courts[0].id), "start_time": start_time.isoformat(), "end_time": end_time.isoformat()},
        headers=member_headers,
    ).json()["id"]
    client.post(f"/holds/{h1}/confirm", headers=member_headers)

    limit_res1 = client.get("/members/me/booking-limit", headers=member_headers)
    assert limit_res1.json()["data"]["active_bookings"] == 1
    assert limit_res1.json()["data"]["remaining_bookings"] == 2

    # 3. Create 2nd hold & confirm
    h2 = client.post(
        "/holds",
        json={"court_id": str(courts[1].id), "start_time": start_time.isoformat(), "end_time": end_time.isoformat()},
        headers=member_headers,
    ).json()["id"]
    client.post(f"/holds/{h2}/confirm", headers=member_headers)

    # 4. Create 3rd hold & confirm
    h3 = client.post(
        "/holds",
        json={"court_id": str(courts[2].id), "start_time": start_time.isoformat(), "end_time": end_time.isoformat()},
        headers=member_headers,
    ).json()["id"]
    confirm3 = client.post(f"/holds/{h3}/confirm", headers=member_headers)
    assert confirm3.status_code == 200

    limit_res3 = client.get("/members/me/booking-limit", headers=member_headers)
    assert limit_res3.json()["data"]["active_bookings"] == 3
    assert limit_res3.json()["data"]["remaining_bookings"] == 0

    # 5. Attempt 4th hold -> Rejected with 409 BookingLimitExceededException
    h4_res = client.post(
        "/holds",
        json={"court_id": str(courts[3].id), "start_time": start_time.isoformat(), "end_time": end_time.isoformat()},
        headers=member_headers,
    )
    assert h4_res.status_code == 409
    assert "limit" in h4_res.json()["message"].lower() or "limit" in h4_res.json()["detail"].lower()

    # 6. Cancel 1st booking -> active count decreases to 2
    b1_id = client.get("/bookings", headers=member_headers).json()[0]["id"]
    client.post(f"/bookings/{b1_id}/cancel", headers=member_headers)

    limit_res_after_cancel = client.get("/members/me/booking-limit", headers=member_headers)
    assert limit_res_after_cancel.json()["data"]["active_bookings"] == 2
    assert limit_res_after_cancel.json()["data"]["remaining_bookings"] == 1

    # 7. Now 4th hold can be created successfully
    h4_retry = client.post(
        "/holds",
        json={"court_id": str(courts[3].id), "start_time": start_time.isoformat(), "end_time": end_time.isoformat()},
        headers=member_headers,
    )
    assert h4_retry.status_code == 201


def test_concurrent_booking_requests_do_not_bypass_limit() -> None:
    """Verifies that two concurrent requests cannot bypass the member limit
    when the member has only 1 remaining slot allowed.
    """
    with Session(real_engine) as session:
        user = User(
            full_name="Limit Concurrency User",
            email=f"limit_conc_{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        venue = Venue(
            name=f"Limit Venue {uuid.uuid4().hex[:6]}",
            address="Addr",
            timezone="Africa/Addis_Ababa",
            opening_time=time(6, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        session.add_all([user, venue])
        session.flush()

        court1 = Court(venue_id=venue.id, name=f"L-Court 1 {uuid.uuid4().hex[:4]}", sport_type="Tennis", is_active=True)
        court2 = Court(venue_id=venue.id, name=f"L-Court 2 {uuid.uuid4().hex[:4]}", sport_type="Tennis", is_active=True)
        court3 = Court(venue_id=venue.id, name=f"L-Court 3 {uuid.uuid4().hex[:4]}", sport_type="Tennis", is_active=True)
        session.add_all([court1, court2, court3])
        session.flush()

        session.add_all([
            PricingRule(
                court_id=c.id,
                pricing_type="PEAK",
                start_time=time(0, 0),
                end_time=time(23, 59, 59),
                hourly_rate=Decimal("100.00"),
                currency="ETB",
                effective_from=date(2025, 1, 1),
                effective_until=date(2035, 12, 31),
                is_active=True,
            )
            for c in [court1, court2, court3]
        ])

        now = datetime.now(UTC)
        start_time = now + timedelta(days=2)
        end_time = start_time + timedelta(hours=1)

        # Pre-create 2 confirmed bookings for this member (so active_bookings = 2, only 1 left!)
        for court in [court1, court2]:
            r = Reservation(
                user_id=user.id,
                court_id=court.id,
                start_at=start_time,
                end_at=end_time,
                status="CONFIRMED",
                expires_at=None,
            )
            session.add(r)
            session.flush()
            h = Hold(
                user_id=user.id,
                court_id=court.id,
                reservation_id=r.id,
                start_time=start_time,
                end_time=end_time,
                expires_at=start_time,
                status="CONFIRMED",
            )
            session.add(h)
            session.flush()
            b = Booking(
                hold_id=h.id,
                reservation_id=r.id,
                user_id=user.id,
                court_id=court.id,
                start_at=start_time,
                end_at=end_time,
                total_price=Decimal("100.00"),
                status="CONFIRMED",
            )
            session.add(b)

        session.commit()
        user_id = user.id
        venue_id = venue.id
        court3_id = court3.id
        court_ids = [court1.id, court2.id, court3.id]

    token = create_access_token({"sub": str(user_id), "role": "MEMBER"})
    headers = {"Authorization": f"Bearer {token}"}

    def override_get_db():
        with Session(real_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    barrier = threading.Barrier(2)

    try:
        # Two simultaneous requests for court3 at different future times
        slot_a_start = now + timedelta(days=3)
        slot_a_end = slot_a_start + timedelta(hours=1)
        slot_b_start = now + timedelta(days=4)
        slot_b_end = slot_b_start + timedelta(hours=1)

        def make_hold(start: datetime, end: datetime) -> tuple[int, dict[str, Any]]:
            barrier.wait()
            with TestClient(app) as test_client:
                res = test_client.post(
                    "/holds",
                    json={"court_id": str(court3_id), "start_time": start.isoformat(), "end_time": end.isoformat()},
                    headers=headers,
                )
                return res.status_code, res.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(make_hold, slot_a_start, slot_a_end)
            f2 = executor.submit(make_hold, slot_b_start, slot_b_end)
            r1 = f1.result()
            r2 = f2.result()

        status_codes = sorted([r1[0], r2[0]])
        # One request must succeed (201) and the other must be rejected (409) because limit was reached!
        assert status_codes == [201, 409], f"Results: {r1}, {r2}"

        with Session(real_engine) as session:
            active_holds = session.scalars(
                select(Hold).where(Hold.user_id == user_id, Hold.status == "ACTIVE")
            ).all()
            assert len(active_holds) == 1
    finally:
        app.dependency_overrides.clear()
        with Session(real_engine) as session:
            session.query(Booking).filter(Booking.court_id.in_(court_ids)).delete(synchronize_session=False)
            session.query(Hold).filter(Hold.court_id.in_(court_ids)).delete(synchronize_session=False)
            session.query(Reservation).filter(Reservation.court_id.in_(court_ids)).delete(synchronize_session=False)
            session.query(PricingRule).filter(PricingRule.court_id.in_(court_ids)).delete(synchronize_session=False)
            session.query(Court).filter(Court.id.in_(court_ids)).delete(synchronize_session=False)
            session.query(Venue).filter(Venue.id == venue_id).delete(synchronize_session=False)
            session.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            session.commit()
