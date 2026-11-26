import datetime
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.court import Court
from app.models.hold import Hold
from app.models.reservations import Reservation
from app.models.user import User


def test_court_availability_no_bookings(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
) -> None:
    # Query future 1-hour slot within operating hours
    # Venue timezone is Africa/Addis_Ababa, opening 06:00, closing 22:00
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    start_at = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    end_at = start_at + datetime.timedelta(hours=1)

    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["court_id"] == str(test_court.id)
    assert data["available"] is True
    assert "available" in data["message"].lower()


def test_court_availability_excludes_confirmed_booking(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    start_at = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    end_at = start_at + datetime.timedelta(hours=2)

    # Insert confirmed booking with reservation
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
        start_time=start_at,
        end_time=end_at,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15),
        status="CONFIRMED",
        reservation_id=res.id,
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
        total_price=Decimal("100.00"),
        status="CONFIRMED",
    )
    db_session.add(booking)
    db_session.commit()

    # Query overlapping time: 14:30 to 15:30
    check_start = start_at + datetime.timedelta(minutes=30)
    check_end = check_start + datetime.timedelta(hours=1)

    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": check_start.isoformat(), "end_at": check_end.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False
    assert "reserved" in data["message"].lower() or "not available" in data["message"].lower()


def test_court_availability_excludes_active_hold(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    start_at = tomorrow.replace(hour=16, minute=0, second=0, microsecond=0)
    end_at = start_at + datetime.timedelta(hours=1)

    # Active hold
    res = Reservation(
        user_id=member_user.id,
        court_id=test_court.id,
        start_at=start_at,
        end_at=end_at,
        status="HELD",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15),
    )
    db_session.add(res)
    db_session.flush()

    hold = Hold(
        user_id=member_user.id,
        court_id=test_court.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15),
        status="ACTIVE",
        reservation_id=res.id,
    )
    db_session.add(hold)
    db_session.commit()

    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_court_availability_expired_holds_become_available(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    start_at = tomorrow.replace(hour=11, minute=0, second=0, microsecond=0)
    end_at = start_at + datetime.timedelta(hours=1)

    # Stale hold that expired 5 minutes ago
    past_expiry = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)
    res = Reservation(
        user_id=member_user.id,
        court_id=test_court.id,
        start_at=start_at,
        end_at=end_at,
        status="HELD",
        expires_at=past_expiry,
    )
    db_session.add(res)
    db_session.flush()

    hold = Hold(
        user_id=member_user.id,
        court_id=test_court.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=past_expiry,
        status="ACTIVE",
        reservation_id=res.id,
    )
    db_session.add(hold)
    db_session.commit()

    # When availability is queried, expired holds are cleaned up and slot becomes available
    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 200
    assert response.json()["available"] is True


def test_court_availability_cancelled_reservation_does_not_block(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    start_at = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
    end_at = start_at + datetime.timedelta(hours=1)

    # Cancelled reservation
    res = Reservation(
        user_id=member_user.id,
        court_id=test_court.id,
        start_at=start_at,
        end_at=end_at,
        status="CANCELLED",
        expires_at=None,
    )
    db_session.add(res)
    db_session.commit()

    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 200
    assert response.json()["available"] is True


def test_court_availability_adjacent_slots_are_available(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    slot1_start = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
    slot1_end = slot1_start + datetime.timedelta(hours=1)  # 09:00 - 10:00

    # Booking at 09:00 - 10:00
    res = Reservation(
        user_id=member_user.id,
        court_id=test_court.id,
        start_at=slot1_start,
        end_at=slot1_end,
        status="CONFIRMED",
        expires_at=None,
    )
    db_session.add(res)
    db_session.commit()

    # Slot adjacent after: 10:00 - 11:00 (ends exactly when the other begins)
    slot2_start = slot1_end
    slot2_end = slot2_start + datetime.timedelta(hours=1)

    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": slot2_start.isoformat(), "end_at": slot2_end.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 200
    assert response.json()["available"] is True

    # Slot adjacent before: 08:00 - 09:00
    slot0_start = slot1_start - datetime.timedelta(hours=1)
    slot0_end = slot1_start

    response_before = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": slot0_start.isoformat(), "end_at": slot0_end.isoformat()},
        headers=member_headers,
    )
    assert response_before.status_code == 200
    assert response_before.json()["available"] is True


def test_court_availability_inactive_court(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    test_court.is_active = False
    db_session.commit()

    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    start_at = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    end_at = start_at + datetime.timedelta(hours=1)

    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False
    assert "inactive" in data["message"].lower()


def test_court_availability_nonexistent_court(
    client: TestClient,
    member_headers: dict[str, str],
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    start_at = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    end_at = start_at + datetime.timedelta(hours=1)

    response = client.get(
        f"/courts/{uuid.uuid4()}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 404
    assert "Court not found" in response.json()["detail"]


def test_court_availability_invalid_date_range(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    start_at = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    # End time before start time
    end_at = start_at - datetime.timedelta(hours=1)

    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 400
    assert "later than start time" in response.json()["detail"]


def test_court_availability_start_time_in_past(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    yesterday = datetime.datetime.now(tz) - datetime.timedelta(days=1)
    start_at = yesterday.replace(hour=10, minute=0, second=0, microsecond=0)
    end_at = start_at + datetime.timedelta(hours=1)

    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 400
    assert "future" in response.json()["detail"].lower()


def test_court_availability_outside_venue_operating_hours(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
) -> None:
    # Operating hours: 06:00 to 22:00
    # Query at 23:00 - 00:00
    tz = ZoneInfo("Africa/Addis_Ababa")
    tomorrow = datetime.datetime.now(tz) + datetime.timedelta(days=1)
    start_at = tomorrow.replace(hour=22, minute=30, second=0, microsecond=0)
    end_at = start_at + datetime.timedelta(hours=1)

    response = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert "operating hours" in response.json()["message"].lower()
