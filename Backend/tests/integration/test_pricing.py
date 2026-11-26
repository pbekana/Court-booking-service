import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.court import Court
from app.models.pricing_rules import PricingRule
from app.models.venue import Venue


def test_create_and_get_pricing_rules(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    test_venue: Venue,
    db_session: Session,
) -> None:
    court = Court(
        venue_id=test_venue.id,
        name=f"Pricing Test Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.commit()

    # Member cannot create pricing rule
    payload = {
        "court_id": str(court.id),
        "pricing_type": "PEAK",
        "start_time": "18:00:00",
        "end_time": "22:00:00",
        "day_of_week": None,
        "hourly_rate": "250.00",
        "currency": "ETB",
        "effective_from": "2025-01-01",
        "effective_until": "2030-12-31",
    }
    assert client.post("/pricing-rules", json=payload, headers=member_headers).status_code == 403

    # Admin creates peak rule
    res = client.post("/pricing-rules", json=payload, headers=admin_headers)
    assert res.status_code == 201
    peak_rule = res.json()
    assert peak_rule["pricing_type"] == "PEAK"
    assert Decimal(str(peak_rule["hourly_rate"])) == Decimal("250.00")

    # Admin creates off-peak rule for daytime
    off_peak_payload = {
        "court_id": str(court.id),
        "pricing_type": "OFF_PEAK",
        "start_time": "08:00:00",
        "end_time": "18:00:00",
        "day_of_week": None,
        "hourly_rate": "120.00",
        "currency": "ETB",
        "effective_from": "2025-01-01",
        "effective_until": "2030-12-31",
    }
    res_off = client.post("/pricing-rules", json=off_peak_payload, headers=admin_headers)
    assert res_off.status_code == 201

    # Conflicting rule rejected (overlapping schedule on same court)
    conflict_payload = {
        "court_id": str(court.id),
        "pricing_type": "PEAK",
        "start_time": "17:00:00",
        "end_time": "20:00:00",
        "day_of_week": None,
        "hourly_rate": "300.00",
        "currency": "ETB",
        "effective_from": "2025-01-01",
        "effective_until": "2030-12-31",
    }
    res_conflict = client.post("/pricing-rules", json=conflict_payload, headers=admin_headers)
    assert res_conflict.status_code == 409
    assert "conflict" in res_conflict.json()["detail"].lower()


def test_pricing_preview_crossing_peak_off_peak_boundary(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    test_venue: Venue,
    db_session: Session,
) -> None:
    court = Court(
        venue_id=test_venue.id,
        name=f"Boundary Pricing Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    # Off-peak: 06:00 to 18:00 at 100 ETB/hr
    r1 = PricingRule(
        court_id=court.id,
        pricing_type="OFF_PEAK",
        start_time=time(6, 0),
        end_time=time(18, 0),
        day_of_week=None,
        hourly_rate=Decimal("100.00"),
        currency="ETB",
        effective_from=date(2025, 1, 1),
        effective_until=date(2035, 12, 31),
        is_active=True,
    )
    # Peak: 18:00 to 22:00 at 200 ETB/hr
    r2 = PricingRule(
        court_id=court.id,
        pricing_type="PEAK",
        start_time=time(18, 0),
        end_time=time(22, 0),
        day_of_week=None,
        hourly_rate=Decimal("200.00"),
        currency="ETB",
        effective_from=date(2025, 1, 1),
        effective_until=date(2035, 12, 31),
        is_active=True,
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    tz = ZoneInfo(test_venue.timezone)
    tomorrow = (datetime.now(tz) + timedelta(days=2)).date()

    # Interval: 17:00 to 19:00 (1 hour off-peak @ 100 + 1 hour peak @ 200 = 300 ETB)
    start_dt = datetime.combine(tomorrow, time(17, 0), tzinfo=tz)
    end_dt = datetime.combine(tomorrow, time(19, 0), tzinfo=tz)

    preview_payload = {
        "court_id": str(court.id),
        "start_at": start_dt.isoformat(),
        "end_at": end_dt.isoformat(),
    }
    response = client.post("/pricing/preview", json=preview_payload, headers=member_headers)
    assert response.status_code == 200
    data = response.json()
    assert Decimal(str(data["total_price"])) == Decimal("300.00")
    assert len(data["segments"]) == 2

    # Verify segments
    off_peak_seg = next(s for s in data["segments"] if s["pricing_type"] == "OFF_PEAK")
    assert Decimal(str(off_peak_seg["hourly_rate"])) == Decimal("100.00")
    assert Decimal(str(off_peak_seg["subtotal"])) == Decimal("100.00")

    peak_seg = next(s for s in data["segments"] if s["pricing_type"] == "PEAK")
    assert Decimal(str(peak_seg["hourly_rate"])) == Decimal("200.00")
    assert Decimal(str(peak_seg["subtotal"])) == Decimal("200.00")


def test_pricing_preview_missing_rule_returns_422(
    client: TestClient,
    member_headers: dict[str, str],
    test_venue: Venue,
    db_session: Session,
) -> None:
    court_without_pricing = Court(
        venue_id=test_venue.id,
        name=f"No Pricing Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court_without_pricing)
    db_session.commit()

    tz = ZoneInfo(test_venue.timezone)
    tomorrow = (datetime.now(tz) + timedelta(days=2)).date()
    start_dt = datetime.combine(tomorrow, time(10, 0), tzinfo=tz)
    end_dt = datetime.combine(tomorrow, time(11, 0), tzinfo=tz)

    response = client.post(
        "/pricing/preview",
        json={
            "court_id": str(court_without_pricing.id),
            "start_at": start_dt.isoformat(),
            "end_at": end_dt.isoformat(),
        },
        headers=member_headers,
    )
    assert response.status_code == 422
    assert "pricing" in response.json()["detail"].lower() or "rule" in response.json()["detail"].lower()


def test_pricing_snapshot_preserved_after_booking_confirmation(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    test_venue: Venue,
    db_session: Session,
) -> None:
    """Snapshot preservation: Changing or increasing pricing rules does NOT alter
    the total_price of existing confirmed bookings.
    """
    court = Court(
        venue_id=test_venue.id,
        name=f"Snapshot Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    initial_rule = PricingRule(
        court_id=court.id,
        pricing_type="OFF_PEAK",
        start_time=time(0, 0),
        end_time=time(23, 59, 59),
        day_of_week=None,
        hourly_rate=Decimal("80.00"),
        currency="ETB",
        effective_from=date(2025, 1, 1),
        effective_until=date(2035, 12, 31),
        is_active=True,
    )
    db_session.add(initial_rule)
    db_session.commit()

    tz = ZoneInfo(test_venue.timezone)
    tomorrow = (datetime.now(tz) + timedelta(days=3)).date()
    start_dt = datetime.combine(tomorrow, time(10, 0), tzinfo=tz)
    end_dt = datetime.combine(tomorrow, time(12, 0), tzinfo=tz)  # 2 hours * 80 = 160 ETB

    # Member creates hold & confirms booking
    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(court.id),
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
        },
        headers=member_headers,
    )
    assert hold_res.status_code == 201
    hold_id = hold_res.json()["id"]

    confirm_res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_res.status_code == 200
    booking_data = confirm_res.json()
    assert Decimal(str(booking_data["total_price"])) == Decimal("160.00")
    booking_id = uuid.UUID(booking_data["id"])

    # Admin updates the rule rate to 500 ETB
    client.put(
        f"/pricing-rules/{initial_rule.id}",
        json={"hourly_rate": "500.00"},
        headers=admin_headers,
    )

    # Existing booking price snapshot must remain 160.00 ETB
    booking_db = db_session.get(Booking, booking_id)
    assert booking_db is not None
    assert booking_db.total_price == Decimal("160.00")
