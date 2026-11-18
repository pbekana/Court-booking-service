import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.court import Court
from app.models.pricing_rules import PricingRule
from app.models.venue import Venue


def create_test_venue_and_court(db_session: Session) -> tuple[Venue, Court]:
    venue = Venue(
        name=f"Pricing Venue {uuid.uuid4().hex[:6]}",
        address="100 Price Way",
        timezone="Africa/Addis_Ababa",
        opening_time=time(0, 0),
        closing_time=time(23, 59, 59),
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Pricing Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.commit()
    db_session.refresh(court)
    return venue, court


# 1. Admin can create peak pricing rule
def test_admin_can_create_peak_pricing_rule(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    response = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "12:00:00",
            "end_time": "18:00:00",
            "day_of_week": 0,
            "hourly_rate": "600.00",
            "currency": "ETB",
            "effective_from": "2026-01-01",
            "effective_until": "2026-12-31",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["court_id"] == str(court.id)
    assert data["pricing_type"] == "PEAK"
    assert data["hourly_rate"] == "600.00"
    assert data["is_active"] is True


# 2. Admin can create off-peak pricing rule
def test_admin_can_create_off_peak_pricing_rule(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    response = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "06:00:00",
            "end_time": "12:00:00",
            "day_of_week": 0,
            "hourly_rate": "300.00",
            "currency": "ETB",
            "effective_from": "2026-01-01",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["pricing_type"] == "OFF_PEAK"
    assert data["hourly_rate"] == "300.00"


# 3. Non-admin cannot create pricing rule
def test_non_admin_cannot_create_pricing_rule(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    response = client.post(
        "/pricing-rules",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "12:00:00",
            "end_time": "18:00:00",
            "hourly_rate": "600.00",
            "effective_from": "2026-01-01",
        },
    )
    assert response.status_code == 403


# 4. Retrieving pricing rules (all, by court, active_only, effective_date)
def test_retrieve_pricing_rules(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)

    # Create 2 rules
    client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "06:00:00",
            "end_time": "12:00:00",
            "day_of_week": 1,
            "hourly_rate": "350.00",
            "effective_from": "2026-01-01",
            "effective_until": "2026-06-30",
        },
    )
    client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "12:00:00",
            "end_time": "18:00:00",
            "day_of_week": 1,
            "hourly_rate": "700.00",
            "effective_from": "2026-07-01",
            "effective_until": "2026-12-31",
        },
    )

    # Member can view pricing rules
    resp_all = client.get(f"/pricing-rules?court_id={court.id}", headers=member_headers)
    assert resp_all.status_code == 200
    assert len(resp_all.json()) == 2

    # Filter by court endpoint
    resp_court = client.get(f"/courts/{court.id}/pricing-rules", headers=member_headers)
    assert resp_court.status_code == 200
    assert len(resp_court.json()) == 2

    # Filter by effective date
    resp_date = client.get(
        f"/pricing-rules?court_id={court.id}&effective_date=2026-03-01",
        headers=member_headers,
    )
    assert resp_date.status_code == 200
    assert len(resp_date.json()) == 1
    assert resp_date.json()[0]["pricing_type"] == "OFF_PEAK"


# 5. Retrieve specific pricing rule by ID
def test_retrieve_pricing_rule_by_id(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_resp = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "12:00:00",
            "end_time": "18:00:00",
            "hourly_rate": "550.00",
            "effective_from": "2026-01-01",
        },
    )
    rule_id = create_resp.json()["id"]

    get_resp = client.get(f"/pricing-rules/{rule_id}", headers=member_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == rule_id

    # Nonexistent
    assert client.get(f"/pricing-rules/{uuid.uuid4()}", headers=member_headers).status_code == 404


# 6. Admin can update pricing rule
def test_update_pricing_rule(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_resp = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "08:00:00",
            "end_time": "12:00:00",
            "hourly_rate": "400.00",
            "effective_from": "2026-01-01",
        },
    )
    rule_id = create_resp.json()["id"]

    # Member forbidden
    forbidden_resp = client.put(
        f"/pricing-rules/{rule_id}",
        headers=member_headers,
        json={"hourly_rate": "450.00"},
    )
    assert forbidden_resp.status_code == 403

    # Admin updates rate and time
    update_resp = client.put(
        f"/pricing-rules/{rule_id}",
        headers=admin_headers,
        json={
            "hourly_rate": "450.00",
            "pricing_type": "PEAK",
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["hourly_rate"] == "450.00"
    assert update_resp.json()["pricing_type"] == "PEAK"


# 7. Delete / deactivate pricing rule
def test_delete_deactivate_pricing_rule(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_resp = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "08:00:00",
            "end_time": "12:00:00",
            "hourly_rate": "400.00",
            "effective_from": "2026-01-01",
        },
    )
    rule_id = create_resp.json()["id"]

    # Member forbidden
    assert client.delete(f"/pricing-rules/{rule_id}", headers=member_headers).status_code == 403

    # Admin deactivates
    del_resp = client.delete(f"/pricing-rules/{rule_id}", headers=admin_headers)
    assert del_resp.status_code == 200

    # Rule is now inactive
    rule_in_db = db_session.get(PricingRule, uuid.UUID(rule_id))
    assert rule_in_db is not None
    assert rule_in_db.is_active is False


# 8. Correct price calculation: split peak and off-peak periods
def test_pricing_calculation_split_peak_off_peak(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], member_headers: dict[str, str]
):
    _venue, court = create_test_venue_and_court(db_session)

    # Monday (weekday 0):
    # 10:00–12:00: 300 ETB/hour
    # 12:00–14:00: 600 ETB/hour
    client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "10:00:00",
            "end_time": "12:00:00",
            "day_of_week": 0,
            "hourly_rate": "300.00",
            "currency": "ETB",
            "effective_from": "2026-01-01",
        },
    )
    client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "12:00:00",
            "end_time": "14:00:00",
            "day_of_week": 0,
            "hourly_rate": "600.00",
            "currency": "ETB",
            "effective_from": "2026-01-01",
        },
    )

    # Next Monday at 10:00 to 14:00 (Addis timezone is UTC+3)
    start_dt = datetime(2026, 6, 1, 10, 0, tzinfo=UTC) - timedelta(hours=3)  # 10:00 local Addis
    end_dt = datetime(2026, 6, 1, 14, 0, tzinfo=UTC) - timedelta(hours=3)    # 14:00 local Addis

    resp = client.post(
        "/pricing/preview",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_at": start_dt.isoformat(),
            "end_at": end_dt.isoformat(),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["currency"] == "ETB"
    # 2 hours * 300 = 600, 2 hours * 600 = 1200 -> Total = 1800.00
    assert data["total_price"] == "1800.00"
    assert len(data["segments"]) == 2
    assert data["segments"][0]["subtotal"] == "600.00"
    assert data["segments"][1]["subtotal"] == "1200.00"


# 9. Booking across midnight
def test_pricing_calculation_across_midnight(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], member_headers: dict[str, str]
):
    _venue, court = create_test_venue_and_court(db_session)

    # Evening rule: 22:00 to 24:00 (23:59:59.999999 or stored as 22:00-02:00 overnight)
    # Let's define rule: 22:00 to 02:00 overnight
    client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "22:00:00",
            "end_time": "02:00:00",
            "hourly_rate": "400.00",
            "currency": "ETB",
            "effective_from": "2026-01-01",
        },
    )

    # Booking from 23:00 to 01:00 across midnight (2 hours)
    start_dt = datetime(2026, 6, 1, 23, 0, tzinfo=UTC) - timedelta(hours=3)
    end_dt = datetime(2026, 6, 2, 1, 0, tzinfo=UTC) - timedelta(hours=3)

    resp = client.post(
        "/pricing/preview",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_at": start_dt.isoformat(),
            "end_at": end_dt.isoformat(),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_price"] == "800.00"


# 10. Booking across different weekdays
def test_pricing_calculation_across_different_weekdays(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], member_headers: dict[str, str]
):
    _venue, court = create_test_venue_and_court(db_session)

    # 2026-06-07 is Sunday (weekday 6)
    # 2026-06-08 is Monday (weekday 0)
    # Sunday evening 22:00–24:00 at 500 ETB/hr
    client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "22:00:00",
            "end_time": "23:59:59",
            "day_of_week": 6,
            "hourly_rate": "500.00",
            "currency": "ETB",
            "effective_from": "2026-01-01",
        },
    )
    # Monday morning 00:00–02:00 at 300 ETB/hr
    client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "00:00:00",
            "end_time": "02:00:00",
            "day_of_week": 0,
            "hourly_rate": "300.00",
            "currency": "ETB",
            "effective_from": "2026-01-01",
        },
    )

    # Booking from Sunday 23:00 to Monday 01:00 (1h Sunday + 1h Monday)
    start_dt = datetime(2026, 6, 7, 23, 0, tzinfo=UTC) - timedelta(hours=3)
    end_dt = datetime(2026, 6, 8, 1, 0, tzinfo=UTC) - timedelta(hours=3)

    resp = client.post(
        "/pricing/preview",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_at": start_dt.isoformat(),
            "end_at": end_dt.isoformat(),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # 1h * 500 + 1h * 300 = 800
    assert data["total_price"] == "800.00"
    assert len(data["segments"]) == 2


# 11. Invalid pricing rules validation
def test_invalid_pricing_rules_validation(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)

    # Hourly rate <= 0
    resp1 = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "10:00:00",
            "end_time": "12:00:00",
            "hourly_rate": "0.00",
            "effective_from": "2026-01-01",
        },
    )
    assert resp1.status_code == 422

    # Start time == end time
    resp2 = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "10:00:00",
            "end_time": "10:00:00",
            "hourly_rate": "500.00",
            "effective_from": "2026-01-01",
        },
    )
    assert resp2.status_code == 422

    # effective_until < effective_from
    resp3 = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "10:00:00",
            "end_time": "12:00:00",
            "hourly_rate": "500.00",
            "effective_from": "2026-06-01",
            "effective_until": "2026-05-01",
        },
    )
    assert resp3.status_code == 422

    # Nonexistent court
    resp4 = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(uuid.uuid4()),
            "pricing_type": "PEAK",
            "start_time": "10:00:00",
            "end_time": "12:00:00",
            "hourly_rate": "500.00",
            "effective_from": "2026-01-01",
        },
    )
    assert resp4.status_code == 404


# 12. Overlapping pricing rules rejected
def test_overlapping_pricing_rules_rejected(
    client: TestClient, db_session: Session, admin_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)

    # First rule: 10:00–14:00
    resp1 = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "10:00:00",
            "end_time": "14:00:00",
            "day_of_week": 2,
            "hourly_rate": "300.00",
            "effective_from": "2026-01-01",
            "effective_until": "2026-12-31",
        },
    )
    assert resp1.status_code == 201

    # Overlapping rule on same court, day, and time: 12:00–16:00
    resp2 = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "PEAK",
            "start_time": "12:00:00",
            "end_time": "16:00:00",
            "day_of_week": 2,
            "hourly_rate": "600.00",
            "effective_from": "2026-06-01",
            "effective_until": "2026-12-31",
        },
    )
    assert resp2.status_code == 409


# 13. Missing pricing coverage rejected
def test_missing_pricing_coverage_rejected(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], member_headers: dict[str, str]
):
    _venue, court = create_test_venue_and_court(db_session)

    # Rule only covers 08:00 to 12:00
    client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "08:00:00",
            "end_time": "12:00:00",
            "hourly_rate": "300.00",
            "effective_from": "2026-01-01",
        },
    )

    # Request pricing preview for 14:00 to 16:00 (no rule covers this period)
    start_dt = datetime(2026, 6, 1, 14, 0, tzinfo=UTC) - timedelta(hours=3)
    end_dt = datetime(2026, 6, 1, 16, 0, tzinfo=UTC) - timedelta(hours=3)

    resp = client.post(
        "/pricing/preview",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_at": start_dt.isoformat(),
            "end_at": end_dt.isoformat(),
        },
    )
    assert resp.status_code == 422
    assert "No valid pricing rule found" in resp.json()["detail"]


# 14. Historical booking prices remain unchanged after pricing rule update or deactivation
def test_historical_booking_price_unchanged_after_rule_update(
    client: TestClient, db_session: Session, admin_headers: dict[str, str], member_headers: dict[str, str]
):
    _venue, court = create_test_venue_and_court(db_session)

    # 1. Create rule at 400 ETB/hr
    create_rule_resp = client.post(
        "/pricing-rules",
        headers=admin_headers,
        json={
            "court_id": str(court.id),
            "pricing_type": "OFF_PEAK",
            "start_time": "10:00:00",
            "end_time": "12:00:00",
            "hourly_rate": "400.00",
            "currency": "ETB",
            "effective_from": "2026-01-01",
        },
    )
    rule_id = create_rule_resp.json()["id"]

    # 2. Member creates hold for 10:00 to 12:00 (2 hours)
    start_dt = (datetime.now(UTC) + timedelta(days=2)).replace(
        hour=7, minute=0, second=0, microsecond=0
    )  # 10:00 Addis
    end_dt = start_dt + timedelta(hours=2)

    hold_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
        },
    )
    assert hold_resp.status_code == 201
    hold_id = hold_resp.json()["id"]

    # 3. Confirm hold -> creates booking with snapshot total_price = 800.00
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    booking_data = confirm_resp.json()
    assert Decimal(str(booking_data["total_price"])) == Decimal("800.00")
    booking_id = booking_data["id"]

    # 4. Admin updates the rule hourly_rate to 999.00
    update_resp = client.put(
        f"/pricing-rules/{rule_id}",
        headers=admin_headers,
        json={"hourly_rate": "999.00"},
    )
    assert update_resp.status_code == 200

    # 5. Check historical booking price in DB: must still be 800.00!
    db_session.expire_all()
    booking_in_db = db_session.get(Booking, uuid.UUID(booking_id))
    assert booking_in_db is not None
    assert booking_in_db.total_price == Decimal("800.00")
