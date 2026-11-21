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
from app.models.user import User
from app.models.venue import Venue
from app.providers.base import PaymentResult
from app.providers.mock_payment_provider import MockPaymentProvider


def create_test_venue_and_court(db_session: Session) -> tuple[Venue, Court]:
    venue = Venue(
        name=f"Confirm Venue {uuid.uuid4().hex[:6]}",
        address="789 Confirm Blvd",
        timezone="Africa/Addis_Ababa",
        opening_time=time(6, 0),
        closing_time=time(23, 0),
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Confirm Court {uuid.uuid4().hex[:6]}",
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


def test_confirm_individual_recurring_hold_and_create_occurrence(
    client: TestClient, db_session: Session, member_headers: dict[str, str], member_user: User
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id)

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
    series_data = create_resp.json()
    series_id = uuid.UUID(series_data["id"])
    assert len(series_data["holds"]) == 2

    hold_to_confirm = series_data["holds"][0]
    hold_id = hold_to_confirm["id"]

    # Confirm the first hold via POST /holds/{id}/confirm
    confirm_resp = client.post(
        f"/holds/{hold_id}/confirm",
        headers=member_headers,
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    booking_data = confirm_resp.json()
    booking_id = uuid.UUID(booking_data["id"])

    # Verify BookingOccurrence was created
    occ = db_session.scalars(
        select(BookingOccurrence).where(
            BookingOccurrence.recurring_series_id == series_id,
            BookingOccurrence.booking_id == booking_id,
        )
    ).first()
    assert occ is not None
    assert occ.status == "CONFIRMED"
    assert occ.occurrence_date == start_date

    # Repeated confirmation should be idempotent and return the same booking
    retry_resp = client.post(
        f"/holds/{hold_id}/confirm",
        headers=member_headers,
    )
    assert retry_resp.status_code == 200
    assert retry_resp.json()["id"] == str(booking_id)

    # Verify no duplicate BookingOccurrence
    all_occs = list(
        db_session.scalars(
            select(BookingOccurrence).where(
                BookingOccurrence.recurring_series_id == series_id,
            )
        ).all()
    )
    assert len(all_occs) == 1


def test_cannot_confirm_expired_recurring_hold(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
):
    _, court = create_test_venue_and_court(db_session)
    create_pricing_rule_for_court(db_session, court.id)

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
    hold_id = uuid.UUID(create_resp.json()["holds"][0]["id"])

    # Manually expire the hold in the database
    hold = db_session.get(Hold, hold_id)
    assert hold is not None
    hold.expires_at = now - timedelta(minutes=5)
    db_session.commit()

    confirm_resp = client.post(
        f"/holds/{hold_id}/confirm",
        headers=member_headers,
    )
    assert confirm_resp.status_code == 400
    assert "expired" in confirm_resp.text.lower()


def test_failed_payment_does_not_create_confirmed_booking(
    client: TestClient, db_session: Session, member_headers: dict[str, str], monkeypatch
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
    hold_id = uuid.UUID(create_resp.json()["holds"][0]["id"])

    # Mock payment provider to simulate payment failure
    class FailingProvider(MockPaymentProvider):
        def initiate_payment(self, *args, **kwargs) -> PaymentResult:
            return PaymentResult(
                success=False,
                status="FAILED",
                provider_transaction_id=None,
                error_message="Card declined by bank",
            )

    monkeypatch.setattr("app.services.hold_service.get_payment_provider", lambda: FailingProvider())

    confirm_resp = client.post(
        f"/holds/{hold_id}/confirm",
        headers=member_headers,
    )
    assert confirm_resp.status_code == 400
    assert "declined" in confirm_resp.text or "failed" in confirm_resp.text.lower()

    # Ensure no confirmed Booking or BookingOccurrence was created
    booking = db_session.scalar(select(Booking).where(Booking.hold_id == hold_id))
    assert booking is None

    occs = list(db_session.scalars(select(BookingOccurrence).where(BookingOccurrence.recurring_series_id == series_id)).all())
    assert len(occs) == 0
