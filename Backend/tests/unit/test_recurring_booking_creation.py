import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.court import Court
from app.models.hold import Hold
from app.models.pricing_rules import PricingRule
from app.models.recurring_series import RecurringSeries
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue


def create_test_venue_and_court(db_session: Session) -> tuple[Venue, Court]:
    venue = Venue(
        name=f"Recurring Venue {uuid.uuid4().hex[:6]}",
        address="123 Recurring Way",
        timezone="Africa/Addis_Ababa",
        opening_time=time(6, 0),
        closing_time=time(23, 0),
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Recurring Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.commit()
    db_session.refresh(court)
    return venue, court


def create_pricing_rule_for_court(
    db_session: Session, court_id: uuid.UUID, rate: str = "500.00"
) -> PricingRule:
    rule = PricingRule(
        court_id=court_id,
        pricing_type="OFF_PEAK",
        start_time=time(0, 0),
        end_time=time(23, 59, 59),
        hourly_rate=Decimal(rate),
        currency="ETB",
        effective_from=datetime.now(UTC).date() - timedelta(days=5),
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)
    return rule


def test_successfully_create_weekly_recurring_series(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id)

    now = datetime.now(UTC)
    # Pick a future start date 7 days out
    start_date = (now + timedelta(days=7)).date()
    target_weekday = start_date.weekday()
    # Spans 2 weeks (2 occurrences, e.g. day 7 and day 14)
    end_date = start_date + timedelta(days=7)

    payload = {
        "court_id": str(court.id),
        "day_of_week": target_weekday,
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    resp = client.post("/recurring-bookings", headers=member_headers, json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert "id" in data
    assert data["status"] == "ACTIVE"
    assert data["court_id"] == str(court.id)
    assert data["day_of_week"] == target_weekday
    assert len(data["occurrences"]) == 2
    assert len(data["holds"]) == 2

    # Each occurrence has its own reservation and hold
    series_id = uuid.UUID(data["id"])
    db_holds = list(
        db_session.scalars(
            select(Hold).where(Hold.user_id == member_user.id, Hold.court_id == court.id)
        ).all()
    )
    assert len(db_holds) == 2
    for h in db_holds:
        assert h.status in ["ACTIVE", "HELD"]
        assert h.reservation_id is not None
        res = db_session.get(Reservation, h.reservation_id)
        assert res is not None
        assert res.status == "HELD"
        assert res.court_id == court.id
        assert res.user_id == member_user.id

    # Test GET /recurring-bookings
    get_all_resp = client.get("/recurring-bookings", headers=member_headers)
    assert get_all_resp.status_code == 200
    all_series = get_all_resp.json()
    assert len(all_series) >= 1
    matched = [s for s in all_series if s["id"] == str(series_id)]
    assert len(matched) == 1
    assert len(matched[0]["occurrences"]) == 2

    # Test GET /recurring-bookings/{series_id}
    get_one_resp = client.get(f"/recurring-bookings/{series_id}", headers=member_headers)
    assert get_one_resp.status_code == 200
    one_series = get_one_resp.json()
    assert one_series["id"] == str(series_id)
    assert len(one_series["occurrences"]) == 2


def test_reject_inactive_court(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    court.is_active = False
    db_session.commit()

    now = datetime.now(UTC)
    start_date = (now + timedelta(days=7)).date()
    end_date = start_date + timedelta(days=14)

    payload = {
        "court_id": str(court.id),
        "day_of_week": start_date.weekday(),
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    resp = client.post("/recurring-bookings", headers=member_headers, json=payload)
    assert resp.status_code == 400
    assert "Court is inactive" in resp.text


def test_reject_inactive_member(
    client: TestClient, db_session: Session
):
    _, court = create_test_venue_and_court(db_session)

    inactive_user = User(
        full_name="Inactive Member",
        email=f"inactive_{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("pw123"),
        role="MEMBER",
        is_active=False,
    )
    db_session.add(inactive_user)
    db_session.commit()

    from app.core.security import create_access_token
    inactive_token = create_access_token({"sub": str(inactive_user.id), "role": "MEMBER"})
    headers = {"Authorization": f"Bearer {inactive_token}"}

    now = datetime.now(UTC)
    start_date = (now + timedelta(days=7)).date()
    end_date = start_date + timedelta(days=14)

    payload = {
        "court_id": str(court.id),
        "day_of_week": start_date.weekday(),
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    resp = client.post("/recurring-bookings", headers=headers, json=payload)
    assert resp.status_code in [400, 401]


def test_reject_past_occurrences(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)

    now = datetime.now(UTC)
    # Recurrence in the past
    past_start = (now - timedelta(days=21)).date()
    past_end = (now - timedelta(days=7)).date()

    payload = {
        "court_id": str(court.id),
        "day_of_week": past_start.weekday(),
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "recurrence_start_date": past_start.isoformat(),
        "recurrence_end_date": past_end.isoformat(),
    }

    resp = client.post("/recurring-bookings", headers=member_headers, json=payload)
    assert resp.status_code == 400
    assert "in the past" in resp.text.lower()


def test_reject_invalid_time_ranges(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)

    now = datetime.now(UTC)
    start_date = (now + timedelta(days=7)).date()
    end_date = start_date + timedelta(days=14)

    # Start time later than end time
    payload = {
        "court_id": str(court.id),
        "day_of_week": start_date.weekday(),
        "start_time": "14:00:00",
        "end_time": "11:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    resp = client.post("/recurring-bookings", headers=member_headers, json=payload)
    assert resp.status_code in [400, 422]


def test_reject_unavailable_occurrences_and_rollback(
    client: TestClient, db_session: Session, member_headers: dict[str, str], other_member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id)

    now = datetime.now(UTC)
    start_date = (now + timedelta(days=7)).date()
    target_weekday = start_date.weekday()
    # 3 occurrences: day 7, day 14, day 21
    end_date = start_date + timedelta(days=14)

    from zoneinfo import ZoneInfo
    venue_tz = ZoneInfo("Africa/Addis_Ababa")

    # Other member reserves the 2nd occurrence (day 14 at 10:00 in venue tz)
    second_occ_date = start_date + timedelta(days=7)
    conflict_start = datetime.combine(second_occ_date, time(10, 0), tzinfo=venue_tz)
    conflict_end = conflict_start + timedelta(hours=1)
    hold_resp = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": conflict_start.isoformat(),
            "end_time": conflict_end.isoformat(),
        },
    )
    assert hold_resp.status_code == 201

    # Member attempts to create recurring booking covering day 7, 14, 21
    payload = {
        "court_id": str(court.id),
        "day_of_week": target_weekday,
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    resp = client.post("/recurring-bookings", headers=member_headers, json=payload)
    assert resp.status_code == 409
    assert "not available" in resp.text.lower() or "conflict" in resp.text.lower()

    # Ensure no partial recurring series or holds exist for member
    all_series = list(db_session.scalars(select(RecurringSeries).where(RecurringSeries.court_id == court.id)).all())
    assert len(all_series) == 0


def test_enforce_member_booking_limit_on_recurring_creation(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id)

    now = datetime.now(UTC)
    # Member creates 2 active holds
    h1 = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (now + timedelta(days=2)).isoformat(),
            "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
        },
    )
    assert h1.status_code == 201

    h2 = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (now + timedelta(days=3)).isoformat(),
            "end_time": (now + timedelta(days=3, hours=1)).isoformat(),
        },
    )
    assert h2.status_code == 201

    # Member currently has 2 active bookings. Requests 2 occurrences -> 2 + 2 = 4 > 3 -> reject!
    start_date = (now + timedelta(days=7)).date()
    end_date = start_date + timedelta(days=7)  # 2 occurrences

    payload = {
        "court_id": str(court.id),
        "day_of_week": start_date.weekday(),
        "start_time": "14:00:00",
        "end_time": "15:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    resp = client.post("/recurring-bookings", headers=member_headers, json=payload)
    assert resp.status_code == 409
    assert "limit of 3" in resp.text
