import datetime
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingStatus
from app.models.court import Court
from app.models.hold import Hold
from app.models.payment import Payment, PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.models.reservations import Reservation
from app.models.user import User
from app.providers.mock_payment_provider import (
    MockPaymentProvider,
    get_payment_provider,
)


def _create_confirmed_booking(
    db_session: Session,
    user: User,
    court: Court,
    start_at: datetime.datetime,
    duration_hours: int = 1,
    amount: Decimal = Decimal("100.00"),
) -> tuple[Booking, Payment]:
    end_at = start_at + datetime.timedelta(hours=duration_hours)

    res = Reservation(
        user_id=user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        status="CONFIRMED",
        expires_at=None,
    )
    db_session.add(res)
    db_session.flush()

    hold = Hold(
        user_id=user.id,
        court_id=court.id,
        reservation_id=res.id,
        start_time=start_at,
        end_time=end_at,
        expires_at=start_at,
        status="CONFIRMED",
    )
    db_session.add(hold)
    db_session.flush()

    booking = Booking(
        hold_id=hold.id,
        reservation_id=res.id,
        user_id=user.id,
        court_id=court.id,
        start_at=start_at,
        end_at=end_at,
        total_price=amount,
        currency="ETB",
        status="CONFIRMED",
    )
    db_session.add(booking)
    db_session.flush()

    payment = Payment(
        booking_id=booking.id,
        hold_id=None,
        provider="MOCK",
        payment_reference=f"PAY-{uuid.uuid4().hex[:10].upper()}",
        provider_transaction_id=f"tx-{uuid.uuid4().hex[:8]}",
        amount=amount,
        currency="ETB",
        status=PaymentStatus.SUCCESS.value,
    )
    db_session.add(payment)
    db_session.commit()
    return booking, payment


def test_cancel_booking_more_than_24h_full_refund(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    # Start time is 48 hours in future (> 24 hours)
    start_at = now + datetime.timedelta(hours=48)
    booking, _payment = _create_confirmed_booking(
        db_session, member_user, test_court, start_at, amount=Decimal("200.00")
    )

    response = client.post(f"/bookings/{booking.id}/cancel", headers=member_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["booking_id"] == str(booking.id)
    assert data["status"] == "CANCELLED"
    assert data["refund"]["eligible"] is True
    assert Decimal(str(data["refund"]["amount"])) == Decimal("200.00")
    assert data["refund"]["status"] == "SUCCESS"

    # Database state verification
    db_session.refresh(booking)
    assert booking.status == BookingStatus.CANCELLED.value
    assert booking.cancelled_at is not None

    res_db = db_session.get(Reservation, booking.reservation_id)
    assert res_db is not None
    assert res_db.status == "CANCELLED"

    refunds = db_session.scalars(
        select(Refund).where(Refund.booking_id == booking.id)
    ).all()
    assert len(refunds) == 1
    assert refunds[0].amount == Decimal("200.00")
    assert refunds[0].status == RefundStatus.SUCCESS.value


def test_cancel_booking_less_than_24h_no_refund(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    # Start time is 12 hours in future (< 24 hours)
    start_at = now + datetime.timedelta(hours=12)
    booking, _payment = _create_confirmed_booking(
        db_session, member_user, test_court, start_at, amount=Decimal("150.00")
    )

    response = client.post(f"/bookings/{booking.id}/cancel", headers=member_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CANCELLED"
    assert data["refund"]["eligible"] is False
    assert Decimal(str(data["refund"]["amount"])) == Decimal("0.00")

    # Verify no refund record created
    refunds = db_session.scalars(
        select(Refund).where(Refund.booking_id == booking.id)
    ).all()
    assert len(refunds) == 0

    # Court slot is freed
    db_session.refresh(booking)
    assert booking.status == "CANCELLED"


def test_cancel_booking_after_start_time_rejected(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    # Start time was 1 hour ago
    start_at = now - datetime.timedelta(hours=1)
    booking, _payment = _create_confirmed_booking(
        db_session, member_user, test_court, start_at
    )

    response = client.post(f"/bookings/{booking.id}/cancel", headers=member_headers)
    assert response.status_code == 409
    assert "already started" in response.json()["detail"].lower()


def test_cancel_booking_rejects_another_member(
    client: TestClient,
    member_user: User,
    other_member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    start_at = now + datetime.timedelta(days=3)
    booking, _payment = _create_confirmed_booking(
        db_session, member_user, test_court, start_at
    )

    response = client.post(f"/bookings/{booking.id}/cancel", headers=other_member_headers)
    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


def test_cancel_booking_nonexistent_rejected(
    client: TestClient,
    member_headers: dict[str, str],
) -> None:
    response = client.post(f"/bookings/{uuid.uuid4()}/cancel", headers=member_headers)
    assert response.status_code == 404


def test_cancel_booking_repeated_cancellation(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    start_at = now + datetime.timedelta(days=4)
    booking, _payment = _create_confirmed_booking(
        db_session, member_user, test_court, start_at
    )

    # First cancellation
    res1 = client.post(f"/bookings/{booking.id}/cancel", headers=member_headers)
    assert res1.status_code == 200

    # Second cancellation without idempotency key -> 409
    res2 = client.post(f"/bookings/{booking.id}/cancel", headers=member_headers)
    assert res2.status_code == 409
    assert "already been cancelled" in res2.json()["detail"].lower()


def test_cancel_booking_releases_court_availability(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    other_member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    start_at = (now + datetime.timedelta(days=5)).replace(
        hour=7, minute=0, second=0, microsecond=0
    )
    end_at = start_at + datetime.timedelta(hours=1)
    booking, _payment = _create_confirmed_booking(
        db_session, member_user, test_court, start_at
    )

    # Cancel booking
    cancel_res = client.post(f"/bookings/{booking.id}/cancel", headers=member_headers)
    assert cancel_res.status_code == 200

    # Check availability now returns True
    avail_res = client.get(
        f"/courts/{test_court.id}/availability",
        params={"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        headers=member_headers,
    )
    assert avail_res.status_code == 200
    assert avail_res.json()["available"] is True

    # Another member can now hold this slot
    hold_res = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": start_at.isoformat(),
            "end_time": end_at.isoformat(),
        },
        headers=other_member_headers,
    )
    assert hold_res.status_code == 201


def test_cancel_booking_payment_provider_failure_does_not_rollback_cancellation(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = get_payment_provider()
    assert isinstance(provider, MockPaymentProvider)
    provider.set_next_refund_outcome("FAILED", error_message="Provider refund gateway unavailable")

    now = datetime.datetime.now(datetime.UTC)
    start_at = now + datetime.timedelta(days=6)
    booking, _payment = _create_confirmed_booking(
        db_session, member_user, test_court, start_at, amount=Decimal("120.00")
    )

    response = client.post(f"/bookings/{booking.id}/cancel", headers=member_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CANCELLED"
    assert data["refund"]["eligible"] is True
    assert data["refund"]["status"] == "FAILED"

    # Reset mock provider
    provider.reset()

    # Verify booking is still cancelled in database despite provider refund failure
    db_session.refresh(booking)
    assert booking.status == BookingStatus.CANCELLED.value

    # Verify refund record is persisted as FAILED
    refunds = db_session.scalars(
        select(Refund).where(Refund.booking_id == booking.id)
    ).all()
    assert len(refunds) == 1
    assert refunds[0].status == RefundStatus.FAILED.value


def test_staff_can_cancel_member_booking(
    client: TestClient,
    staff_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    start_at = now + datetime.timedelta(days=7)
    booking, _payment = _create_confirmed_booking(
        db_session, member_user, test_court, start_at
    )

    # Staff cancels member's booking
    response = client.post(f"/bookings/{booking.id}/cancel", headers=staff_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
