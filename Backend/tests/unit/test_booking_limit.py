import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.court import Court
from app.models.hold import Hold
from app.models.pricing_rules import PricingRule
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue


def create_test_venue_and_court(db_session: Session) -> tuple[Venue, Court]:
    venue = Venue(
        name=f"Limit Test Venue {uuid.uuid4().hex[:6]}",
        address="100 Limit Way",
        timezone="Africa/Addis_Ababa",
        opening_time=time(6, 0),
        closing_time=time(23, 0),
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Limit Court {uuid.uuid4().hex[:6]}",
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


# 1 & 2 & 3 & 4. Progression from 0 to 3 holds and rejection on 4th
def test_member_limit_progression_zero_to_three_and_rejection_on_fourth(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    _, court1 = create_test_venue_and_court(db_session)
    _, court2 = create_test_venue_and_court(db_session)
    _, court3 = create_test_venue_and_court(db_session)
    _, court4 = create_test_venue_and_court(db_session)

    base_time = datetime.now(UTC) + timedelta(days=2)

    # 1. Zero active bookings -> Hold 1 Allowed
    resp1 = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court1.id),
            "start_time": (base_time + timedelta(hours=1)).isoformat(),
            "end_time": (base_time + timedelta(hours=2)).isoformat(),
        },
    )
    assert resp1.status_code == 201

    # Check /members/me/booking-limit
    limit_resp1 = client.get("/members/me/booking-limit", headers=member_headers)
    assert limit_resp1.status_code == 200
    assert limit_resp1.json()["data"]["active_bookings"] == 1
    assert limit_resp1.json()["data"]["remaining_bookings"] == 2

    # 2. One active booking -> Hold 2 Allowed
    resp2 = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court2.id),
            "start_time": (base_time + timedelta(hours=3)).isoformat(),
            "end_time": (base_time + timedelta(hours=4)).isoformat(),
        },
    )
    assert resp2.status_code == 201

    # 3. Two active bookings -> Hold 3 Allowed
    resp3 = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court3.id),
            "start_time": (base_time + timedelta(hours=5)).isoformat(),
            "end_time": (base_time + timedelta(hours=6)).isoformat(),
        },
    )
    assert resp3.status_code == 201

    limit_resp3 = client.get("/members/me/booking-limit", headers=member_headers)
    assert limit_resp3.status_code == 200
    assert limit_resp3.json()["data"]["active_bookings"] == 3
    assert limit_resp3.json()["data"]["remaining_bookings"] == 0

    # 4. Three active bookings -> Hold 4 REJECTED with 409 Conflict
    resp4 = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court4.id),
            "start_time": (base_time + timedelta(hours=7)).isoformat(),
            "end_time": (base_time + timedelta(hours=8)).isoformat(),
        },
    )
    assert resp4.status_code == 409
    data = resp4.json()
    assert data["success"] is False
    assert "maximum limit of 3" in data["message"]
    assert data["data"]["booking_limit"] == 3
    assert data["data"]["active_bookings"] == 3
    assert data["data"]["remaining_bookings"] == 0


# 5. Expired holds do not count toward the limit
def test_expired_holds_do_not_count_toward_limit(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    _, court = create_test_venue_and_court(db_session)
    now = datetime.now(UTC)

    # Insert 3 expired holds directly
    for i in range(3):
        res = Reservation(
            user_id=member_user.id,
            court_id=court.id,
            start_at=now + timedelta(days=2, hours=i * 2),
            end_at=now + timedelta(days=2, hours=i * 2 + 1),
            status="HELD",
            expires_at=now - timedelta(minutes=5),  # already expired
        )
        db_session.add(res)
        db_session.flush()

        hold = Hold(
            user_id=member_user.id,
            court_id=court.id,
            start_time=now + timedelta(days=2, hours=i * 2),
            end_time=now + timedelta(days=2, hours=i * 2 + 1),
            expires_at=now - timedelta(minutes=5),
            status="ACTIVE",
            reservation_id=res.id,
        )
        db_session.add(hold)

    db_session.commit()

    # The member should be able to create a new hold (expired holds are cleaned up and don't count)
    _, court_new = create_test_venue_and_court(db_session)
    resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court_new.id),
            "start_time": (now + timedelta(days=3)).isoformat(),
            "end_time": (now + timedelta(days=3, hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 201


# 6. Cancelled bookings do not count toward the limit
def test_cancelled_bookings_do_not_count_toward_limit(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    _, court = create_test_venue_and_court(db_session)
    now = datetime.now(UTC)

    # Insert 3 cancelled bookings
    for i in range(3):
        res = Reservation(
            user_id=member_user.id,
            court_id=court.id,
            start_at=now + timedelta(days=2, hours=i * 2),
            end_at=now + timedelta(days=2, hours=i * 2 + 1),
            status="CANCELLED",
            expires_at=None,
        )
        db_session.add(res)
        db_session.flush()

        hold = Hold(
            user_id=member_user.id,
            court_id=court.id,
            start_time=now + timedelta(days=2, hours=i * 2),
            end_time=now + timedelta(days=2, hours=i * 2 + 1),
            expires_at=now + timedelta(days=2),
            status="CANCELLED",
            reservation_id=res.id,
        )
        db_session.add(hold)
        db_session.flush()

        booking = Booking(
            hold_id=hold.id,
            reservation_id=res.id,
            user_id=member_user.id,
            court_id=court.id,
            start_at=now + timedelta(days=2, hours=i * 2),
            end_at=now + timedelta(days=2, hours=i * 2 + 1),
            total_price=Decimal("500.00"),
            currency="ETB",
            status="CANCELLED",
            cancelled_at=now,
        )
        db_session.add(booking)

    db_session.commit()

    # Member should have 0 active bookings and be able to create a hold
    limit_resp = client.get("/members/me/booking-limit", headers=member_headers)
    assert limit_resp.json()["data"]["active_bookings"] == 0

    _, court_new = create_test_venue_and_court(db_session)
    resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court_new.id),
            "start_time": (now + timedelta(days=4)).isoformat(),
            "end_time": (now + timedelta(days=4, hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 201


# 7. Past bookings do not count toward the limit
def test_past_bookings_do_not_count_toward_limit(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    _, court = create_test_venue_and_court(db_session)
    now = datetime.now(UTC)

    # Insert 3 completed past confirmed bookings (end_at < now)
    for i in range(3):
        past_start = now - timedelta(days=5, hours=i * 2 + 2)
        past_end = past_start + timedelta(hours=1)

        res = Reservation(
            user_id=member_user.id,
            court_id=court.id,
            start_at=past_start,
            end_at=past_end,
            status="CONFIRMED",
            expires_at=None,
        )
        db_session.add(res)
        db_session.flush()

        hold = Hold(
            user_id=member_user.id,
            court_id=court.id,
            start_time=past_start,
            end_time=past_end,
            expires_at=past_start,
            status="CONFIRMED",
            reservation_id=res.id,
        )
        db_session.add(hold)
        db_session.flush()

        booking = Booking(
            hold_id=hold.id,
            reservation_id=res.id,
            user_id=member_user.id,
            court_id=court.id,
            start_at=past_start,
            end_at=past_end,
            total_price=Decimal("500.00"),
            currency="ETB",
            status="CONFIRMED",
        )
        db_session.add(booking)

    db_session.commit()

    # Active count is 0
    limit_resp = client.get("/members/me/booking-limit", headers=member_headers)
    assert limit_resp.json()["data"]["active_bookings"] == 0

    _, court_new = create_test_venue_and_court(db_session)
    resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court_new.id),
            "start_time": (now + timedelta(days=2)).isoformat(),
            "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
        },
    )
    assert resp.status_code == 201


# 8. Active holds count toward the limit
def test_active_holds_count_toward_limit(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    # Creating 3 holds occupies all 3 slots
    now = datetime.now(UTC)
    for i in range(3):
        _, court = create_test_venue_and_court(db_session)
        resp = client.post(
            "/holds",
            headers=member_headers,
            json={
                "court_id": str(court.id),
                "start_time": (now + timedelta(days=2, hours=i * 2)).isoformat(),
                "end_time": (now + timedelta(days=2, hours=i * 2 + 1)).isoformat(),
            },
        )
        assert resp.status_code == 201

    limit_resp = client.get("/members/me/booking-limit", headers=member_headers)
    assert limit_resp.json()["data"]["active_bookings"] == 3
    assert limit_resp.json()["data"]["remaining_bookings"] == 0


# 9. Hold confirmation enforces the limit
def test_hold_confirmation_enforces_limit(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    now = datetime.now(UTC)
    _, court1 = create_test_venue_and_court(db_session)
    _, court2 = create_test_venue_and_court(db_session)
    _, court3 = create_test_venue_and_court(db_session)
    _, court4 = create_test_venue_and_court(db_session)

    # User creates 1 hold
    hold_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court1.id),
            "start_time": (now + timedelta(days=3)).isoformat(),
            "end_time": (now + timedelta(days=3, hours=1)).isoformat(),
        },
    )
    assert hold_resp.status_code == 201
    hold_id = hold_resp.json()["id"]

    # Now suppose 3 other confirmed bookings exist for this user (e.g. from recurring or direct booking)
    for i, c in enumerate([court2, court3, court4]):
        res = Reservation(
            user_id=member_user.id,
            court_id=c.id,
            start_at=now + timedelta(days=4, hours=i * 2),
            end_at=now + timedelta(days=4, hours=i * 2 + 1),
            status="CONFIRMED",
            expires_at=None,
        )
        db_session.add(res)
        db_session.flush()

        h = Hold(
            user_id=member_user.id,
            court_id=c.id,
            start_time=now + timedelta(days=4, hours=i * 2),
            end_time=now + timedelta(days=4, hours=i * 2 + 1),
            expires_at=now + timedelta(days=4),
            status="CONFIRMED",
            reservation_id=res.id,
        )
        db_session.add(h)
        db_session.flush()

        b = Booking(
            hold_id=h.id,
            reservation_id=res.id,
            user_id=member_user.id,
            court_id=c.id,
            start_at=now + timedelta(days=4, hours=i * 2),
            end_at=now + timedelta(days=4, hours=i * 2 + 1),
            total_price=Decimal("500.00"),
            currency="ETB",
            status="CONFIRMED",
        )
        db_session.add(b)

    db_session.commit()

    # Attempting to confirm the hold when 3 other active bookings already exist must fail with 409
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 409
    assert confirm_resp.json()["success"] is False


# 10. Successful idempotent retry returns the existing booking
def test_successful_idempotent_retry_returns_existing_booking(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id, "600.00")

    now = datetime.now(UTC)
    hold_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (now + timedelta(days=2)).isoformat(),
            "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
        },
    )
    assert hold_resp.status_code == 201
    hold_id = hold_resp.json()["id"]

    # First confirmation
    confirm_resp1 = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp1.status_code == 200
    booking1 = confirm_resp1.json()

    # Retry confirmation
    confirm_resp2 = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp2.status_code == 200
    booking2 = confirm_resp2.json()

    assert booking1["id"] == booking2["id"]
    assert booking1["total_price"] == booking2["total_price"]


# 11. One member cannot confirm another member's hold
def test_one_member_cannot_confirm_another_members_hold(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
):
    _, court = create_test_venue_and_court(db_session)
    now = datetime.now(UTC)

    # Member 1 creates hold
    hold_resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (now + timedelta(days=2)).isoformat(),
            "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
        },
    )
    assert hold_resp.status_code == 201
    hold_id = hold_resp.json()["id"]

    # Member 2 attempts to confirm Member 1's hold
    confirm_resp = client.post(
        f"/holds/{hold_id}/confirm",
        headers=other_member_headers,
    )
    assert confirm_resp.status_code == 403


# 12. Recurring bookings cannot exceed the limit
def test_recurring_bookings_cannot_exceed_limit(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id, "400.00")

    # Member already has 1 active hold
    now = datetime.now(UTC)
    client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": (now + timedelta(days=2)).isoformat(),
            "end_time": (now + timedelta(days=2, hours=1)).isoformat(),
        },
    )

    # Recurring series spanning 3 future weeks on Wednesdays (weekday 2)
    # Today is Tuesday/Wednesday -> 3 occurrences requested + 1 existing = 4 -> exceeds limit of 3!
    future_start_date = (now + timedelta(days=7)).date()
    future_end_date = future_start_date + timedelta(days=21)  # spans 3-4 Wednesdays

    resp = client.post(
        "/recurring-series",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "day_of_week": future_start_date.weekday(),
            "start_time": "14:00:00",
            "end_time": "15:00:00",
            "recurrence_start_date": future_start_date.isoformat(),
            "recurrence_end_date": future_end_date.isoformat(),
        },
    )
    assert resp.status_code == 409
    assert resp.json()["success"] is False
    assert "exceed the maximum limit of 3" in resp.json()["message"]


# 13. Member booking limit endpoint
def test_member_booking_limit_endpoint(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    now = datetime.now(UTC)

    # Initially 0
    resp_init = client.get("/members/me/booking-limit", headers=member_headers)
    assert resp_init.status_code == 200
    assert resp_init.json()["data"]["active_bookings"] == 0
    assert resp_init.json()["data"]["remaining_bookings"] == 3

    # Create 2 holds
    for i in range(2):
        client.post(
            "/holds",
            headers=member_headers,
            json={
                "court_id": str(court.id),
                "start_time": (now + timedelta(days=2, hours=i * 2)).isoformat(),
                "end_time": (now + timedelta(days=2, hours=i * 2 + 1)).isoformat(),
            },
        )

    resp_after = client.get("/members/me/booking-limit", headers=member_headers)
    assert resp_after.status_code == 200
    data = resp_after.json()["data"]
    assert data["booking_limit"] == 3
    assert data["active_bookings"] == 2
    assert data["remaining_bookings"] == 1
    assert len(data["active_reservations"]) == 2
