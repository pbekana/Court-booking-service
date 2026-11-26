import datetime
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import HOLD_DURATION_MINUTES
from app.models.booking import Booking
from app.models.court import Court
from app.models.hold import Hold
from app.models.reservations import Reservation
from app.models.user import User
from app.workers.hold_expiration import cleanup_expired_holds


def test_create_hold_success(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=2)
    start_time = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=1)

    payload = {
        "court_id": str(test_court.id),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
    }

    response = client.post("/holds", json=payload, headers=member_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["court_id"] == str(test_court.id)
    assert data["user_id"] == str(member_user.id)
    assert data["status"] == "ACTIVE"

    # Verify expiration timestamp is set to configured duration (15 min)
    created_at = datetime.datetime.fromisoformat(data["created_at"])
    expires_at = datetime.datetime.fromisoformat(data["expires_at"])
    duration = (expires_at - created_at).total_seconds() / 60
    assert abs(duration - HOLD_DURATION_MINUTES) < 1

    # Verify database record
    hold_db = db_session.get(Hold, uuid.UUID(data["id"]))
    assert hold_db is not None
    assert hold_db.status == "ACTIVE"
    assert hold_db.reservation is not None
    assert hold_db.reservation.status == "HELD"


def test_create_hold_rejects_overlapping_active_hold(
    client: TestClient,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
    test_court: Court,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=2)
    start_time = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=2)

    # First member holds 14:00 - 16:00
    res1 = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers=member_headers,
    )
    assert res1.status_code == 201

    # Second member attempts overlapping hold: 15:00 - 17:00
    res2 = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (start_time + datetime.timedelta(hours=1)).isoformat(),
            "end_time": (end_time + datetime.timedelta(hours=1)).isoformat(),
        },
        headers=other_member_headers,
    )
    assert res2.status_code == 409
    assert "conflict" in res2.json()["detail"].lower() or "not available" in res2.json()["detail"].lower()


def test_create_hold_rejects_overlapping_confirmed_booking(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    other_member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=2)
    start_time = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = start_time + datetime.timedelta(hours=1)

    # Create confirmed booking directly in DB
    res = Reservation(
        user_id=member_user.id,
        court_id=test_court.id,
        start_at=start_time,
        end_at=end_time,
        status="CONFIRMED",
        expires_at=None,
    )
    db_session.add(res)
    db_session.flush()

    hold = Hold(
        user_id=member_user.id,
        court_id=test_court.id,
        reservation_id=res.id,
        start_time=start_time,
        end_time=end_time,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15),
        status="CONFIRMED",
    )
    db_session.add(hold)
    db_session.flush()

    booking = Booking(
        hold_id=hold.id,
        reservation_id=res.id,
        user_id=member_user.id,
        court_id=test_court.id,
        start_at=start_time,
        end_at=end_time,
        total_price=Decimal("100.00"),
        status="CONFIRMED",
    )
    db_session.add(booking)
    db_session.commit()

    # Attempt to hold same slot
    resp = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers=other_member_headers,
    )
    assert resp.status_code == 409


def test_create_hold_rejects_inactive_or_nonexistent_court(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    start_time = now + datetime.timedelta(days=1)
    end_time = start_time + datetime.timedelta(hours=1)

    # Nonexistent court
    res_404 = client.post(
        "/holds",
        json={
            "court_id": str(uuid.uuid4()),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers=member_headers,
    )
    assert res_404.status_code == 404

    # Inactive court
    test_court.is_active = False
    db_session.commit()

    res_inactive = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers=member_headers,
    )
    assert res_inactive.status_code == 400
    assert "inactive" in res_inactive.json()["detail"].lower()


def test_create_hold_rejects_invalid_time_ranges(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
) -> None:
    now = datetime.datetime.now(datetime.UTC)

    # Past start time
    past_start = now - datetime.timedelta(hours=2)
    res_past = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": past_start.isoformat(),
            "end_time": (past_start + datetime.timedelta(hours=1)).isoformat(),
        },
        headers=member_headers,
    )
    assert res_past.status_code == 400
    assert "future" in res_past.json()["detail"].lower()

    # End time before start time
    future_start = now + datetime.timedelta(days=1)
    res_reversed = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": future_start.isoformat(),
            "end_time": (future_start - datetime.timedelta(hours=1)).isoformat(),
        },
        headers=member_headers,
    )
    assert res_reversed.status_code == 400
    assert "later than start time" in res_reversed.json()["detail"].lower()


def test_create_hold_unauthorized(
    client: TestClient,
    test_court: Court,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (now + datetime.timedelta(days=1)).isoformat(),
            "end_time": (now + datetime.timedelta(days=1, hours=1)).isoformat(),
        },
    )
    assert res.status_code == 401


def test_member_cannot_access_another_members_hold(
    client: TestClient,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
    test_court: Court,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    create_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (now + datetime.timedelta(days=3)).isoformat(),
            "end_time": (now + datetime.timedelta(days=3, hours=1)).isoformat(),
        },
        headers=member_headers,
    )
    assert create_res.status_code == 201
    hold_id = create_res.json()["id"]

    # Other member cannot view this hold
    get_res = client.get(f"/holds/{hold_id}", headers=other_member_headers)
    assert get_res.status_code == 403

    # Owner can view
    owner_get = client.get(f"/holds/{hold_id}", headers=member_headers)
    assert owner_get.status_code == 200
    assert owner_get.json()["id"] == hold_id


def test_hold_expiration_releases_court_and_prevents_confirmation(
    client: TestClient,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    slot_start = now + datetime.timedelta(days=4)
    slot_end = slot_start + datetime.timedelta(hours=1)

    # Member creates hold
    create_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": slot_start.isoformat(),
            "end_time": slot_end.isoformat(),
        },
        headers=member_headers,
    )
    assert create_res.status_code == 201
    hold_id = create_res.json()["id"]

    # Simulate expiration by modifying expires_at to 5 minutes ago in DB
    hold_db = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold_db is not None
    past_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)
    hold_db.expires_at = past_time
    if hold_db.reservation:
        hold_db.reservation.expires_at = past_time
    db_session.commit()

    # Background cleanup worker marks it expired
    cleanup_count = cleanup_expired_holds(db_session, court_id=test_court.id)
    assert cleanup_count >= 1

    # Attempting to confirm expired hold is rejected
    confirm_res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_res.status_code == 400
    assert "expired" in confirm_res.json()["detail"].lower()

    # Court slot is now available again for another member to hold
    new_hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": slot_start.isoformat(),
            "end_time": slot_end.isoformat(),
        },
        headers=other_member_headers,
    )
    assert new_hold_res.status_code == 201
    assert new_hold_res.json()["status"] == "ACTIVE"


def test_cancel_active_hold_releases_court(
    client: TestClient,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    slot_start = now + datetime.timedelta(days=5)
    slot_end = slot_start + datetime.timedelta(hours=1)

    create_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": slot_start.isoformat(),
            "end_time": slot_end.isoformat(),
        },
        headers=member_headers,
    )
    assert create_res.status_code == 201
    hold_id = create_res.json()["id"]

    # Member cancels their hold
    cancel_res = client.delete(f"/holds/{hold_id}", headers=member_headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # Database verification
    hold_db = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold_db is not None
    assert hold_db.status == "CANCELLED"
    if hold_db.reservation:
        assert hold_db.reservation.status == "CANCELLED"

    # Slot is released immediately
    new_hold = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": slot_start.isoformat(),
            "end_time": slot_end.isoformat(),
        },
        headers=other_member_headers,
    )
    assert new_hold.status_code == 201
