import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.booking_ocurrences import BookingOccurrence
from app.models.court import Court
from app.models.hold import Hold
from app.models.pricing_rules import PricingRule
from app.models.recurring_series import RecurringSeries
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue


def create_venue_record(
    db: Session,
    name: str = "Test Arena",
    opening_time: time = time(6, 0),
    closing_time: time = time(22, 0),
    timezone: str = "Africa/Addis_Ababa",
    is_active: bool = True,
) -> Venue:
    venue = Venue(
        name=f"{name}_{uuid.uuid4().hex[:6]}",
        address="100 Court Way",
        timezone=timezone,
        opening_time=opening_time,
        closing_time=closing_time,
        is_active=is_active,
    )
    db.add(venue)
    db.commit()
    db.refresh(venue)
    return venue


def create_court_record(
    db: Session,
    venue_id: uuid.UUID,
    name: str = "Court 1",
    sport_type: str = "Tennis",
    is_active: bool = True,
) -> Court:
    court = Court(
        venue_id=venue_id,
        name=f"{name}_{uuid.uuid4().hex[:6]}",
        sport_type=sport_type,
        is_active=is_active,
    )
    db.add(court)
    db.commit()
    db.refresh(court)
    return court


def create_pricing_rule_record(
    db: Session,
    court_id: uuid.UUID,
    pricing_type: str = "OFF_PEAK",
    start_time: time = time(6, 0),
    end_time: time = time(22, 0),
    hourly_rate: Decimal = Decimal("500.00"),
    currency: str = "ETB",
    day_of_week: int | None = None,
    effective_from: date = date(2026, 1, 1),
    effective_until: date | None = None,
) -> PricingRule:
    rule = PricingRule(
        court_id=court_id,
        pricing_type=pricing_type,
        start_time=start_time,
        end_time=end_time,
        hourly_rate=hourly_rate,
        currency=currency,
        day_of_week=day_of_week,
        effective_from=effective_from,
        effective_until=effective_until,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


# -----------------------------------------------------------------------------
# 1. Basic Availability Tests
# -----------------------------------------------------------------------------


def test_active_court_no_reservations_is_available(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(db_session, court.id, hourly_rate=Decimal("500.00"))

    start_at = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    end_at = start_at + timedelta(hours=1)

    # Test /courts/{id}/availability
    response = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["court_id"] == str(court.id)
    assert data["venue_id"] == str(venue.id)
    assert data["available"] is True
    assert data["message"] == "Court is available for the requested time."
    assert "pricing" in data
    assert data["pricing"]["currency"] == "ETB"
    assert float(data["pricing"]["total_price"]) == 500.00
    assert len(data["pricing"]["segments"]) == 1

    # Test alias route /api/v1/courts/{id}/availability
    response_v1 = client.get(
        f"/api/v1/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )
    assert response_v1.status_code == 200
    assert response_v1.json() == data


def test_court_with_confirmed_booking_is_not_available(
    client: TestClient, db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(db_session, court.id)

    start_at = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    end_at = start_at + timedelta(hours=2)

    # Insert confirmed reservation
    reservation = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        status="CONFIRMED",
    )
    db_session.add(reservation)
    db_session.commit()

    # Query during booked time
    req_start = start_at + timedelta(minutes=30)
    req_end = req_start + timedelta(hours=1)
    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": req_start.isoformat(), "end_at": req_end.isoformat()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["court_id"] == str(court.id)
    assert data["available"] is False
    assert data["message"] == "Court is already reserved for the requested time."
    assert "pricing" not in data


def test_court_with_active_hold_is_not_available(
    client: TestClient, db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(db_session, court.id)

    start_at = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    end_at = start_at + timedelta(hours=1)
    expires_at = datetime.now(UTC) + timedelta(minutes=10)

    # Insert active hold with held reservation
    reservation = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        status="HELD",
        expires_at=expires_at,
    )
    db_session.add(reservation)
    db_session.flush()

    hold = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=expires_at,
        status="ACTIVE",
        reservation_id=reservation.id,
    )
    db_session.add(hold)
    db_session.commit()

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["message"] == "Court is already reserved for the requested time."


def test_court_with_recurring_occurrence_is_not_available(
    client: TestClient, db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(db_session, court.id)

    start_at = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    end_at = start_at + timedelta(hours=1)

    # Create recurring series, booking, and booking_occurrence
    series = RecurringSeries(
        user_id=member_user.id,
        court_id=court.id,
        day_of_week=start_at.weekday(),
        start_time=start_at.time(),
        end_time=end_at.time(),
        recurrence_start_date=start_at.date(),
        recurrence_end_date=start_at.date() + timedelta(days=28),
        status="ACTIVE",
    )
    db_session.add(series)
    db_session.flush()

    hold = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        status="CONFIRMED",
    )
    db_session.add(hold)
    db_session.flush()

    booking = Booking(
        hold_id=hold.id,
        user_id=member_user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        total_price=Decimal("500.00"),
        currency="ETB",
        status="CONFIRMED",
    )
    db_session.add(booking)
    db_session.flush()

    occurrence = BookingOccurrence(
        recurring_series_id=series.id,
        booking_id=booking.id,
        occurrence_date=start_at.date(),
        status="CONFIRMED",
    )
    db_session.add(occurrence)
    db_session.commit()

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )
    assert resp.status_code == 200
    assert resp.json()["available"] is False


def test_nonexistent_court_returns_404(client: TestClient):
    random_id = uuid.uuid4()
    start_at = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    end_at = (datetime.now(UTC) + timedelta(days=2, hours=1)).isoformat()

    resp = client.get(
        f"/courts/{random_id}/availability",
        params={"start_at": start_at, "end_at": end_at},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Court not found"


def test_inactive_court_returns_not_available(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id, is_active=False)

    start_at = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    end_at = (datetime.now(UTC) + timedelta(days=2, hours=1)).isoformat()

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at, "end_at": end_at},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["court_id"] == str(court.id)
    assert data["available"] is False
    assert data["message"] == "Court is inactive."


def test_inactive_venue_returns_not_available(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session, is_active=False)
    court = create_court_record(db_session, venue.id, is_active=True)

    start_at = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    end_at = (datetime.now(UTC) + timedelta(days=2, hours=1)).isoformat()

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at, "end_at": end_at},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["court_id"] == str(court.id)
    assert data["available"] is False
    assert data["message"] == "Venue is inactive."


# -----------------------------------------------------------------------------
# 2. Date and Time Validation Tests
# -----------------------------------------------------------------------------


def test_end_time_before_start_time_returns_400(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)

    start_at = datetime.now(UTC) + timedelta(days=2, hours=2)
    end_at = datetime.now(UTC) + timedelta(days=2, hours=1)

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "End time must be later than start time"


def test_start_time_equal_to_end_time_returns_400(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)

    start_at = datetime.now(UTC) + timedelta(days=2)

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": start_at.isoformat()},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "End time must be later than start time"


def test_past_reservation_returns_400(client: TestClient, db_session: Session):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)

    start_at = datetime.now(UTC) - timedelta(days=1)
    end_at = start_at + timedelta(hours=1)

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Reservation start time must be in the future"


def test_missing_timezone_returns_422(client: TestClient, db_session: Session):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={
            "start_at": "2026-11-20T09:00:00",  # Naive without tz
            "end_at": "2026-11-20T10:00:00+03:00",
        },
    )
    assert resp.status_code == 422


def test_reservation_outside_venue_operating_hours_returns_not_available(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(
        db_session,
        opening_time=time(8, 0),
        closing_time=time(20, 0),
        timezone="Africa/Addis_Ababa",
    )
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(
        db_session, court.id, start_time=time(6, 0), end_time=time(22, 0)
    )

    tz = ZoneInfo("Africa/Addis_Ababa")
    future_date = (datetime.now(tz) + timedelta(days=3)).date()

    # Early morning: 07:00 to 08:00 (venue opens at 08:00)
    start_at = datetime.combine(future_date, time(7, 0), tzinfo=tz)
    end_at = datetime.combine(future_date, time(8, 0), tzinfo=tz)

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["message"] == "Requested time falls outside venue operating hours."

    # Late night: 20:30 to 21:30 (venue closes at 20:00)
    start_night = datetime.combine(future_date, time(20, 30), tzinfo=tz)
    end_night = datetime.combine(future_date, time(21, 30), tzinfo=tz)

    resp_night = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_night.isoformat(), "end_at": end_night.isoformat()},
    )
    assert resp_night.status_code == 200
    assert resp_night.json()["available"] is False


def test_adjacent_reservations_are_available(
    client: TestClient, db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(db_session, court.id)

    tz = ZoneInfo("Africa/Addis_Ababa")
    target_date = (datetime.now(tz) + timedelta(days=2)).date()

    # Confirmed booking from 10:00 to 11:00
    book_start = datetime.combine(target_date, time(10, 0), tzinfo=tz)
    book_end = datetime.combine(target_date, time(11, 0), tzinfo=tz)
    res = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=book_start.astimezone(UTC),
        end_at=book_end.astimezone(UTC),
        status="CONFIRMED",
    )
    db_session.add(res)
    db_session.commit()

    # Check directly preceding adjacent interval: 09:00 to 10:00
    resp_before = client.get(
        f"/courts/{court.id}/availability",
        params={
            "start_at": datetime.combine(target_date, time(9, 0), tzinfo=tz).isoformat(),
            "end_at": book_start.isoformat(),
        },
    )
    assert resp_before.status_code == 200
    assert resp_before.json()["available"] is True

    # Check directly succeeding adjacent interval: 11:00 to 12:00
    resp_after = client.get(
        f"/courts/{court.id}/availability",
        params={
            "start_at": book_end.isoformat(),
            "end_at": datetime.combine(target_date, time(12, 0), tzinfo=tz).isoformat(),
        },
    )
    assert resp_after.status_code == 200
    assert resp_after.json()["available"] is True


def test_overlapping_reservations_are_not_available(
    client: TestClient, db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(db_session, court.id)

    tz = ZoneInfo("Africa/Addis_Ababa")
    target_date = (datetime.now(tz) + timedelta(days=2)).date()

    # Confirmed booking from 10:00 to 11:00
    book_start = datetime.combine(target_date, time(10, 0), tzinfo=tz)
    book_end = datetime.combine(target_date, time(11, 0), tzinfo=tz)
    res = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=book_start.astimezone(UTC),
        end_at=book_end.astimezone(UTC),
        status="CONFIRMED",
    )
    db_session.add(res)
    db_session.commit()

    # Overlaps start: 09:30 to 10:30
    resp1 = client.get(
        f"/courts/{court.id}/availability",
        params={
            "start_at": datetime.combine(target_date, time(9, 30), tzinfo=tz).isoformat(),
            "end_at": datetime.combine(target_date, time(10, 30), tzinfo=tz).isoformat(),
        },
    )
    assert resp1.status_code == 200
    assert resp1.json()["available"] is False

    # Overlaps end: 10:30 to 11:30
    resp2 = client.get(
        f"/courts/{court.id}/availability",
        params={
            "start_at": datetime.combine(target_date, time(10, 30), tzinfo=tz).isoformat(),
            "end_at": datetime.combine(target_date, time(11, 30), tzinfo=tz).isoformat(),
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["available"] is False

    # Enclosing: 09:00 to 12:00
    resp3 = client.get(
        f"/courts/{court.id}/availability",
        params={
            "start_at": datetime.combine(target_date, time(9, 0), tzinfo=tz).isoformat(),
            "end_at": datetime.combine(target_date, time(12, 0), tzinfo=tz).isoformat(),
        },
    )
    assert resp3.status_code == 200
    assert resp3.json()["available"] is False


# -----------------------------------------------------------------------------
# 3. Hold Expiration Tests
# -----------------------------------------------------------------------------


def test_active_hold_blocks_availability(
    client: TestClient, db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(db_session, court.id)

    start_at = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    end_at = start_at + timedelta(hours=1)
    future_exp = datetime.now(UTC) + timedelta(minutes=10)

    reservation = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        status="HELD",
        expires_at=future_exp,
    )
    db_session.add(reservation)
    db_session.flush()

    hold = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=future_exp,
        status="ACTIVE",
        reservation_id=reservation.id,
    )
    db_session.add(hold)
    db_session.commit()

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )
    assert resp.status_code == 200
    assert resp.json()["available"] is False


def test_expired_hold_does_not_block_and_updates_db(
    client: TestClient, db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(db_session, court.id)

    start_at = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    end_at = start_at + timedelta(hours=1)
    past_exp = datetime.now(UTC) - timedelta(minutes=5)

    reservation = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        status="HELD",
        expires_at=past_exp,
    )
    db_session.add(reservation)
    db_session.flush()

    hold = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=past_exp,
        status="ACTIVE",
        reservation_id=reservation.id,
    )
    db_session.add(hold)
    db_session.commit()

    # Availability endpoint runs cleanup_expired_holds in transaction
    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )
    assert resp.status_code == 200
    assert resp.json()["available"] is True

    # Verify database was updated
    db_session.refresh(hold)
    db_session.refresh(reservation)
    assert hold.status == "EXPIRED"
    assert reservation.status == "EXPIRED"
    assert reservation.expires_at is None  # Checked constraint requirement!


# -----------------------------------------------------------------------------
# 4. Pricing Tests
# -----------------------------------------------------------------------------


def test_peak_and_off_peak_pricing(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)

    # OFF_PEAK: 08:00 to 17:00 at 400.00
    create_pricing_rule_record(
        db_session,
        court.id,
        pricing_type="OFF_PEAK",
        start_time=time(8, 0),
        end_time=time(17, 0),
        hourly_rate=Decimal("400.00"),
    )
    # PEAK: 17:00 to 22:00 at 600.00
    create_pricing_rule_record(
        db_session,
        court.id,
        pricing_type="PEAK",
        start_time=time(17, 0),
        end_time=time(22, 0),
        hourly_rate=Decimal("600.00"),
    )

    tz = ZoneInfo("Africa/Addis_Ababa")
    target_date = (datetime.now(tz) + timedelta(days=2)).date()

    # Off-peak interval
    s_off = datetime.combine(target_date, time(10, 0), tzinfo=tz)
    e_off = datetime.combine(target_date, time(12, 0), tzinfo=tz)
    resp_off = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": s_off.isoformat(), "end_at": e_off.isoformat()},
    )
    assert resp_off.status_code == 200
    p_off = resp_off.json()["pricing"]
    assert float(p_off["total_price"]) == 800.00
    assert len(p_off["segments"]) == 1
    assert p_off["segments"][0]["pricing_type"] == "OFF_PEAK"
    assert float(p_off["segments"][0]["hourly_rate"]) == 400.00

    # Peak interval
    s_peak = datetime.combine(target_date, time(18, 0), tzinfo=tz)
    e_peak = datetime.combine(target_date, time(19, 0), tzinfo=tz)
    resp_peak = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": s_peak.isoformat(), "end_at": e_peak.isoformat()},
    )
    assert resp_peak.status_code == 200
    p_peak = resp_peak.json()["pricing"]
    assert float(p_peak["total_price"]) == 600.00
    assert len(p_peak["segments"]) == 1
    assert p_peak["segments"][0]["pricing_type"] == "PEAK"


def test_booking_crossing_peak_and_off_peak_periods(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)

    # OFF_PEAK: 08:00 to 17:00 at 400.00
    create_pricing_rule_record(
        db_session,
        court.id,
        pricing_type="OFF_PEAK",
        start_time=time(8, 0),
        end_time=time(17, 0),
        hourly_rate=Decimal("400.00"),
    )
    # PEAK: 17:00 to 22:00 at 700.00
    create_pricing_rule_record(
        db_session,
        court.id,
        pricing_type="PEAK",
        start_time=time(17, 0),
        end_time=time(22, 0),
        hourly_rate=Decimal("700.00"),
    )

    tz = ZoneInfo("Africa/Addis_Ababa")
    target_date = (datetime.now(tz) + timedelta(days=2)).date()

    # Requested interval crossing boundary: 16:00 to 18:30 (1 hr off-peak, 1.5 hr peak)
    s = datetime.combine(target_date, time(16, 0), tzinfo=tz)
    e = datetime.combine(target_date, time(18, 30), tzinfo=tz)

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": s.isoformat(), "end_at": e.isoformat()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    pricing = data["pricing"]

    # 1.0 hr * 400 = 400.00; 1.5 hr * 700 = 1050.00; total = 1450.00
    assert float(pricing["total_price"]) == 1450.00
    assert len(pricing["segments"]) == 2

    seg1 = pricing["segments"][0]
    assert seg1["pricing_type"] == "OFF_PEAK"
    assert float(seg1["hourly_rate"]) == 400.00
    assert float(seg1["subtotal"]) == 400.00

    seg2 = pricing["segments"][1]
    assert seg2["pricing_type"] == "PEAK"
    assert float(seg2["hourly_rate"]) == 700.00
    assert float(seg2["subtotal"]) == 1050.00


def test_day_of_week_specific_pricing(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)

    tz = ZoneInfo("Africa/Addis_Ababa")
    target_date = (datetime.now(tz) + timedelta(days=2)).date()
    target_dow = target_date.weekday()

    # Generic rule for all days: 500 ETB
    create_pricing_rule_record(
        db_session,
        court.id,
        hourly_rate=Decimal("500.00"),
        day_of_week=None,
    )
    # Day-specific override for target_dow: 750 ETB
    create_pricing_rule_record(
        db_session,
        court.id,
        hourly_rate=Decimal("750.00"),
        day_of_week=target_dow,
    )

    s = datetime.combine(target_date, time(10, 0), tzinfo=tz)
    e = datetime.combine(target_date, time(11, 0), tzinfo=tz)

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": s.isoformat(), "end_at": e.isoformat()},
    )
    assert resp.status_code == 200
    pricing = resp.json()["pricing"]
    assert float(pricing["total_price"]) == 750.00
    assert float(pricing["segments"][0]["hourly_rate"]) == 750.00


def test_pricing_effective_date_boundaries_and_expiration(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)

    tz = ZoneInfo("Africa/Addis_Ababa")
    target_date = (datetime.now(tz) + timedelta(days=2)).date()

    # Rule expired yesterday
    create_pricing_rule_record(
        db_session,
        court.id,
        hourly_rate=Decimal("300.00"),
        effective_from=target_date - timedelta(days=30),
        effective_until=target_date - timedelta(days=1),
    )

    s = datetime.combine(target_date, time(10, 0), tzinfo=tz)
    e = datetime.combine(target_date, time(11, 0), tzinfo=tz)

    # When only expired rule exists, returns 422
    resp_expired = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": s.isoformat(), "end_at": e.isoformat()},
    )
    assert resp_expired.status_code == 422

    # Add active rule starting today
    create_pricing_rule_record(
        db_session,
        court.id,
        hourly_rate=Decimal("550.00"),
        effective_from=target_date,
        effective_until=target_date + timedelta(days=30),
    )

    resp_active = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": s.isoformat(), "end_at": e.isoformat()},
    )
    assert resp_active.status_code == 200
    assert float(resp_active.json()["pricing"]["total_price"]) == 550.00


def test_missing_applicable_pricing_rule_returns_422(
    client: TestClient, db_session: Session
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    # Court has NO pricing rules

    s = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    e = s + timedelta(hours=1)

    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": s.isoformat(), "end_at": e.isoformat()},
    )
    assert resp.status_code == 422
    assert "No valid pricing rule found" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# 5. Database Integrity and Constraint Tests
# -----------------------------------------------------------------------------


def test_exclusion_constraint_blocks_overlapping_reservations(
    db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)

    s = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    e = s + timedelta(hours=2)

    # Insert reservation 1 (CONFIRMED)
    res1 = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=s,
        end_at=e,
        status="CONFIRMED",
    )
    db_session.add(res1)
    db_session.commit()

    # Attempt to insert overlapping reservation 2 for same court (HELD)
    res2 = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=s + timedelta(minutes=30),
        end_at=e + timedelta(minutes=30),
        status="HELD",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(res2)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_exclusion_constraint_allows_overlapping_reservations_different_courts(
    db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court1 = create_court_record(db_session, venue.id, name="Court A")
    court2 = create_court_record(db_session, venue.id, name="Court B")

    s = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    e = s + timedelta(hours=1)

    res1 = Reservation(
        user_id=member_user.id,
        court_id=court1.id,
        start_at=s,
        end_at=e,
        status="CONFIRMED",
    )
    res2 = Reservation(
        user_id=member_user.id,
        court_id=court2.id,
        start_at=s,
        end_at=e,
        status="CONFIRMED",
    )
    db_session.add(res1)
    db_session.add(res2)
    db_session.commit()  # Must succeed without IntegrityError


def test_cancelled_and_expired_reservations_do_not_block_availability(
    client: TestClient, db_session: Session, member_user: User
):
    venue = create_venue_record(db_session)
    court = create_court_record(db_session, venue.id)
    create_pricing_rule_record(db_session, court.id)

    s = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    e = s + timedelta(hours=1)

    # Cancelled reservation
    res_cancelled = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=s,
        end_at=e,
        status="CANCELLED",
        expires_at=None,
    )
    db_session.add(res_cancelled)

    # Expired reservation
    res_expired = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=s,
        end_at=e,
        status="EXPIRED",
        expires_at=None,
    )
    db_session.add(res_expired)
    db_session.commit()

    # Query availability for same time slot
    resp = client.get(
        f"/courts/{court.id}/availability",
        params={"start_at": s.isoformat(), "end_at": e.isoformat()},
    )
    assert resp.status_code == 200
    assert resp.json()["available"] is True
