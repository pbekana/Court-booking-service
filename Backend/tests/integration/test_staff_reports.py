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


def _seed_booking(
    db_session: Session,
    user: User,
    court: Court,
    start_at: datetime,
    end_at: datetime,
    *,
    booking_status: str = "CONFIRMED",
) -> Booking:
    res = Reservation(
        user_id=user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        status=booking_status,
        expires_at=None,
    )
    db_session.add(res)
    db_session.flush()

    hold = Hold(
        user_id=user.id,
        court_id=court.id,
        reservation_id=res.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=start_at,
        status=booking_status,
    )
    db_session.add(hold)
    db_session.flush()

    booking = Booking(
        hold_id=hold.id,
        reservation_id=res.id,
        user_id=user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        total_price=Decimal("100.00"),
        status=booking_status,
        cancelled_at=start_at - timedelta(days=1) if booking_status == "CANCELLED" else None,
    )
    db_session.add(booking)
    return booking


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
    - Default date range resolves to the current Monday-Sunday week in venue timezone.
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

    tz = ZoneInfo(test_venue.timezone)
    today_local = datetime.now(UTC).astimezone(tz).date()
    week_monday = today_local - timedelta(days=today_local.weekday())
    week_sunday = week_monday + timedelta(days=6)

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


def test_staff_reports_period_boundary_clipping_and_non_7_day_period(
    client: TestClient,
    staff_headers: dict[str, str],
    member_user: User,
    db_session: Session,
) -> None:
    """Verifies:
    - Bookings crossing the start boundary of the reporting period are clipped.
    - Bookings crossing the end boundary of the reporting period are clipped.
    - Non-7-day reporting periods calculate operating hours for the requested days only.
    """
    venue = Venue(
        name=f"Boundary Venue {uuid.uuid4().hex[:6]}",
        address="10 Boundary Ave",
        timezone="UTC",
        opening_time=time(0, 0),
        closing_time=time(22, 0),  # 22 hours/day
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Boundary Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    period_start = date(2026, 7, 1)
    period_end = date(2026, 7, 3)  # 3 days -> 3 * 22 = 66.00 operating hours

    # Crosses start boundary: 2026-06-30 21:00Z -> 2026-07-01 02:00Z (only 2h inside period)
    _seed_booking(
        db_session,
        member_user,
        court,
        datetime(2026, 6, 30, 21, 0, tzinfo=UTC),
        datetime(2026, 7, 1, 2, 0, tzinfo=UTC),
    )

    # Crosses end boundary: 2026-07-03 20:00Z -> 2026-07-04 02:00Z (only 2h inside period)
    _seed_booking(
        db_session,
        member_user,
        court,
        datetime(2026, 7, 3, 20, 0, tzinfo=UTC),
        datetime(2026, 7, 4, 2, 0, tzinfo=UTC),
    )
    db_session.commit()

    res = client.get(
        "/staff/reports/utilization",
        params={
            "venue_id": str(venue.id),
            "court_id": str(court.id),
            "start_date": period_start.isoformat(),
            "end_date": period_end.isoformat(),
        },
        headers=staff_headers,
    )
    assert res.status_code == 200
    data = res.json()
    court_rep = data["courts"][0]
    assert Decimal(str(court_rep["total_operating_hours"])) == Decimal("66.00")
    assert Decimal(str(court_rep["total_booked_hours"])) == Decimal("4.00")
    assert Decimal(str(court_rep["total_available_hours"])) == Decimal("62.00")
    # (4 / 66) * 100 = 6.0606... -> 6.06%
    assert Decimal(str(court_rep["utilization_percentage"])) == Decimal("6.06")
    assert court_rep["confirmed_bookings_count"] == 2


def test_staff_reports_different_venue_timezones_and_dst(
    client: TestClient,
    admin_headers: dict[str, str],
    member_user: User,
    db_session: Session,
) -> None:
    """Verifies:
    - UTC timestamps are evaluated in the venue's configured timezone.
    - DST spring-forward transitions adjust operating hours accurately.
    """
    ny_tz = ZoneInfo("America/New_York")
    venue = Venue(
        name=f"NY Venue {uuid.uuid4().hex[:6]}",
        address="500 5th Ave",
        timezone="America/New_York",
        opening_time=time(1, 0),
        closing_time=time(5, 0),  # 4h normal day, 3h on spring-forward DST day
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"NY Court {uuid.uuid4().hex[:6]}",
        sport_type="Squash",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    # 2026-03-08 is US DST spring-forward (02:00 -> 03:00 in America/New_York).
    # Opening 01:00 EST (06:00Z) to 05:00 EDT (09:00Z) = 3.00 hours!
    dst_day = date(2026, 3, 8)
    # Also seed a booking at 2026-03-08 04:00Z (= 2026-03-07 23:00 EST local time),
    # which is on March 7 in NY even though its UTC date is March 8.
    _seed_booking(
        db_session,
        member_user,
        court,
        datetime(2026, 3, 8, 4, 0, tzinfo=UTC),
        datetime(2026, 3, 8, 5, 0, tzinfo=UTC),
    )
    # Seed a 1.5h booking inside March 8 local operating window (03:00 EDT - 04:30 EDT = 07:00Z - 08:30Z)
    b_start = datetime(2026, 3, 8, 3, 0, tzinfo=ny_tz).astimezone(UTC)
    b_end = datetime(2026, 3, 8, 4, 30, tzinfo=ny_tz).astimezone(UTC)
    _seed_booking(db_session, member_user, court, b_start, b_end)
    db_session.commit()

    res = client.get(
        "/api/v1/staff/reports/utilization",
        params={
            "venue_id": str(venue.id),
            "start_date": dst_day.isoformat(),
            "end_date": dst_day.isoformat(),
        },
        headers=admin_headers,
    )
    assert res.status_code == 200
    court_rep = res.json()["courts"][0]
    assert Decimal(str(court_rep["total_operating_hours"])) == Decimal("3.00")
    assert Decimal(str(court_rep["total_booked_hours"])) == Decimal("1.50")
    assert Decimal(str(court_rep["utilization_percentage"])) == Decimal("50.00")
    assert court_rep["confirmed_bookings_count"] == 1


def test_staff_reports_invalid_venue_timezone_returns_error(
    client: TestClient,
    staff_headers: dict[str, str],
    db_session: Session,
) -> None:
    """Verifies invalid venue timezone configuration is rejected with 422 rather than silently falling back."""
    bad_venue = Venue(
        name=f"Bad TZ Venue {uuid.uuid4().hex[:6]}",
        address="Invalid TZ Rd",
        timezone="Mars/Olympus_Mons",
        opening_time=time(8, 0),
        closing_time=time(18, 0),
        is_active=True,
    )
    db_session.add(bad_venue)
    db_session.flush()

    bad_court = Court(
        venue_id=bad_venue.id,
        name=f"Bad TZ Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(bad_court)
    db_session.commit()

    res_venue = client.get(
        "/staff/reports/utilization",
        params={"venue_id": str(bad_venue.id)},
        headers=staff_headers,
    )
    assert res_venue.status_code == 422
    assert "timezone" in res_venue.json()["detail"].lower()

    res_court = client.get(
        "/staff/reports/utilization",
        params={"court_id": str(bad_court.id)},
        headers=staff_headers,
    )
    assert res_court.status_code == 422
    assert "timezone" in res_court.json()["detail"].lower()


def test_staff_reports_bookings_outside_operating_hours_excluded(
    client: TestClient,
    staff_headers: dict[str, str],
    member_user: User,
    db_session: Session,
) -> None:
    """Verifies:
    - Bookings completely outside venue operating hours do not inflate utilization.
    - Bookings partially overlapping operating hours only count the overlapping portion.
    """
    venue = Venue(
        name=f"OpHours Venue {uuid.uuid4().hex[:6]}",
        address="40 Hours Rd",
        timezone="UTC",
        opening_time=time(8, 0),
        closing_time=time(18, 0),  # 10 hours/day
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"OpHours Court {uuid.uuid4().hex[:6]}",
        sport_type="Basketball",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    day = date(2026, 8, 10)  # Single day -> 10.00 operating hours

    # Completely outside operating hours: 19:00 - 21:00 (2h outside)
    _seed_booking(
        db_session,
        member_user,
        court,
        datetime(2026, 8, 10, 19, 0, tzinfo=UTC),
        datetime(2026, 8, 10, 21, 0, tzinfo=UTC),
    )
    # Partially overlapping: 07:00 - 10:00 (only 08:00 - 10:00 = 2h inside operating hours)
    _seed_booking(
        db_session,
        member_user,
        court,
        datetime(2026, 8, 10, 7, 0, tzinfo=UTC),
        datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
    )
    db_session.commit()

    res = client.get(
        "/staff/reports/utilization",
        params={
            "venue_id": str(venue.id),
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
        },
        headers=staff_headers,
    )
    assert res.status_code == 200
    court_rep = res.json()["courts"][0]
    assert Decimal(str(court_rep["total_operating_hours"])) == Decimal("10.00")
    assert Decimal(str(court_rep["total_booked_hours"])) == Decimal("2.00")
    assert Decimal(str(court_rep["utilization_percentage"])) == Decimal("20.00")
    assert court_rep["confirmed_bookings_count"] == 1


def test_staff_reports_inactive_courts_and_venues(
    client: TestClient,
    staff_headers: dict[str, str],
    db_session: Session,
) -> None:
    """Verifies inactive courts and inactive venues are excluded from active utilization reports."""
    active_venue = Venue(
        name=f"Active Venue {uuid.uuid4().hex[:6]}",
        address="1 Active St",
        timezone="UTC",
        opening_time=time(8, 0),
        closing_time=time(18, 0),
        is_active=True,
    )
    inactive_venue = Venue(
        name=f"Inactive Venue {uuid.uuid4().hex[:6]}",
        address="2 Inactive St",
        timezone="UTC",
        opening_time=time(8, 0),
        closing_time=time(18, 0),
        is_active=False,
    )
    db_session.add_all([active_venue, inactive_venue])
    db_session.flush()

    active_court = Court(
        venue_id=active_venue.id,
        name=f"Active Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    inactive_court = Court(
        venue_id=active_venue.id,
        name=f"Inactive Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=False,
    )
    court_in_inactive_venue = Court(
        venue_id=inactive_venue.id,
        name=f"Court In Inactive Venue {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add_all([active_court, inactive_court, court_in_inactive_venue])
    db_session.commit()

    # 1. Active venue report excludes inactive_court
    res_active_venue = client.get(
        "/staff/reports/utilization",
        params={"venue_id": str(active_venue.id), "start_date": "2026-09-07", "end_date": "2026-09-07"},
        headers=staff_headers,
    )
    assert res_active_venue.status_code == 200
    data_av = res_active_venue.json()
    assert data_av["total_courts"] == 1
    assert [c["court_id"] for c in data_av["courts"]] == [str(active_court.id)]

    # 2. Inactive venue report returns 200 with 0 active courts
    res_inactive_venue = client.get(
        "/staff/reports/utilization",
        params={"venue_id": str(inactive_venue.id)},
        headers=staff_headers,
    )
    assert res_inactive_venue.status_code == 200
    data_iv = res_inactive_venue.json()
    assert data_iv["total_courts"] == 0
    assert data_iv["courts"] == []
    assert Decimal(str(data_iv["total_operating_hours"])) == Decimal("0.00")

    # 3. Inactive court filter returns 200 with 0 active courts
    res_inactive_court = client.get(
        "/staff/reports/utilization",
        params={"court_id": str(inactive_court.id)},
        headers=staff_headers,
    )
    assert res_inactive_court.status_code == 200
    assert res_inactive_court.json()["total_courts"] == 0


def test_staff_reports_empty_venue_and_zero_operating_hours(
    client: TestClient,
    staff_headers: dict[str, str],
    db_session: Session,
) -> None:
    """Verifies:
    - An active venue with no courts returns an empty valid report with 0.00% utilization.
    - Zero operating hours never raise division-by-zero errors (both via API empty periods
      and directly in the utilization calculation helpers).
    """
    from app.services.utilization_service import (
        _build_operating_windows,
        _calculate_utilization_percentage,
    )

    empty_venue = Venue(
        name=f"Empty Venue {uuid.uuid4().hex[:6]}",
        address="0 Courts Way",
        timezone="UTC",
        opening_time=time(8, 0),
        closing_time=time(18, 0),
        is_active=True,
    )
    db_session.add(empty_venue)
    db_session.commit()

    empty_res = client.get(
        "/staff/reports/utilization",
        params={"venue_id": str(empty_venue.id)},
        headers=staff_headers,
    )
    assert empty_res.status_code == 200
    empty_data = empty_res.json()
    assert empty_data["total_courts"] == 0
    assert empty_data["courts"] == []
    assert Decimal(str(empty_data["total_operating_hours"])) == Decimal("0.00")
    assert Decimal(str(empty_data["total_booked_hours"])) == Decimal("0.00")
    assert Decimal(str(empty_data["total_available_hours"])) == Decimal("0.00")
    assert Decimal(str(empty_data["overall_utilization_percentage"])) == Decimal("0.00")

    # Direct division-by-zero protection verification for zero-hour schedules
    windows, op_seconds = _build_operating_windows(
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
        opening_time=time(8, 0),
        closing_time=time(8, 0),
        venue_tz=ZoneInfo("UTC"),
        period_start_utc=datetime(2026, 9, 14, 0, 0, tzinfo=UTC),
        period_end_utc=datetime(2026, 9, 15, 0, 0, tzinfo=UTC),
    )
    assert windows == []
    assert op_seconds == Decimal(0)
    assert _calculate_utilization_percentage(Decimal(3600), op_seconds) == Decimal("0.00")


def test_staff_reports_multi_court_weighted_utilization_percentages(
    client: TestClient,
    admin_headers: dict[str, str],
    member_user: User,
    db_session: Session,
) -> None:
    """Verifies per-court and overall utilization percentages across multiple courts."""
    venue = Venue(
        name=f"Weighted Venue {uuid.uuid4().hex[:6]}",
        address="99 Multi Court Blvd",
        timezone="UTC",
        opening_time=time(8, 0),
        closing_time=time(18, 0),  # 10 hours/day
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court_a = Court(
        venue_id=venue.id,
        name=f"A-Court {uuid.uuid4().hex[:4]}",
        sport_type="Tennis",
        is_active=True,
    )
    court_b = Court(
        venue_id=venue.id,
        name=f"B-Court {uuid.uuid4().hex[:4]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add_all([court_a, court_b])
    db_session.flush()

    # 2 days -> 20.00 operating hours per court, 40.00 total operating hours
    # Court A: 5h confirmed + 2h cancelled -> 5.00 booked hours (25.00%)
    _seed_booking(
        db_session,
        member_user,
        court_a,
        datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
        datetime(2026, 10, 5, 14, 0, tzinfo=UTC),
    )
    _seed_booking(
        db_session,
        member_user,
        court_a,
        datetime(2026, 10, 6, 9, 0, tzinfo=UTC),
        datetime(2026, 10, 6, 11, 0, tzinfo=UTC),
        booking_status="CANCELLED",
    )
    # Court B: 10h confirmed -> 10.00 booked hours (50.00%)
    _seed_booking(
        db_session,
        member_user,
        court_b,
        datetime(2026, 10, 5, 8, 0, tzinfo=UTC),
        datetime(2026, 10, 5, 18, 0, tzinfo=UTC),
    )
    db_session.commit()

    res = client.get(
        "/api/v1/staff/reports/utilization",
        params={
            "venue_id": str(venue.id),
            "start_date": "2026-10-05",
            "end_date": "2026-10-06",
        },
        headers=admin_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_courts"] == 2
    assert Decimal(str(data["total_operating_hours"])) == Decimal("40.00")
    assert Decimal(str(data["total_booked_hours"])) == Decimal("15.00")
    assert Decimal(str(data["total_available_hours"])) == Decimal("25.00")
    # (15 / 40) * 100 = 37.50%
    assert Decimal(str(data["overall_utilization_percentage"])) == Decimal("37.50")

    by_id = {c["court_id"]: c for c in data["courts"]}
    assert Decimal(str(by_id[str(court_a.id)]["utilization_percentage"])) == Decimal("25.00")
    assert Decimal(str(by_id[str(court_b.id)]["utilization_percentage"])) == Decimal("50.00")
