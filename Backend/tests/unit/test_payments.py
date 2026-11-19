import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.court import Court
from app.models.hold import Hold
from app.models.payment import Payment, PaymentStatus
from app.models.pricing_rules import PricingRule
from app.models.user import User
from app.models.venue import Venue
from app.providers.mock_payment_provider import (
    MockPaymentProvider,
    get_payment_provider,
)


@pytest.fixture(autouse=True)
def reset_mock_provider() -> None:
    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.reset()


def create_test_court_with_pricing(
    db_session: Session, hourly_rate: Decimal = Decimal("500.00")
) -> Court:
    venue = Venue(
        name=f"Payment Venue {uuid.uuid4().hex[:6]}",
        address="100 Payment Way",
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


# ============================================================================
# 1. Payment Creation and Retrieval Tests
# ============================================================================


def test_payment_creation_and_retrieval_by_id(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    member_user: User,
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    hold_id = create_active_hold(client, member_headers, court)

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    booking_data = confirm_resp.json()
    assert booking_data["status"] == "CONFIRMED"
    assert "payment" in booking_data and booking_data["payment"] is not None

    payment_info = booking_data["payment"]
    payment_id = payment_info["id"]
    assert payment_info["amount"] == "500.00"
    assert payment_info["currency"] == "ETB"
    assert payment_info["status"] == "SUCCESS"
    assert payment_info["provider"] == "MOCK"

    # Retrieve by ID
    get_resp = client.get(f"/payments/{payment_id}", headers=member_headers)
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["id"] == payment_id
    assert get_data["booking_id"] == booking_data["id"]
    assert get_data["amount"] == "500.00"
    assert get_data["status"] == "SUCCESS"


def test_payment_retrieval_by_reference(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("300.00"))
    hold_id = create_active_hold(client, member_headers, court)

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    payment_ref = confirm_resp.json()["payment"]["payment_reference"]

    ref_resp = client.get(f"/payments/reference/{payment_ref}", headers=member_headers)
    assert ref_resp.status_code == 200
    ref_data = ref_resp.json()
    assert ref_data["payment_reference"] == payment_ref
    assert ref_data["amount"] == "300.00"


def test_unknown_payment_returns_404(
    client: TestClient, member_headers: dict[str, str]
) -> None:
    random_uuid = uuid.uuid4()
    resp = client.get(f"/payments/{random_uuid}", headers=member_headers)
    assert resp.status_code == 404

    ref_resp = client.get("/payments/reference/PAY-NONEXISTENT", headers=member_headers)
    assert ref_resp.status_code == 404


def test_unauthorized_user_cannot_access_another_members_payment(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("400.00"))
    hold_id = create_active_hold(client, member_headers, court)

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    payment_id = confirm_resp.json()["payment"]["id"]
    payment_ref = confirm_resp.json()["payment"]["payment_reference"]

    # Other member attempts access
    id_resp = client.get(f"/payments/{payment_id}", headers=other_member_headers)
    assert id_resp.status_code == 403

    ref_resp = client.get(f"/payments/reference/{payment_ref}", headers=other_member_headers)
    assert ref_resp.status_code == 403


def test_staff_and_admin_can_access_any_payment(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    staff_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("250.00"))
    hold_id = create_active_hold(client, member_headers, court)

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    payment_id = confirm_resp.json()["payment"]["id"]

    staff_resp = client.get(f"/payments/{payment_id}", headers=staff_headers)
    assert staff_resp.status_code == 200

    admin_resp = client.get(f"/payments/{payment_id}", headers=admin_headers)
    assert admin_resp.status_code == 200


def test_unauthenticated_request_rejected(client: TestClient) -> None:
    resp = client.get(f"/payments/{uuid.uuid4()}")
    assert resp.status_code == 401


# ============================================================================
# 2. Payment Processing & Provider Abstraction Tests
# ============================================================================


def test_mock_payment_provider_direct() -> None:
    provider = get_payment_provider()
    # Successful payment
    res = provider.initiate_payment(
        amount=Decimal("100.00"),
        currency="ETB",
        payment_reference="PAY-TEST-001",
    )
    assert res.success is True
    assert res.status == "SUCCESS"
    assert res.provider_transaction_id is not None
    assert "mock_txn_" in res.provider_transaction_id

    # Verification
    ver = provider.verify_payment(res.provider_transaction_id)
    assert ver.success is True
    assert ver.status == "SUCCESS"

    # Refund
    rf = provider.refund_payment(
        provider_transaction_id=res.provider_transaction_id,
        amount=Decimal("100.00"),
        currency="ETB",
    )
    assert rf.success is True
    assert rf.status == "REFUNDED"
    assert rf.refund_transaction_id is not None


def test_mock_payment_failure_simulation() -> None:
    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.set_next_payment_outcome("FAILED", "Simulated insufficient funds")

    res = provider.initiate_payment(
        amount=Decimal("150.00"),
        currency="ETB",
        payment_reference="PAY-TEST-FAIL",
    )
    assert res.success is False
    assert res.status == "FAILED"
    assert res.error_message == "Simulated insufficient funds"


def test_mock_payment_pending_simulation() -> None:
    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.set_next_payment_outcome("PENDING")

    res = provider.initiate_payment(
        amount=Decimal("200.00"),
        currency="ETB",
        payment_reference="PAY-TEST-PEND",
    )
    assert res.success is False
    assert res.status == "PENDING"


def test_mock_payment_invalid_response_simulation() -> None:
    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.should_return_invalid_response = True

    res = provider.initiate_payment(
        amount=Decimal("100.00"),
        currency="ETB",
        payment_reference="PAY-TEST-INV",
    )
    assert res.success is False
    assert res.status == "INVALID"


def test_duplicate_transaction_id_db_constraint(
    client: TestClient, db_session: Session, member_headers: dict[str, str]
) -> None:
    court = create_test_court_with_pricing(db_session)
    hold_id = create_active_hold(client, member_headers, court)

    txn_id = f"test_dup_{uuid.uuid4().hex}"
    p1 = Payment(
        provider="MOCK",
        provider_transaction_id=txn_id,
        payment_reference=f"PAY-DUP-1-{uuid.uuid4().hex[:6]}",
        amount=Decimal("100.00"),
        currency="ETB",
        status=PaymentStatus.SUCCESS.value,
        hold_id=uuid.UUID(hold_id),
    )
    db_session.add(p1)
    db_session.flush()

    # Create another hold
    hold_id_2 = create_active_hold(client, member_headers, court, hours_from_now=72)
    p2 = Payment(
        provider="MOCK",
        provider_transaction_id=txn_id,
        payment_reference=f"PAY-DUP-2-{uuid.uuid4().hex[:6]}",
        amount=Decimal("100.00"),
        currency="ETB",
        status=PaymentStatus.SUCCESS.value,
        hold_id=uuid.UUID(hold_id_2),
    )
    db_session.add(p2)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# ============================================================================
# 3. Hold Confirmation with Payment Tests
# ============================================================================


def test_successful_payment_creates_booking_and_associates_payment(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    member_user: User,
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("600.00"))
    hold_id = create_active_hold(client, member_headers, court)

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    booking_data = confirm_resp.json()
    booking_id = booking_data["id"]

    # Verify booking in DB
    booking_in_db = db_session.get(Booking, uuid.UUID(booking_id))
    assert booking_in_db is not None
    assert booking_in_db.status == "CONFIRMED"
    assert booking_in_db.total_price == Decimal("600.00")

    # Verify hold in DB
    hold_in_db = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold_in_db is not None
    assert hold_in_db.status == "CONFIRMED"

    # Verify payment in DB
    stmt = select(Payment).where(Payment.booking_id == booking_in_db.id)
    payment_in_db = db_session.scalar(stmt)
    assert payment_in_db is not None
    assert payment_in_db.status == "SUCCESS"
    assert payment_in_db.hold_id is None  # Satisfies mutually exclusive hold/booking constraint
    assert payment_in_db.amount == Decimal("600.00")


def test_failed_payment_does_not_create_confirmed_booking(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    hold_id = create_active_hold(client, member_headers, court)

    # Configure mock provider to fail
    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.set_next_payment_outcome("FAILED", "Simulated card decline")

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 400
    assert "Payment failed" in confirm_resp.json()["detail"] or "decline" in confirm_resp.json()["detail"]

    # Verify no booking created
    stmt = select(Booking).where(Booking.hold_id == uuid.UUID(hold_id))
    booking = db_session.scalar(stmt)
    assert booking is None

    # Hold remains unconfirmed (ACTIVE)
    hold_in_db = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold_in_db is not None
    assert hold_in_db.status == "ACTIVE"

    # Payment record reflects FAILED status
    p_stmt = select(Payment).where(Payment.hold_id == uuid.UUID(hold_id))
    payment = db_session.scalar(p_stmt)
    assert payment is not None
    assert payment.status == "FAILED"


def test_pending_payment_does_not_confirm_booking(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    hold_id = create_active_hold(client, member_headers, court)

    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.set_next_payment_outcome("PENDING")

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 400
    detail = confirm_resp.json()["detail"].lower()
    assert "pending" in detail or "processing" in detail

    # No booking created
    booking = db_session.scalar(select(Booking).where(Booking.hold_id == uuid.UUID(hold_id)))
    assert booking is None

    # Hold remains ACTIVE
    hold = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold is not None
    assert hold.status == "ACTIVE"


def test_expired_hold_cannot_be_confirmed_with_payment(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session)
    hold_id = create_active_hold(client, member_headers, court)

    # Force expiration
    hold = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold is not None
    hold.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 400
    assert "expired" in confirm_resp.json()["detail"].lower()


def test_another_user_cannot_confirm_someone_elses_hold(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session)
    hold_id = create_active_hold(client, member_headers, court)

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=other_member_headers)
    assert confirm_resp.status_code == 403


def test_repeated_confirmation_returns_existing_booking_idempotently(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    hold_id = create_active_hold(client, member_headers, court)

    resp1 = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert resp1.status_code == 200
    booking1 = resp1.json()

    # Second request
    resp2 = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert resp2.status_code == 200
    booking2 = resp2.json()

    assert booking1["id"] == booking2["id"]

    # Exactly one booking and one payment record exist in DB
    bookings = db_session.scalars(select(Booking).where(Booking.hold_id == uuid.UUID(hold_id))).all()
    assert len(bookings) == 1

    payments = db_session.scalars(select(Payment).where(Payment.booking_id == uuid.UUID(booking1["id"]))).all()
    assert len(payments) == 1


# ============================================================================
# 4. Refund Integration Tests (POST /bookings/{id}/cancel)
# ============================================================================


def test_cancellation_at_least_24h_before_start_triggers_full_refund(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("700.00"))
    # Hold is 48 hours in future (>= 24 hours)
    hold_id = create_active_hold(client, member_headers, court, hours_from_now=48)

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    booking_id = confirm_resp.json()["id"]

    # Cancel booking
    cancel_resp = client.post(f"/bookings/{booking_id}/cancel", headers=member_headers)
    assert cancel_resp.status_code == 200
    cancelled_data = cancel_resp.json()
    assert cancelled_data["status"] == "CANCELLED"
    assert cancelled_data["cancelled_at"] is not None

    # Check payment status in DB: must be REFUNDED
    payment = db_session.scalar(select(Payment).where(Payment.booking_id == uuid.UUID(booking_id)))
    assert payment is not None
    assert payment.status == "REFUNDED"


def test_cancellation_less_than_24h_before_start_does_not_trigger_refund(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("700.00"))
    # Hold is only 12 hours in future (< 24 hours)
    hold_id = create_active_hold(client, member_headers, court, hours_from_now=12)

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    booking_id = confirm_resp.json()["id"]

    # Cancel booking
    cancel_resp = client.post(f"/bookings/{booking_id}/cancel", headers=member_headers)
    assert cancel_resp.status_code == 200
    cancelled_data = cancel_resp.json()
    assert cancelled_data["status"] == "CANCELLED"

    # Payment status must remain SUCCESS (no refund issued)
    payment = db_session.scalar(select(Payment).where(Payment.booking_id == uuid.UUID(booking_id)))
    assert payment is not None
    assert payment.status == "SUCCESS"


def test_duplicate_cancellation_does_not_cause_duplicate_refunds(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    hold_id = create_active_hold(client, member_headers, court, hours_from_now=48)
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    booking_id = confirm_resp.json()["id"]

    # Cancel once
    resp1 = client.post(f"/bookings/{booking_id}/cancel", headers=member_headers)
    assert resp1.status_code == 200

    # Cancel second time: should return existing cancelled booking idempotently
    resp2 = client.post(f"/bookings/{booking_id}/cancel", headers=member_headers)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "CANCELLED"

    payment = db_session.scalar(select(Payment).where(Payment.booking_id == uuid.UUID(booking_id)))
    assert payment is not None
    assert payment.status == "REFUNDED"


def test_failed_refund_handled_correctly(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    hold_id = create_active_hold(client, member_headers, court, hours_from_now=48)
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    booking_id = confirm_resp.json()["id"]

    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.set_next_refund_outcome("FAILED", "Simulated refund gateway failure")

    cancel_resp = client.post(f"/bookings/{booking_id}/cancel", headers=member_headers)
    assert cancel_resp.status_code == 400
    assert "refund" in cancel_resp.json()["detail"].lower()

    # Booking remains CONFIRMED due to rollback
    booking = db_session.get(Booking, uuid.UUID(booking_id))
    assert booking is not None
    assert booking.status == "CONFIRMED"


def test_pending_refund_represented_correctly(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    hold_id = create_active_hold(client, member_headers, court, hours_from_now=48)
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    booking_id = confirm_resp.json()["id"]

    provider = get_payment_provider()
    if isinstance(provider, MockPaymentProvider):
        provider.set_next_refund_outcome("REFUND_PENDING")

    cancel_resp = client.post(f"/bookings/{booking_id}/cancel", headers=member_headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    payment = db_session.scalar(select(Payment).where(Payment.booking_id == uuid.UUID(booking_id)))
    assert payment is not None
    assert payment.status == "REFUND_PENDING"


def test_unauthorized_user_cannot_cancel_booking(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session)
    hold_id = create_active_hold(client, member_headers, court, hours_from_now=48)
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    booking_id = confirm_resp.json()["id"]

    resp = client.post(f"/bookings/{booking_id}/cancel", headers=other_member_headers)
    assert resp.status_code == 403


def test_staff_and_admin_can_cancel_booking(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    staff_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session)
    hold_id = create_active_hold(client, member_headers, court, hours_from_now=48)
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    booking_id = confirm_resp.json()["id"]

    resp = client.post(f"/bookings/{booking_id}/cancel", headers=staff_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"


# ============================================================================
# 5. Idempotency and Recovery Tests
# ============================================================================


def test_idempotency_key_header_retry(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("450.00"))
    hold_id = create_active_hold(client, member_headers, court)

    idem_key = f"idem-{uuid.uuid4()}"
    headers = {**member_headers, "Idempotency-Key": idem_key}

    # Initial confirmation
    resp1 = client.post(f"/holds/{hold_id}/confirm", headers=headers)
    assert resp1.status_code == 200
    booking1 = resp1.json()

    # Retry with same key
    resp2 = client.post(f"/holds/{hold_id}/confirm", headers=headers)
    assert resp2.status_code == 200
    booking2 = resp2.json()

    assert booking1["id"] == booking2["id"]


def test_reuse_of_idempotency_key_with_different_request_rejected(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("450.00"))
    hold_id_1 = create_active_hold(client, member_headers, court)
    hold_id_2 = create_active_hold(client, member_headers, court, hours_from_now=72)

    idem_key = f"shared-key-{uuid.uuid4()}"
    headers = {**member_headers, "Idempotency-Key": idem_key}

    # Request 1 with idem_key
    resp1 = client.post(f"/holds/{hold_id_1}/confirm", headers=headers)
    assert resp1.status_code == 200

    # Request 2 reuses idem_key with different hold
    resp2 = client.post(f"/holds/{hold_id_2}/confirm", headers=headers)
    assert resp2.status_code == 409
    assert "different parameters" in resp2.json()["detail"].lower()


def test_reconciliation_of_successful_payment_on_retry(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
    member_user: User,
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    hold_id = create_active_hold(client, member_headers, court)

    # Simulate situation: Payment already succeeded at provider and is in DB attached to hold,
    # but booking was not created yet due to a transient failure
    payment = Payment(
        hold_id=uuid.UUID(hold_id),
        booking_id=None,
        provider="MOCK",
        provider_transaction_id=f"mock_txn_{uuid.uuid4().hex}",
        payment_reference=f"PAY-RECON-{uuid.uuid4().hex[:8].upper()}",
        amount=Decimal("500.00"),
        currency="ETB",
        status=PaymentStatus.SUCCESS.value,
    )
    db_session.add(payment)
    db_session.commit()

    # Retrying confirm_hold should recognize the successful payment, reconcile, and confirm booking
    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_resp.status_code == 200
    booking_data = confirm_resp.json()
    assert booking_data["status"] == "CONFIRMED"

    # Payment is now attached to booking
    db_session.refresh(payment)
    assert payment.booking_id == uuid.UUID(booking_data["id"])
    assert payment.hold_id is None
    assert payment.status == "SUCCESS"


# ============================================================================
# 6. Webhook Endpoint Tests
# ============================================================================


def test_webhook_successful_verification(
    client: TestClient,
    db_session: Session,
    member_headers: dict[str, str],
) -> None:
    court = create_test_court_with_pricing(db_session, Decimal("500.00"))
    hold_id = create_active_hold(client, member_headers, court)

    confirm_resp = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    payment_info = confirm_resp.json()["payment"]
    txn_id = payment_info["provider_transaction_id"]

    webhook_payload = {
        "provider": "MOCK",
        "provider_transaction_id": txn_id,
        "event_type": "payment.succeeded",
        "signature": "valid_signature_123",
        "status": "SUCCESS",
    }
    resp = client.post("/payments/webhook", json=webhook_payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"


def test_webhook_invalid_signature_rejected(client: TestClient) -> None:
    webhook_payload = {
        "provider": "MOCK",
        "provider_transaction_id": "mock_txn_123",
        "event_type": "payment.succeeded",
        "signature": "invalid_sig",
    }
    resp = client.post("/payments/webhook", json=webhook_payload)
    assert resp.status_code == 401
