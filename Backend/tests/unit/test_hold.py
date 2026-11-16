import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import HOLD_DURATION_MINUTES
from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.booking import Booking
from app.models.court import Court
from app.models.hold import Hold
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue
from tests.conftest import TEST_DATABASE_URL


def create_test_court(
    db_session: Session, is_active: bool = True, venue_is_active: bool = True
) -> Court:
    venue = Venue(
        name=f"Hold Test Venue {uuid.uuid4().hex[:6]}",
        address="123 Hold St",
        timezone="Africa/Addis_Ababa",
        opening_time=time(6, 0),
        closing_time=time(22, 0),
        is_active=venue_is_active,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=is_active,
    )
    db_session.add(court)
    db_session.commit()
    db_session.refresh(court)
    return court


# 1. Successful temporary hold creation
def test_successful_temporary_hold_creation(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=2)
    end_time = start_time + timedelta(hours=1)

    response = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["court_id"] == str(court.id)
    assert data["user_id"] == str(member_user.id)
    assert data["status"] == "ACTIVE"
    assert "expires_at" in data

    # Expiration is approximately now + HOLD_DURATION_MINUTES
    expires_at = datetime.fromisoformat(data["expires_at"])
    expected_expiry = datetime.now(UTC) + timedelta(minutes=HOLD_DURATION_MINUTES)
    assert abs((expires_at - expected_expiry).total_seconds()) < 60

    # Also test /api/v1/holds prefix works
    start_time2 = datetime.now(UTC) + timedelta(hours=4)
    end_time2 = start_time2 + timedelta(hours=1)
    response_v1 = client.post(
        "/api/v1/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time2.isoformat(),
            "end_time": end_time2.isoformat(),
        },
    )
    assert response_v1.status_code == 201


# 2. Hold creation for a nonexistent court
def test_hold_creation_nonexistent_court(
    client: TestClient, member_headers: dict[str, str]
):
    fake_court_id = str(uuid.uuid4())
    start_time = datetime.now(UTC) + timedelta(hours=2)
    end_time = start_time + timedelta(hours=1)

    response = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": fake_court_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert response.status_code == 404
    assert "Court not found" in response.json()["detail"]


# 3. Hold creation for an inactive court
def test_hold_creation_inactive_court(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    court = create_test_court(db_session, is_active=False)
    start_time = datetime.now(UTC) + timedelta(hours=2)
    end_time = start_time + timedelta(hours=1)

    response = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert response.status_code == 400
    assert "Court is inactive" in response.json()["detail"]


def test_hold_creation_inactive_venue(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    court = create_test_court(db_session, is_active=True, venue_is_active=False)
    start_time = datetime.now(UTC) + timedelta(hours=2)
    end_time = start_time + timedelta(hours=1)

    response = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert response.status_code == 400
    assert "inactive venue" in response.json()["detail"].lower()


# 4. Hold creation with invalid time ranges
def test_hold_creation_invalid_time_ranges(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=2)

    # end_time equal to start_time
    response_equal = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": start_time.isoformat(),
        },
    )
    assert response_equal.status_code == 400
    assert "End time must be later than start time" in response_equal.json()["detail"]

    # end_time before start_time
    response_before = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": (start_time - timedelta(minutes=30)).isoformat(),
        },
    )
    assert response_before.status_code == 400
    assert "End time must be later than start time" in response_before.json()["detail"]


# 5. Hold creation for a past time slot
def test_hold_creation_past_time_slot(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) - timedelta(hours=2)
    end_time = start_time + timedelta(hours=1)

    response = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert response.status_code == 400
    assert "Start time must be in the future" in response.json()["detail"]


# 6. Preventing overlapping active holds
def test_prevent_overlapping_active_holds(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
):
    court = create_test_court(db_session)
    base_start = datetime.now(UTC) + timedelta(days=1, hours=10)
    base_end = base_start + timedelta(hours=2)  # 10:00 - 12:00

    # Initial hold by Member 1
    resp1 = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": base_start.isoformat(),
            "end_time": base_end.isoformat(),
        },
    )
    assert resp1.status_code == 201

    # Overlap 1: 11:00 - 13:00 (overlaps end)
    overlap1 = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (base_start + timedelta(hours=1)).isoformat(),
            "end_time": (base_end + timedelta(hours=1)).isoformat(),
        },
    )
    assert overlap1.status_code == 409

    # Overlap 2: 09:00 - 11:00 (overlaps start)
    overlap2 = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (base_start - timedelta(hours=1)).isoformat(),
            "end_time": (base_start + timedelta(hours=1)).isoformat(),
        },
    )
    assert overlap2.status_code == 409

    # Overlap 3: 10:30 - 11:30 (fully enclosed)
    overlap3 = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (base_start + timedelta(minutes=30)).isoformat(),
            "end_time": (base_end - timedelta(minutes=30)).isoformat(),
        },
    )
    assert overlap3.status_code == 409

    # Non-overlapping adjacent slots should succeed
    # 08:00 - 10:00 (adjacent before)
    before_adj = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (base_start - timedelta(hours=2)).isoformat(),
            "end_time": base_start.isoformat(),
        },
    )
    assert before_adj.status_code == 201

    # 12:00 - 14:00 (adjacent after)
    after_adj = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": base_end.isoformat(),
            "end_time": (base_end + timedelta(hours=2)).isoformat(),
        },
    )
    assert after_adj.status_code == 201


# 7. Preventing holds that overlap confirmed bookings
def test_prevent_holds_overlapping_confirmed_bookings(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    member_user: User,
):
    court = create_test_court(db_session)
    booking_start = datetime.now(UTC) + timedelta(days=2, hours=14)
    booking_end = booking_start + timedelta(hours=2)

    # First, create an active hold to satisfy hold_id foreign key constraint
    dummy_hold = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=booking_start,
        end_time=booking_end,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        status="CONFIRMED",
    )
    db_session.add(dummy_hold)
    db_session.flush()

    booking = Booking(
        hold_id=dummy_hold.id,
        user_id=member_user.id,
        court_id=court.id,
        start_at=booking_start,
        end_at=booking_end,
        total_price=Decimal("50.00"),
        currency="ETB",
        status="CONFIRMED",
    )
    db_session.add(booking)
    db_session.commit()

    # Attempt to create hold overlapping confirmed booking
    overlap_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (booking_start + timedelta(minutes=30)).isoformat(),
            "end_time": (booking_end + timedelta(minutes=30)).isoformat(),
        },
    )
    assert overlap_resp.status_code == 409
    assert "conflicts with an existing confirmed booking" in overlap_resp.json()["detail"]


# 8. Successfully retrieving a hold
def test_successfully_retrieving_a_hold(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=3)
    end_time = start_time + timedelta(hours=1)

    create_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    hold_id = create_resp.json()["id"]

    get_resp = client.get(f"/holds/{hold_id}", headers=member_headers)
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["id"] == hold_id
    assert data["status"] == "ACTIVE"
    assert data["court_id"] == str(court.id)


# 9. Preventing members from accessing other members' holds
def test_prevent_members_from_accessing_other_members_holds(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=5)
    end_time = start_time + timedelta(hours=1)

    # Member 1 creates hold
    create_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    hold_id = create_resp.json()["id"]

    # Member 2 tries to GET hold -> 403
    get_resp = client.get(f"/holds/{hold_id}", headers=other_member_headers)
    assert get_resp.status_code == 403

    # Member 2 tries to CONFIRM hold -> 403
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=other_member_headers)
    assert confirm_resp.status_code == 403

    # Member 2 tries to DELETE hold -> 403
    delete_resp = client.delete(f"/holds/{hold_id}", headers=other_member_headers)
    assert delete_resp.status_code == 403


# 10. Successfully confirming an active hold
def test_successfully_confirming_active_hold(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=6)
    end_time = start_time + timedelta(hours=1)

    create_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    hold_id = create_resp.json()["id"]

    # Confirm hold
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    booking_data = confirm_resp.json()
    assert booking_data["hold_id"] == hold_id
    assert booking_data["court_id"] == str(court.id)
    assert booking_data["user_id"] == str(member_user.id)
    assert booking_data["status"] == "CONFIRMED"

    # Hold status in DB should now be CONFIRMED
    hold_in_db = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold_in_db is not None
    assert hold_in_db.status == "CONFIRMED"


# 11. Rejecting confirmation of an expired hold
def test_reject_confirming_expired_hold(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=7)
    end_time = start_time + timedelta(hours=1)

    # Manually create hold that has expired
    expired_hold = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=start_time,
        end_time=end_time,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        status="ACTIVE",
    )
    db_session.add(expired_hold)
    db_session.commit()

    confirm_resp = client.post(f"/holds/{expired_hold.id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 400
    assert "expired" in confirm_resp.json()["detail"].lower()


# 12. Rejecting confirmation of a cancelled hold
def test_reject_confirming_cancelled_hold(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=8)
    end_time = start_time + timedelta(hours=1)

    create_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    hold_id = create_resp.json()["id"]

    # Cancel hold
    cancel_resp = client.delete(f"/holds/{hold_id}", headers=member_headers)
    assert cancel_resp.status_code == 200

    # Attempt to confirm cancelled hold -> 400
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 400
    assert "cancelled" in confirm_resp.json()["detail"].lower()


# 13. Successfully cancelling an active hold
def test_successfully_cancelling_active_hold(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=9)
    end_time = start_time + timedelta(hours=1)

    create_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    hold_id = create_resp.json()["id"]

    cancel_resp = client.delete(f"/holds/{hold_id}", headers=member_headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    hold_in_db = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold_in_db is not None
    assert hold_in_db.status == "CANCELLED"


# 14. Releasing the time slot after cancellation
def test_releasing_time_slot_after_cancellation(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=10)
    end_time = start_time + timedelta(hours=1)

    # Member 1 creates hold
    create_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    hold_id = create_resp.json()["id"]

    # Member 2 tries to hold same slot -> 409
    conflict_resp = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert conflict_resp.status_code == 409

    # Member 1 cancels hold
    cancel_resp = client.delete(f"/holds/{hold_id}", headers=member_headers)
    assert cancel_resp.status_code == 200

    # Member 2 now can hold the exact same slot!
    success_resp = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert success_resp.status_code == 201
    assert success_resp.json()["status"] == "ACTIVE"


# 15. Automatic expiration handling
def test_automatic_expiration_handling(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    member_user: User,
    other_member_headers: dict[str, str],
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=12)
    end_time = start_time + timedelta(hours=1)

    # Create hold with past expiration
    hold = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=start_time,
        end_time=end_time,
        expires_at=datetime.now(UTC) - timedelta(seconds=10),
        status="ACTIVE",
    )
    db_session.add(hold)
    db_session.commit()
    db_session.refresh(hold)

    # GET /holds/{id} triggers auto-expiration
    get_resp = client.get(f"/holds/{hold.id}", headers=member_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "EXPIRED"

    # Time slot is now available again for another member
    new_hold_resp = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert new_hold_resp.status_code == 201
    assert new_hold_resp.json()["status"] == "ACTIVE"


# 16. Idempotent hold creation
def test_idempotent_hold_creation(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=14)
    end_time = start_time + timedelta(hours=1)
    key = f"key_{uuid.uuid4().hex}"

    # First request
    resp1 = client.post(
        "/holds",
        headers={**member_headers, "Idempotency-Key": key},
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert resp1.status_code == 201
    hold_id_1 = resp1.json()["id"]

    # Replay identical request with same key
    resp2 = client.post(
        "/holds",
        headers={**member_headers, "Idempotency-Key": key},
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert resp2.status_code in [200, 201]
    assert resp2.json()["id"] == hold_id_1

    # Request with same key but DIFFERENT parameters -> 409 Conflict
    diff_start = start_time + timedelta(hours=3)
    diff_end = diff_start + timedelta(hours=1)
    resp3 = client.post(
        "/holds",
        headers={**member_headers, "Idempotency-Key": key},
        json={
            "court_id": str(court.id),
            "start_time": diff_start.isoformat(),
            "end_time": diff_end.isoformat(),
        },
    )
    assert resp3.status_code == 409


# 17. Idempotent confirmation
def test_idempotent_confirmation(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    court = create_test_court(db_session)
    start_time = datetime.now(UTC) + timedelta(hours=18)
    end_time = start_time + timedelta(hours=1)

    create_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    hold_id = create_resp.json()["id"]

    # First confirmation
    confirm_resp1 = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp1.status_code == 200
    booking_id = confirm_resp1.json()["id"]

    # Retry confirmation
    confirm_resp2 = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp2.status_code == 200
    assert confirm_resp2.json()["id"] == booking_id

    # Verify in DB: only one booking exists for this hold
    bookings = db_session.scalars(select(Booking).where(Booking.hold_id == uuid.UUID(hold_id))).all()
    assert len(bookings) == 1


# 18. Concurrent requests attempting to hold the same time slot
def test_concurrent_hold_requests_same_slot(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-authentication")
    real_engine = create_engine(TEST_DATABASE_URL)

    with Session(real_engine) as session:
        # Create court and 2 users committed in test db
        venue = Venue(
            name=f"Concurrent Venue {uuid.uuid4().hex[:6]}",
            address="123 Conc St",
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

        u1 = User(
            full_name="Conc User 1",
            email=f"conc1_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        u2 = User(
            full_name="Conc User 2",
            email=f"conc2_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("pw"),
            role="MEMBER",
            is_active=True,
        )
        session.add(u1)
        session.add(u2)
        session.commit()

        venue_id = venue.id
        court_id = court.id
        u1_id = u1.id
        u2_id = u2.id

    t1 = create_access_token({"sub": str(u1_id), "role": "MEMBER"})
    t2 = create_access_token({"sub": str(u2_id), "role": "MEMBER"})

    start_time = datetime.now(UTC) + timedelta(days=5, hours=10)
    end_time = start_time + timedelta(hours=1)

    def attempt_hold(token: str) -> int:
        test_client = TestClient(app)
        resp = test_client.post(
            "/holds",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "court_id": str(court_id),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )
        return resp.status_code

    def override_get_db():
        with Session(real_engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(attempt_hold, t1)
            f2 = executor.submit(attempt_hold, t2)
            results = [f1.result(), f2.result()]

        # Exactly one request must succeed with 201, the other must be rejected with 409
        assert sorted(results) == [201, 409], f"Unexpected results: {results}"
    finally:
        app.dependency_overrides.clear()

    # Verify only 1 active hold in database
    with Session(real_engine) as session:
        holds = session.scalars(
            select(Hold).where(
                Hold.court_id == court_id,
                Hold.status == "ACTIVE",
            )
        ).all()
        assert len(holds) == 1

        # Cleanup test data from real_engine
        session.query(Hold).filter(Hold.court_id == court_id).delete()
        session.query(Reservation).filter(Reservation.court_id == court_id).delete()
        session.query(Court).filter(Court.id == court_id).delete()
        session.query(Venue).filter(Venue.id == venue_id).delete()
        session.query(User).filter(User.id.in_([u1_id, u2_id])).delete()
        session.commit()
