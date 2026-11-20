import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.court import Court
from app.models.payment import Payment
from app.models.pricing_rules import PricingRule
from app.models.refund import Refund
from app.models.reservations import Reservation
from app.providers.mock_payment_provider import (
    MockPaymentProvider,
    get_payment_provider,
)
from app.services.refund_service import calculate_refund_eligibility


@pytest.fixture(autouse=True)
def reset_mock_provider() -> None:
    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.reset()


def create_test_court_with_pricing(
    db_session: Session, hourly_rate: Decimal = Decimal("500.00")
) -> Court:
    from app.models.venue import Venue

    venue = Venue(
        name=f"Cancel Venue {uuid.uuid4().hex[:6]}",
        address="200 Cancellation Way",
        timezone="Africa/Addis_Ababa",
        opening_time=time(6, 0),
        closing_time=time(22, 0),
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name=f"Court {uuid.uuid4().hex[:6]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    pricing_rule = PricingRule(
        court_id=court.id,
        pricing_type="PEAK",
        day_of_week=None,
        start_time=time(0, 0),
        end_time=time(23, 59, 59),
        hourly_rate=hourly_rate,
        currency="ETB",
        effective_from=date(2026, 1, 1),
        effective_until=date(2030, 12, 31),
        is_active=True,
    )
    db_session.add(pricing_rule)
    db_session.commit()
    db_session.refresh(court)
    return court


def create_active_hold(
    client: TestClient,
    member_headers: dict[str, str],
    court: Court,
    hours_from_now: int = 48,
    duration_hours: int = 1,
) -> str:
    start_time = datetime.now(UTC) + timedelta(hours=hours_from_now)
    end_time = start_time + timedelta(hours=duration_hours)
    resp = client.post(
        "/holds",
        headers=member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def create_confirmed_booking(
    client: TestClient,
    member_headers: dict[str, str],
    court: Court,
    hours_from_now: int = 48,
) -> tuple[str, str]:
    hold_id = create_active_hold(
        client, member_headers, court, hours_from_now=hours_from_now
    )
    confirm_resp = client.post(
        f"/holds/{hold_id}/confirm", headers=member_headers
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    booking_id = confirm_resp.json()["id"]
    return hold_id, booking_id


# ============================================================================
# Dedicated Refund Eligibility Unit Tests
# ============================================================================


def test_calculate_refund_eligibility_rules() -> None:
    now = datetime.now(UTC)

    # 48 hours before: Full refund
    assert calculate_refund_eligibility(now + timedelta(hours=48), now) is True

    # Exactly 24 hours before: Full refund
    assert calculate_refund_eligibility(now + timedelta(hours=24), now) is True

    # 23 hours before: No refund
    assert calculate_refund_eligibility(now + timedelta(hours=23), now) is False

    # 12 hours before: No refund
    assert calculate_refund_eligibility(now + timedelta(hours=12), now) is False

    # 1 hour before: No refund
    assert calculate_refund_eligibility(now + timedelta(hours=1), now) is False

    # Booking already started: raises ValueError
    with pytest.raises(
        ValueError, match="Cannot cancel a booking that has already started"
    ):
        calculate_refund_eligibility(now - timedelta(minutes=1), now)

    with pytest.raises(
        ValueError, match="Cannot cancel a booking that has already started"
    ):
        calculate_refund_eligibility(now, now)


# ============================================================================
# 1. Cancellation Core Workflow Tests
# ============================================================================


def test_cancel_confirmed_booking_successfully(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    cancel_resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert cancel_resp.status_code == 200
    data = cancel_resp.json()
    assert data["message"] == "Booking cancelled successfully"
    assert data["booking_id"] == booking_id
    assert data["booking_status"] == "CANCELLED"
    assert data["status"] == "CANCELLED"
    assert data["cancelled_at"] is not None
    assert data["refund"]["eligible"] is True
    assert data["refund"]["amount"] == "500.00"
    assert data["refund"]["status"] == "SUCCESS"

    # DB verification
    booking = db_session.get(Booking, uuid.UUID(booking_id))
    assert booking is not None
    assert booking.status == "CANCELLED"
    assert booking.cancelled_at is not None

    reservation = db_session.get(Reservation, booking.reservation_id)
    assert reservation is not None
    assert reservation.status == "CANCELLED"
    assert reservation.expires_at is None


def test_reject_cancellation_for_nonexistent_booking(
    client: TestClient,
    member_headers: dict[str, str],
) -> None:
    fake_id = uuid.uuid4()
    resp = client.post(f"/bookings/{fake_id}/cancel", headers=member_headers)
    assert resp.status_code == 404
    assert "booking not found" in resp.json()["detail"].lower()


def test_reject_cancellation_by_another_member(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session)
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=other_member_headers
    )
    assert resp.status_code == 403
    assert "permission" in resp.json()["detail"].lower()


def test_reject_cancellation_of_already_cancelled_booking(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session)
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    resp1 = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp1.status_code == 200

    # Repeat cancellation without idempotency key -> rejected with 409 Conflict
    resp2 = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp2.status_code == 409
    assert "already been cancelled" in resp2.json()["detail"].lower()


def test_reject_cancellation_after_booking_has_started(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session)
    # Create booking that is 48 hours in future, then artificially update start_at into the past
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )
    booking = db_session.get(Booking, uuid.UUID(booking_id))
    assert booking is not None
    booking.start_at = datetime.now(UTC) - timedelta(minutes=10)
    db_session.commit()

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp.status_code == 409
    assert "already started" in resp.json()["detail"].lower()


def test_confirm_reservation_status_becomes_cancelled(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session)
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp.status_code == 200

    booking = db_session.get(Booking, uuid.UUID(booking_id))
    assert booking is not None
    res = db_session.get(Reservation, booking.reservation_id)
    assert res is not None
    assert res.status == "CANCELLED"
    assert res.expires_at is None


def test_confirm_court_slot_becomes_available_again(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session)
    target_hours = 48
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=target_hours
    )

    # Other member tries to create hold on the same court slot: rejected due to exclusion constraint
    start_time = datetime.now(UTC) + timedelta(hours=target_hours)
    end_time = start_time + timedelta(hours=1)
    hold_attempt = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert hold_attempt.status_code == 409

    # Member 1 cancels booking
    cancel_resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert cancel_resp.status_code == 200

    # Other member can now successfully hold the exact same slot!
    hold_success = client.post(
        "/holds",
        headers=other_member_headers,
        json={
            "court_id": str(court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
    )
    assert hold_success.status_code == 201


# ============================================================================
# 2. Refund Eligibility and Calculation Tests
# ============================================================================


def test_cancellation_48_hours_before_gives_full_refund(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("600.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["refund"]["eligible"] is True
    assert Decimal(str(data["refund"]["amount"])) == Decimal("600.00")
    assert data["refund"]["status"] == "SUCCESS"

    refund = db_session.scalar(
        select(Refund).where(Refund.booking_id == uuid.UUID(booking_id))
    )
    assert refund is not None
    assert refund.status == "SUCCESS"
    assert refund.amount == Decimal("600.00")


def test_cancellation_exactly_24_hours_before_gives_full_refund(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )
    booking = db_session.get(Booking, uuid.UUID(booking_id))
    assert booking is not None
    # Adjust start_at to exactly 24 hours plus 1 second from now
    booking.start_at = datetime.now(UTC) + timedelta(hours=24, seconds=1)
    db_session.commit()

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["refund"]["eligible"] is True
    assert data["refund"]["status"] == "SUCCESS"


def test_cancellation_23_hours_before_gives_no_refund(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=23
    )

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "not eligible for a refund" in data["message"]
    assert data["refund"]["eligible"] is False
    assert Decimal(str(data["refund"]["amount"])) == Decimal("0.00")
    assert data["refund"]["status"] is None

    # Payment in DB remains SUCCESS
    payment = db_session.scalar(
        select(Payment).where(Payment.booking_id == uuid.UUID(booking_id))
    )
    assert payment is not None
    assert payment.status == "SUCCESS"

    # No refund record created
    refund = db_session.scalar(
        select(Refund).where(Refund.booking_id == uuid.UUID(booking_id))
    )
    assert refund is None


def test_cancellation_1_hour_before_gives_no_refund(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=1
    )

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["refund"]["eligible"] is False
    assert Decimal(str(data["refund"]["amount"])) == Decimal("0.00")


def test_refund_amount_equals_original_successful_payment_amount(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    expected_rate = Decimal("950.00")
    court = create_test_court_with_pricing(db_session, expected_rate)
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(str(data["refund"]["amount"])) == expected_rate


def test_failed_provider_refund_does_not_restore_booking(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.set_next_refund_outcome("FAILED", "Simulated gateway error")

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["booking_status"] == "CANCELLED"
    assert data["refund"]["status"] == "FAILED"

    # Booking and reservation remain cancelled!
    booking = db_session.get(Booking, uuid.UUID(booking_id))
    assert booking is not None
    assert booking.status == "CANCELLED"

    res = db_session.get(Reservation, booking.reservation_id)
    assert res is not None
    assert res.status == "CANCELLED"

    # Refund record in DB is FAILED with failure reason
    refund = db_session.scalar(
        select(Refund).where(Refund.booking_id == uuid.UUID(booking_id))
    )
    assert refund is not None
    assert refund.status == "FAILED"
    assert "Simulated gateway error" in str(refund.failure_reason)


def test_successful_refund_updates_refund_and_payment_statuses(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert resp.status_code == 200

    refund = db_session.scalar(
        select(Refund).where(Refund.booking_id == uuid.UUID(booking_id))
    )
    assert refund is not None
    assert refund.status == "SUCCESS"
    assert refund.provider_refund_id is not None

    payment = db_session.scalar(
        select(Payment).where(Payment.booking_id == uuid.UUID(booking_id))
    )
    assert payment is not None
    assert payment.status == "REFUNDED"


def test_repeated_cancellation_does_not_create_duplicate_refund(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    idem_key = f"cancel-{uuid.uuid4()}"
    headers = {**member_headers, "Idempotency-Key": idem_key}

    resp1 = client.post(f"/bookings/{booking_id}/cancel", headers=headers)
    assert resp1.status_code == 200

    # Repeat with same key
    resp2 = client.post(f"/bookings/{booking_id}/cancel", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["booking_status"] == "CANCELLED"

    # Exactly 1 refund in DB
    refunds = list(
        db_session.scalars(
            select(Refund).where(Refund.booking_id == uuid.UUID(booking_id))
        ).all()
    )
    assert len(refunds) == 1


def test_retrying_refund_does_not_create_duplicate_provider_transaction(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.set_next_refund_outcome("FAILED", "Simulated timeout")

    # Cancel booking: provider fails, refund is FAILED
    cancel_resp = client.post(
        f"/bookings/{booking_id}/cancel", headers=member_headers
    )
    assert cancel_resp.status_code == 200

    refund = db_session.scalar(
        select(Refund).where(Refund.booking_id == uuid.UUID(booking_id))
    )
    assert refund is not None
    assert refund.status == "FAILED"

    # Retry the refund via retry endpoint
    retry_resp = client.post(
        f"/bookings/{booking_id}/refund/retry", headers=member_headers
    )
    assert retry_resp.status_code == 200
    retry_data = retry_resp.json()
    assert retry_data["refund_status"] == "SUCCESS"

    db_session.refresh(refund)
    assert refund.status == "SUCCESS"
    provider_refund_id = refund.provider_refund_id

    # Retry again when already SUCCESS: idempotent, no new provider transaction
    retry_again = client.post(
        f"/bookings/{booking_id}/refund/retry", headers=member_headers
    )
    assert retry_again.status_code == 200
    assert retry_again.json()["provider_refund_id"] == provider_refund_id


# ============================================================================
# 3. GET /bookings/{id}/refund Endpoint & RBAC Tests
# ============================================================================


def test_get_booking_refund_endpoint_success(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    client.post(f"/bookings/{booking_id}/cancel", headers=member_headers)

    resp = client.get(f"/bookings/{booking_id}/refund", headers=member_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["booking_id"] == booking_id
    assert data["refund_eligible"] is True
    assert Decimal(str(data["refund_amount"])) == Decimal("500.00")
    assert data["refund_status"] == "SUCCESS"
    assert data["created_at"] is not None


def test_get_booking_refund_when_no_refund_initiated(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    # Booking is CONFIRMED, no refund initiated yet
    resp = client.get(f"/bookings/{booking_id}/refund", headers=member_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["refund_eligible"] is False
    assert data["refund_status"] is None
    assert "no refund was initiated" in data["message"].lower()


def test_get_booking_refund_rbac(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
    staff_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    _, booking_id = create_confirmed_booking(
        client, member_headers, court, hours_from_now=48
    )

    client.post(f"/bookings/{booking_id}/cancel", headers=member_headers)

    # Other member cannot view refund info
    resp_other = client.get(
        f"/bookings/{booking_id}/refund", headers=other_member_headers
    )
    assert resp_other.status_code == 403

    # Staff can view refund info
    resp_staff = client.get(
        f"/bookings/{booking_id}/refund", headers=staff_headers
    )
    assert resp_staff.status_code == 200
    assert resp_staff.json()["refund_status"] == "SUCCESS"

    # Admin can view refund info
    resp_admin = client.get(
        f"/bookings/{booking_id}/refund", headers=admin_headers
    )
    assert resp_admin.status_code == 200
    assert resp_admin.json()["refund_status"] == "SUCCESS"
