import datetime
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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


def test_confirm_hold_success(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    start_time = now + datetime.timedelta(days=2)
    end_time = start_time + datetime.timedelta(hours=1)

    # 1. Create a hold
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

    # 2. Confirm the hold
    confirm_res = client.post(
        f"/holds/{hold_id}/confirm",
        headers={**member_headers, "Idempotency-Key": f"test-key-{uuid.uuid4()}"},
    )
    assert confirm_res.status_code == 200
    booking_data = confirm_res.json()
    assert booking_data["hold_id"] == hold_id
    assert booking_data["status"] == "CONFIRMED"
    assert booking_data["court_id"] == str(test_court.id)
    assert booking_data["user_id"] == str(member_user.id)
    assert Decimal(str(booking_data["total_price"])) > Decimal("0.00")

    # 3. Verify DB state consistency
    hold_db = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold_db is not None
    assert hold_db.status == "CONFIRMED"
    assert hold_db.reservation is not None
    assert hold_db.reservation.status == "CONFIRMED"
    assert hold_db.reservation.expires_at is None

    booking_db = db_session.get(Booking, uuid.UUID(booking_data["id"]))
    assert booking_db is not None
    assert booking_db.status == "CONFIRMED"
    assert booking_db.reservation_id == hold_db.reservation_id

    # Verify payment record created and linked
    payments = db_session.scalars(
        select(Payment).where(Payment.booking_id == booking_db.id)
    ).all()
    assert len(payments) == 1
    assert payments[0].status == PaymentStatus.SUCCESS.value
    assert payments[0].amount == booking_db.total_price


def test_confirm_hold_repeated_idempotent_returns_same_booking(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    start_time = now + datetime.timedelta(days=3)
    end_time = start_time + datetime.timedelta(hours=1)

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

    idempotency_key = f"idemp-{uuid.uuid4()}"
    headers = {**member_headers, "Idempotency-Key": idempotency_key}

    # First confirmation
    res1 = client.post(f"/holds/{hold_id}/confirm", headers=headers)
    assert res1.status_code == 200
    booking1 = res1.json()

    # Second confirmation with same idempotency key
    res2 = client.post(f"/holds/{hold_id}/confirm", headers=headers)
    assert res2.status_code == 200
    booking2 = res2.json()

    # Must be identical booking
    assert booking1["id"] == booking2["id"]

    # Third confirmation without header, should also return existing booking since hold is CONFIRMED
    res3 = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert res3.status_code == 200
    assert res3.json()["id"] == booking1["id"]

    # Verify database has only 1 booking and 1 payment
    bookings = db_session.scalars(
        select(Booking).where(Booking.hold_id == uuid.UUID(hold_id))
    ).all()
    assert len(bookings) == 1

    payments = db_session.scalars(
        select(Payment).where(Payment.booking_id == bookings[0].id)
    ).all()
    assert len(payments) == 1


def test_confirm_hold_rejects_another_members_hold(
    client: TestClient,
    member_headers: dict[str, str],
    other_member_headers: dict[str, str],
    test_court: Court,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (now + datetime.timedelta(days=4)).isoformat(),
            "end_time": (now + datetime.timedelta(days=4, hours=1)).isoformat(),
        },
        headers=member_headers,
    )
    hold_id = hold_res.json()["id"]

    # Other member attempts confirmation
    res = client.post(f"/holds/{hold_id}/confirm", headers=other_member_headers)
    assert res.status_code == 403
    assert "permission" in res.json()["detail"].lower()


def test_confirm_hold_rejects_expired_hold(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (now + datetime.timedelta(days=5)).isoformat(),
            "end_time": (now + datetime.timedelta(days=5, hours=1)).isoformat(),
        },
        headers=member_headers,
    )
    hold_id = hold_res.json()["id"]

    # Force expiration in DB
    hold_db = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold_db is not None
    past = now - datetime.timedelta(minutes=10)
    hold_db.expires_at = past
    if hold_db.reservation:
        hold_db.reservation.expires_at = past
    db_session.commit()

    res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert res.status_code == 400
    assert "expired" in res.json()["detail"].lower()


def test_confirm_hold_rejects_cancelled_hold(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (now + datetime.timedelta(days=6)).isoformat(),
            "end_time": (now + datetime.timedelta(days=6, hours=1)).isoformat(),
        },
        headers=member_headers,
    )
    hold_id = hold_res.json()["id"]

    # Cancel hold first
    cancel_res = client.delete(f"/holds/{hold_id}", headers=member_headers)
    assert cancel_res.status_code == 200

    # Attempt to confirm cancelled hold
    confirm_res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_res.status_code == 400
    assert "cancelled" in confirm_res.json()["detail"].lower()


def test_confirm_hold_payment_failure_rolls_back(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = get_payment_provider()
    assert isinstance(provider, MockPaymentProvider)
    provider.set_next_payment_outcome("FAILED", error_message="Insufficient member funds")

    now = datetime.datetime.now(datetime.UTC)
    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (now + datetime.timedelta(days=7)).isoformat(),
            "end_time": (now + datetime.timedelta(days=7, hours=1)).isoformat(),
        },
        headers=member_headers,
    )
    hold_id = hold_res.json()["id"]

    # Confirmation fails due to payment failure
    confirm_res = client.post(f"/holds/{hold_id}/confirm", headers=member_headers)
    assert confirm_res.status_code == 400
    assert "funds" in confirm_res.json()["detail"].lower() or "payment" in confirm_res.json()["detail"].lower()

    # Reset mock provider
    provider.reset()

    # Verify no booking was created
    bookings = db_session.scalars(
        select(Booking).where(Booking.hold_id == uuid.UUID(hold_id))
    ).all()
    assert len(bookings) == 0

    # Verify hold was not marked CONFIRMED
    hold_db = db_session.get(Hold, uuid.UUID(hold_id))
    assert hold_db is not None
    assert hold_db.status != "CONFIRMED"


def test_confirm_hold_idempotency_key_payload_mismatch(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    # Create two different holds
    h1 = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (now + datetime.timedelta(days=8)).isoformat(),
            "end_time": (now + datetime.timedelta(days=8, hours=1)).isoformat(),
        },
        headers=member_headers,
    ).json()["id"]

    h2 = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": (now + datetime.timedelta(days=9)).isoformat(),
            "end_time": (now + datetime.timedelta(days=9, hours=1)).isoformat(),
        },
        headers=member_headers,
    ).json()["id"]

    key = f"conflict-key-{uuid.uuid4()}"
    # Confirm h1 with key
    res1 = client.post(f"/holds/{h1}/confirm", headers={**member_headers, "Idempotency-Key": key})
    assert res1.status_code == 200

    # Attempt to confirm h2 with SAME key -> 409 conflict
    res2 = client.post(f"/holds/{h2}/confirm", headers={**member_headers, "Idempotency-Key": key})
    assert res2.status_code == 409
    assert "idempotency" in res2.json()["detail"].lower()
