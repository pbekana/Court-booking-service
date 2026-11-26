import uuid
from datetime import UTC, datetime, timedelta
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
from app.models.user import User
from app.providers.mock_payment_provider import (
    MockPaymentProvider,
    get_payment_provider,
)


def test_payment_creation_and_success_flow(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    start_time = now + timedelta(days=2)
    end_time = start_time + timedelta(hours=1)

    # Create hold
    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers=member_headers,
    )
    assert hold_res.status_code == 201
    hold_id = hold_res.json()["id"]

    # Confirm hold (triggers payment initiation & verification)
    confirm_res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_res.status_code == 200
    booking_data = confirm_res.json()
    booking_id = uuid.UUID(booking_data["id"])

    # Query payment by booking_id
    payment = db_session.scalar(
        select(Payment).where(Payment.booking_id == booking_id)
    )
    assert payment is not None
    assert payment.status == PaymentStatus.SUCCESS.value
    assert payment.amount == Decimal(str(booking_data["total_price"]))
    assert payment.currency == "ETB"
    assert payment.payment_reference.startswith("PAY-")
    assert payment.booking_id == booking_id
    assert payment.hold_id is None

    # Retrieve payment by ID endpoint
    get_payment_res = client.get(f"/payments/{payment.id}", headers=member_headers)
    assert get_payment_res.status_code == 200
    assert get_payment_res.json()["id"] == str(payment.id)
    assert get_payment_res.json()["status"] == "SUCCESS"

    # Retrieve payment by reference endpoint
    ref_res = client.get(
        f"/payments/reference/{payment.payment_reference}",
        headers=member_headers,
    )
    assert ref_res.status_code == 200
    assert ref_res.json()["payment_reference"] == payment.payment_reference


def test_payment_failure_flow(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    provider = get_payment_provider()
    assert isinstance(provider, MockPaymentProvider)
    provider.set_next_payment_outcome("FAILED", error_message="Insufficient balance")

    now = datetime.now(UTC)
    start_time = now + timedelta(days=3)
    end_time = start_time + timedelta(hours=1)

    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers=member_headers,
    )
    hold_id = uuid.UUID(hold_res.json()["id"])

    # Confirmation fails
    confirm_res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_res.status_code == 400
    assert "insufficient" in confirm_res.json()["detail"].lower()
    provider.reset()

    # Payment record in DB must be FAILED or rolled back, no booking created
    booking = db_session.scalar(select(Booking).where(Booking.hold_id == hold_id))
    assert booking is None

    hold_db = db_session.get(Hold, hold_id)
    assert hold_db is not None
    assert hold_db.status != "CONFIRMED"


def test_payment_webhook_and_duplicate_deliveries(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    start_time = now + timedelta(days=4)
    end_time = start_time + timedelta(hours=1)

    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers=member_headers,
    )
    hold_id = hold_res.json()["id"]

    confirm_res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_res.status_code == 200
    booking_id = uuid.UUID(confirm_res.json()["id"])

    payment = db_session.scalar(
        select(Payment).where(Payment.booking_id == booking_id)
    )
    assert payment is not None

    # Invalid signature rejected
    bad_sig_payload = {
        "provider": payment.provider,
        "provider_transaction_id": payment.provider_transaction_id or "tx-test",
        "event_type": "payment.success",
        "signature": "invalid_sig",
    }
    assert client.post("/payments/webhook", json=bad_sig_payload).status_code == 401

    # Valid webhook delivery
    valid_payload = {
        "provider": payment.provider,
        "provider_transaction_id": payment.provider_transaction_id or "tx-test",
        "event_type": "payment.success",
        "signature": "valid_signature_hash",
        "payment_reference": payment.payment_reference,
    }
    webhook_res1 = client.post("/payments/webhook", json=valid_payload)
    assert webhook_res1.status_code == 200
    assert webhook_res1.json()["id"] == str(payment.id)

    # Duplicate webhook delivery handled safely (idempotent)
    webhook_res2 = client.post("/payments/webhook", json=valid_payload)
    assert webhook_res2.status_code == 200
    assert webhook_res2.json()["id"] == str(payment.id)


def test_payment_authorization_restrictions(
    client: TestClient,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
    admin_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (now + timedelta(days=5)).isoformat(),
            "end_time": (now + timedelta(days=5, hours=1)).isoformat(),
        },
        headers=member_headers,
    )
    hold_id = hold_res.json()["id"]
    confirm_res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_res.status_code == 200
    booking_id = uuid.UUID(confirm_res.json()["id"])

    payment = db_session.scalar(
        select(Payment).where(Payment.booking_id == booking_id)
    )
    assert payment is not None

    # Other member cannot view payment
    assert client.get(f"/payments/{payment.id}", headers=other_member_headers).status_code == 403
    assert client.get(f"/payments/reference/{payment.payment_reference}", headers=other_member_headers).status_code == 403

    # Admin can view payment
    admin_get = client.get(f"/payments/{payment.id}", headers=admin_headers)
    assert admin_get.status_code == 200


def test_payment_reference_uniqueness_constraint(
    db_session: Session,
    member_user: User,
    test_court: Court,
) -> None:
    ref = f"PAY-UNIQUE-{uuid.uuid4().hex[:8]}"
    p1 = Payment(
        hold_id=None,
        booking_id=None,
        provider="MOCK",
        payment_reference=ref,
        amount=Decimal("50.00"),
        status=PaymentStatus.SUCCESS.value,
    )
    # Note: payments_check constraint requires either booking_id or hold_id not null
    # Create a hold to link
    now = datetime.now(UTC)
    h1 = Hold(
        user_id=member_user.id,
        court_id=test_court.id,
        start_time=now + timedelta(days=6),
        end_time=now + timedelta(days=6, hours=1),
        expires_at=now + timedelta(days=6),
        status="ACTIVE",
    )
    db_session.add(h1)
    db_session.flush()

    p1.hold_id = h1.id
    db_session.add(p1)
    db_session.commit()

    # Second payment with same payment_reference
    h2 = Hold(
        user_id=member_user.id,
        court_id=test_court.id,
        start_time=now + timedelta(days=7),
        end_time=now + timedelta(days=7, hours=1),
        expires_at=now + timedelta(days=7),
        status="ACTIVE",
    )
    db_session.add(h2)
    db_session.flush()

    p2 = Payment(
        hold_id=h2.id,
        booking_id=None,
        provider="MOCK",
        payment_reference=ref,
        amount=Decimal("50.00"),
        status=PaymentStatus.SUCCESS.value,
    )
    db_session.add(p2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
