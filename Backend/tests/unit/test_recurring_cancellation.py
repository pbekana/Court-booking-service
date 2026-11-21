import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.booking_ocurrences import BookingOccurrence
from app.models.court import Court
from app.models.hold import Hold
from app.models.pricing_rules import PricingRule
from app.models.recurring_series import RecurringSeries
from app.models.refund import Refund
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue


def create_test_venue_and_court(db_session: Session) -> tuple[Venue, Court]:
    venue = Venue(
        name=f"Cancel Venue {uuid.uuid4().hex[:6]}",
        address="321 Cancel Lane",
        timezone="Africa/Addis_Ababa",
        opening_time=time(6, 0),
        closing_time=time(23, 0),
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Cancel Court {uuid.uuid4().hex[:6]}",
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


def test_cancel_individual_occurrence_with_full_refund(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id, "500.00")

    now = datetime.now(UTC)
    start_date = (now + timedelta(days=7)).date()
    end_date = start_date + timedelta(days=7)  # 2 occurrences

    create_resp = client.post(
        "/recurring-bookings",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "day_of_week": start_date.weekday(),
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "recurrence_start_date": start_date.isoformat(),
            "recurrence_end_date": end_date.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    series_id = uuid.UUID(create_resp.json()["id"])
    hold_id = create_resp.json()["holds"][0]["id"]

    # Confirm the first hold
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200

    # Get occurrence_id
    occ = db_session.scalars(
        select(BookingOccurrence).where(BookingOccurrence.recurring_series_id == series_id)
    ).first()
    assert occ is not None
    occurrence_id = occ.id

    # Occurrence is 7 days in the future (>= 24 hours) -> eligible for full refund
    cancel_resp = client.post(
        f"/recurring-bookings/{series_id}/occurrences/{occurrence_id}/cancel",
        headers=member_headers,
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    cancel_data = cancel_resp.json()
    assert cancel_data["status"] == "CANCELLED"
    assert cancel_data["refund"] is not None
    assert cancel_data["refund"]["eligible"] is True
    assert Decimal(str(cancel_data["refund"]["amount"])) == Decimal("500.00")

    # Verify occurrence and booking status in db
    db_session.refresh(occ)
    assert occ.status == "CANCELLED"
    booking = db_session.get(Booking, occ.booking_id)
    assert booking is not None
    assert booking.status == "CANCELLED"
    assert booking.cancelled_at is not None

    # Repeated cancellation should reject with 409 (cannot cancel already cancelled occurrence)
    repeat_cancel = client.post(
        f"/recurring-bookings/{series_id}/occurrences/{occurrence_id}/cancel",
        headers=member_headers,
    )
    assert repeat_cancel.status_code == 409


def test_cancel_individual_occurrence_with_no_refund_within_24h(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id, "500.00")

    now = datetime.now(UTC)
    start_date = (now + timedelta(days=7)).date()
    end_date = start_date + timedelta(days=7)

    create_resp = client.post(
        "/recurring-bookings",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "day_of_week": start_date.weekday(),
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "recurrence_start_date": start_date.isoformat(),
            "recurrence_end_date": end_date.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    series_id = uuid.UUID(create_resp.json()["id"])
    hold_id = create_resp.json()["holds"][0]["id"]

    # Confirm the first hold
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    booking_id = uuid.UUID(confirm_resp.json()["id"])

    # Modify the booking start_at to be 5 hours from now (< 24 hours)
    booking = db_session.get(Booking, booking_id)
    assert booking is not None
    booking.start_at = now + timedelta(hours=5)
    booking.end_at = booking.start_at + timedelta(hours=1)
    if booking.reservation_id:
        res = db_session.get(Reservation, booking.reservation_id)
        if res:
            res.start_at = booking.start_at
            res.end_at = booking.end_at
    db_session.commit()

    occ = db_session.scalars(
        select(BookingOccurrence).where(BookingOccurrence.recurring_series_id == series_id)
    ).first()
    assert occ is not None

    # Cancel occurrence
    cancel_resp = client.post(
        f"/recurring-bookings/{series_id}/occurrences/{occ.id}/cancel",
        headers=member_headers,
    )
    assert cancel_resp.status_code == 200
    cancel_data = cancel_resp.json()
    assert cancel_data["status"] == "CANCELLED"
    assert cancel_data["refund"] is not None
    assert cancel_data["refund"]["eligible"] is False
    assert Decimal(str(cancel_data["refund"]["amount"])) == Decimal("0.00")


def test_cancel_entire_recurring_series(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id, "400.00")

    now = datetime.now(UTC)
    start_date = (now + timedelta(days=7)).date()
    end_date = start_date + timedelta(days=7)  # 2 occurrences

    create_resp = client.post(
        "/recurring-bookings",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "day_of_week": start_date.weekday(),
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "recurrence_start_date": start_date.isoformat(),
            "recurrence_end_date": end_date.isoformat(),
        },
    )
    assert create_resp.status_code == 201
    series_id = uuid.UUID(create_resp.json()["id"])
    holds = create_resp.json()["holds"]
    assert len(holds) == 2

    # Confirm the 1st occurrence, leave 2nd occurrence as hold
    confirm_resp = client.post(f"/holds/{holds[0]['id']}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200

    # Cancel entire series
    cancel_all_resp = client.post(
        f"/recurring-bookings/{series_id}/cancel",
        headers=member_headers,
    )
    assert cancel_all_resp.status_code == 200, cancel_all_resp.text
    all_data = cancel_all_resp.json()
    assert all_data["status"] == "CANCELLED"
    assert all_data["cancelled_bookings_count"] == 1
    assert all_data["cancelled_holds_count"] == 1
    assert Decimal(str(all_data["total_refund_amount"])) == Decimal("400.00")

    # Series status in DB
    series = db_session.get(RecurringSeries, series_id)
    assert series is not None
    assert series.status == "CANCELLED"

    # Confirmed booking was cancelled
    occ = db_session.scalars(select(BookingOccurrence).where(BookingOccurrence.recurring_series_id == series_id)).first()
    assert occ is not None
    assert occ.status == "CANCELLED"

    # 2nd occurrence hold was cancelled
    hold2 = db_session.get(Hold, uuid.UUID(holds[1]["id"]))
    assert hold2 is not None
    assert hold2.status == "CANCELLED"

    # Repeated series cancellation is idempotent and does not duplicate refunds
    repeat_resp = client.post(
        f"/recurring-bookings/{series_id}/cancel",
        headers=member_headers,
    )
    assert repeat_resp.status_code == 200
    assert repeat_resp.json()["status"] == "CANCELLED"
    # No additional refund issued
    assert Decimal(str(repeat_resp.json()["total_refund_amount"])) == Decimal("0.00")

    refunds = list(db_session.scalars(select(Refund).where(Refund.booking_id == occ.booking_id)).all())
    # Exactly one refund record existed for this booking
    assert len(refunds) == 1


def test_cancel_series_does_not_cancel_past_occurrences(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id, "400.00")

    now = datetime.now(UTC)
    past_date = (now - timedelta(days=7)).date()
    future_date = (now + timedelta(days=7)).date()
    weekday = past_date.weekday()

    series = RecurringSeries(
        user_id=member_user.id,
        court_id=court.id,
        day_of_week=weekday,
        start_time=time(10, 0),
        end_time=time(11, 0),
        recurrence_start_date=past_date,
        recurrence_end_date=future_date,
        status="ACTIVE",
    )
    db_session.add(series)
    db_session.flush()

    # Past occurrence: confirmed booking in the past
    past_start = datetime.combine(past_date, time(10, 0), tzinfo=UTC)
    past_end = past_start + timedelta(hours=1)
    past_hold = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=past_start,
        end_time=past_end,
        expires_at=past_start,
        status="CONFIRMED",
    )
    db_session.add(past_hold)
    db_session.flush()

    past_res = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=past_start,
        end_at=past_end,
        status="CONFIRMED",
        expires_at=None,
    )
    db_session.add(past_res)
    db_session.flush()

    past_booking = Booking(
        hold_id=past_hold.id,
        reservation_id=past_res.id,
        user_id=member_user.id,
        court_id=court.id,
        start_at=past_start,
        end_at=past_end,
        total_price=Decimal("400.00"),
        currency="ETB",
        status="CONFIRMED",
    )
    db_session.add(past_booking)
    db_session.flush()

    past_occ = BookingOccurrence(
        recurring_series_id=series.id,
        booking_id=past_booking.id,
        occurrence_date=past_date,
        status="CONFIRMED",
    )
    db_session.add(past_occ)

    # Future occurrence: active hold
    future_start = datetime.combine(future_date, time(10, 0), tzinfo=UTC)
    future_end = future_start + timedelta(hours=1)
    future_res = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=future_start,
        end_at=future_end,
        status="HELD",
        expires_at=now + timedelta(minutes=10),
    )
    db_session.add(future_res)
    db_session.flush()

    future_hold = Hold(
        user_id=member_user.id,
        court_id=court.id,
        start_time=future_start,
        end_time=future_end,
        expires_at=now + timedelta(minutes=10),
        status="ACTIVE",
        reservation_id=future_res.id,
        idempotency_key=f"recurring:{series.id}:{future_date.isoformat()}",
    )
    db_session.add(future_hold)
    db_session.commit()

    # Cancel series
    resp = client.post(f"/recurring-bookings/{series.id}/cancel", headers=member_headers)
    assert resp.status_code == 200

    # Verify past occurrence remains CONFIRMED
    db_session.refresh(past_occ)
    db_session.refresh(past_booking)
    assert past_occ.status == "CONFIRMED"
    assert past_booking.status == "CONFIRMED"

    # Verify future hold was CANCELLED
    db_session.refresh(future_hold)
    assert future_hold.status == "CANCELLED"

