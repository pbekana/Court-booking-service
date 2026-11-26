import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.court import Court
from app.models.hold import Hold
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue


def test_staff_reports_authorization(
    client: TestClient,
    member_headers: dict[str, str],
    staff_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    """Verifies that:
    - Unauthenticated callers receive 401.
    - Members receive 403 Forbidden.
    - Staff receive 200 OK.
    - Admins receive 200 OK.
    """
    # 1. Unauthenticated
    assert client.get("/staff/reports/utilization").status_code == 401
    assert client.get("/api/v1/staff/reports/utilization").status_code == 401

    # 2. Member
    assert client.get("/staff/reports/utilization", headers=member_headers).status_code == 403
    assert client.get("/api/v1/staff/reports/utilization", headers=member_headers).status_code == 403

    # 3. Staff
    staff_res = client.get("/staff/reports/utilization", headers=staff_headers)
    assert staff_res.status_code == 200
    assert "total_operating_hours" in staff_res.json()

    # 4. Admin
    admin_res = client.get("/api/v1/staff/reports/utilization", headers=admin_headers)
    assert admin_res.status_code == 200


def test_weekly_utilization_calculation_and_exclusions(
    client: TestClient,
    staff_headers: dict[str, str],
    member_user: User,
    db_session: Session,
) -> None:
    """Creates a dedicated venue and court with known operating hours and bookings:
    - 7 days of 10-hour days (08:00 to 18:00) = 70.00 total operating hours.
    - 2 confirmed bookings of 2 hours each = 4.00 booked hours.
    - 1 cancelled booking of 2 hours = 0.00 booked hours (excluded).
    - 1 expired hold of 1 hour = 0.00 booked hours (excluded).
    - 1 active hold of 1 hour = reported separately under active_holds, not in booked hours.
    - Expected utilization percentage = (4.00 / 70.00) * 100 = 5.71%.
    """
    venue = Venue(
        name=f"Report Venue {uuid.uuid4().hex[:6]}",
        address="100 Report Way",
        timezone="Africa/Addis_Ababa",
        opening_time=time(8, 0),
        closing_time=time(18, 0),  # 10 hours per day
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Report Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    tz = ZoneInfo(venue.timezone)
    week_start = date(2026, 6, 1)  # Monday
    week_end = date(2026, 6, 7)    # Sunday (7 days total: 7 * 10h = 70.00 hours)

    # 1. Confirmed booking 1: Tuesday 10:00 - 12:00 (2 hours)
    tue_start = datetime.combine(date(2026, 6, 2), time(10, 0), tzinfo=tz).astimezone(UTC)
    tue_end = tue_start + timedelta(hours=2)

    res1 = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=tue_start,
        end_at=tue_end,
        status="CONFIRMED",
        expires_at=None,
    )
    db_session.add(res1)
    db_session.flush()
    h1 = Hold(
        user_id=member_user.id,
        court_id=court.id,
        reservation_id=res1.id,
        start_time=tue_start,
        end_time=tue_end,
        expires_at=tue_start,
        status="CONFIRMED",
    )
    db_session.add(h1)
    db_session.flush()
    b1 = Booking(
        hold_id=h1.id,
        reservation_id=res1.id,
        user_id=member_user.id,
        court_id=court.id,
        start_at=tue_start,
        end_at=tue_end,
        total_price=Decimal("100.00"),
        status="CONFIRMED",
    )
    db_session.add(b1)

    # 2. Confirmed booking 2: Thursday 14:00 - 16:00 (2 hours)
    thu_start = datetime.combine(date(2026, 6, 4), time(14, 0), tzinfo=tz).astimezone(UTC)
    thu_end = thu_start + timedelta(hours=2)

    res2 = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=thu_start,
        end_at=thu_end,
        status="CONFIRMED",
        expires_at=None,
    )
    db_session.add(res2)
    db_session.flush()
    h2 = Hold(
        user_id=member_user.id,
        court_id=court.id,
        reservation_id=res2.id,
        start_time=thu_start,
        end_time=thu_end,
        expires_at=thu_start,
        status="CONFIRMED",
    )
    db_session.add(h2)
    db_session.flush()
    b2 = Booking(
        hold_id=h2.id,
        reservation_id=res2.id,
        user_id=member_user.id,
        court_id=court.id,
        start_at=thu_start,
        end_at=thu_end,
        total_price=Decimal("100.00"),
        status="CONFIRMED",
    )
    db_session.add(b2)

    # 3. Cancelled booking: Wednesday 10:00 - 12:00 (must be excluded from utilization)
    wed_start = datetime.combine(date(2026, 6, 3), time(10, 0), tzinfo=tz).astimezone(UTC)
    wed_end = wed_start + timedelta(hours=2)
    res_canc = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=wed_start,
        end_at=wed_end,
        status="CANCELLED",
        expires_at=None,
    )
    db_session.add(res_canc)
    db_session.flush()
    h_canc = Hold(
        user_id=member_user.id,
        court_id=court.id,
        reservation_id=res_canc.id,
        start_time=wed_start,
        end_time=wed_end,
        expires_at=wed_start,
        status="CANCELLED",
    )
    db_session.add(h_canc)
    db_session.flush()
    b_canc = Booking(
        hold_id=h_canc.id,
        reservation_id=res_canc.id,
        user_id=member_user.id,
        court_id=court.id,
        start_at=wed_start,
        end_at=wed_end,
        total_price=Decimal("100.00"),
        status="CANCELLED",
        cancelled_at=wed_start - timedelta(days=1),
    )
    db_session.add(b_canc)

    # 4. Expired hold: Friday 09:00 - 10:00 (must be excluded)
    fri_start = datetime.combine(date(2026, 6, 5), time(9, 0), tzinfo=tz).astimezone(UTC)
    fri_end = fri_start + timedelta(hours=1)
    h_exp = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=fri_start,
        end_time=fri_end,
        expires_at=datetime.now(UTC) - timedelta(days=1),  # already expired
        status="EXPIRED",
    )
    db_session.add(h_exp)

    # 5. Active hold: Friday 11:00 - 12:00 (1 hour active hold, not counted as confirmed utilization)
    h_act = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=fri_start + timedelta(hours=2),
        end_time=fri_end + timedelta(hours=2),
        expires_at=datetime.now(UTC) + timedelta(days=100),  # future expiry
        status="ACTIVE",
    )
    db_session.add(h_act)

    db_session.commit()

    # Query report
    response = client.get(
        "/staff/reports/utilization",
        params={
            "venue_id": str(venue.id),
            "court_id": str(court.id),
            "start_date": week_start.isoformat(),
            "end_date": week_end.isoformat(),
        },
        headers=staff_headers,
    )
    assert response.status_code == 200
    report = response.json()
    assert report["total_courts"] == 1
    assert len(report["courts"]) == 1

    court_rep = report["courts"][0]
    assert court_rep["court_id"] == str(court.id)
    assert court_rep["venue_name"] == venue.name
    # 7 days * 10 hours = 70.00 operating hours
    assert Decimal(str(court_rep["total_operating_hours"])) == Decimal("70.00")
    # 2 confirmed bookings of 2 hours each = 4.00 booked hours
    assert Decimal(str(court_rep["total_booked_hours"])) == Decimal("4.00")
    # Available = 70 - 4 = 66.00
    assert Decimal(str(court_rep["total_available_hours"])) == Decimal("66.00")
    # (4.00 / 70.00) * 100 = 5.71%
    assert Decimal(str(court_rep["utilization_percentage"])) == Decimal("5.71")
    # Exactly 2 confirmed bookings
    assert court_rep["confirmed_bookings_count"] == 2
    # Active hold reported separately
    assert court_rep["active_holds_count"] == 1
    assert Decimal(str(court_rep["active_hold_hours"])) == Decimal("1.00")


def test_staff_reports_empty_week_and_multiple_courts(
    client: TestClient,
    staff_headers: dict[str, str],
    test_venue: Venue,
    db_session: Session,
) -> None:
    """Verifies:
    - Multiple courts reported under one venue.
    - A court with no bookings reports valid 0.00 booked hours and 0.00% utilization.
    - Overall summary aggregates across courts.
    """
    c1 = Court(
        venue_id=test_venue.id,
        name=f"Multi Court A {uuid.uuid4().hex[:4]}",
        sport_type="Tennis",
        is_active=True,
    )
    c2 = Court(
        venue_id=test_venue.id,
        name=f"Multi Court B {uuid.uuid4().hex[:4]}",
        sport_type="Squash",
        is_active=True,
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    week_start = date(2027, 1, 4)
    week_end = date(2027, 1, 10)

    response = client.get(
        "/staff/reports/utilization",
        params={
            "venue_id": str(test_venue.id),
            "start_date": week_start.isoformat(),
            "end_date": week_end.isoformat(),
        },
        headers=staff_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_courts"] >= 2
    assert Decimal(str(data["total_booked_hours"])) == Decimal("0.00")
    assert Decimal(str(data["overall_utilization_percentage"])) == Decimal("0.00")


def test_staff_reports_invalid_date_range_rejected(
    client: TestClient,
    staff_headers: dict[str, str],
) -> None:
    """Rejects end_date earlier than start_date with 400 Bad Request."""
    res = client.get(
        "/staff/reports/utilization",
        params={
            "start_date": "2026-06-10",
            "end_date": "2026-06-01",
        },
        headers=staff_headers,
    )
    assert res.status_code == 400
    assert "earlier than start_date" in res.json()["detail"].lower()


def test_staff_reports_nonexistent_filters_rejected(
    client: TestClient,
    staff_headers: dict[str, str],
) -> None:
    """Rejects queries for nonexistent venue or court with 404."""
    assert client.get(f"/staff/reports/utilization?venue_id={uuid.uuid4()}", headers=staff_headers).status_code == 404
    assert client.get(f"/staff/reports/utilization?court_id={uuid.uuid4()}", headers=staff_headers).status_code == 404


def test_staff_reports_mismatched_venue_and_court_and_unswept_expired_hold(
    client: TestClient,
    staff_headers: dict[str, str],
    member_user: User,
    test_venue: Venue,
    test_court: Court,
    db_session: Session,
) -> None:
    """Verifies:
    - Filtering by a court_id that does not belong to venue_id returns 400.
    - An un-swept expired hold (status='ACTIVE' with expires_at in the past) is excluded
      from both utilization and active holds.
    - Default date range resolves to the current Monday-Sunday week.
    """
    other_venue = Venue(
        name=f"Other Venue {uuid.uuid4().hex[:6]}",
        address="200 Other St",
        timezone="Africa/Addis_Ababa",
        opening_time=time(8, 0),
        closing_time=time(18, 0),
        is_active=True,
    )
    db_session.add(other_venue)
    db_session.flush()

    today = datetime.now(UTC).date()
    week_monday = today - timedelta(days=today.weekday())
    week_sunday = week_monday + timedelta(days=6)

    tz = ZoneInfo(test_venue.timezone)
    slot_start = datetime.combine(week_monday, time(10, 0), tzinfo=tz).astimezone(UTC)
    slot_end = slot_start + timedelta(hours=1)
    unswept_hold = Hold(
        user_id=member_user.id,
        court_id=test_court.id,
        start_time=slot_start,
        end_time=slot_end,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        status="ACTIVE",
    )
    db_session.add(unswept_hold)
    db_session.commit()

    # Mismatched venue_id and court_id
    mismatch_res = client.get(
        "/staff/reports/utilization",
        params={"venue_id": str(other_venue.id), "court_id": str(test_court.id)},
        headers=staff_headers,
    )
    assert mismatch_res.status_code == 400

    # Default current week report for test_court excludes un-swept expired hold
    default_res = client.get(
        "/api/v1/staff/reports/utilization",
        params={"court_id": str(test_court.id)},
        headers=staff_headers,
    )
    assert default_res.status_code == 200
    data = default_res.json()
    assert data["start_date"] == week_monday.isoformat()
    assert data["end_date"] == week_sunday.isoformat()
    assert data["total_courts"] == 1
    assert data["courts"][0]["active_holds_count"] == 0
    assert Decimal(str(data["courts"][0]["total_booked_hours"])) == Decimal("0.00")
