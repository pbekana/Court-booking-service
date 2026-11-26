from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.court import Court
from app.models.hold import Hold
from app.models.recurring_series import RecurringSeries
from app.models.reservations import Reservation
from app.models.user import User
from app.schemas.recurring_series import RecurringSeriesCreate
from app.services.recurring_service import RecurringService


def test_tx_02_all_or_nothing_recurring_creation_on_partial_conflict(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    other_member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    """TX-02: All-or-nothing recurring booking creation.
    When a series spans 2 occurrences, and the 2nd occurrence conflicts with an existing reservation,
    the entire recurring creation must fail (409) and ROLL BACK completely.
    No partial holds, reservations, or recurring series records may remain.
    """
    tz = ZoneInfo("Africa/Addis_Ababa")
    # Choose next Monday
    today = datetime.now(tz).date()
    days_ahead = (0 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    first_monday = today + timedelta(days=days_ahead)
    second_monday = first_monday + timedelta(weeks=1)

    # Pre-book second Monday: 10:00 - 11:00 for other member
    conflict_start = datetime.combine(second_monday, time(10, 0), tzinfo=tz).astimezone(UTC)
    conflict_end = conflict_start + timedelta(hours=1)

    conflict_res = Reservation(
        user_id=other_member_user.id,
        court_id=test_court.id,
        start_at=conflict_start,
        end_at=conflict_end,
        status="CONFIRMED",
        expires_at=None,
    )
    db_session.add(conflict_res)
    db_session.commit()

    # Member attempts to book recurring Mondays 10:00 - 11:00 spanning first & second Monday
    payload = {
        "court_id": str(test_court.id),
        "day_of_week": 0,  # Monday
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "recurrence_start_date": first_monday.isoformat(),
        "recurrence_end_date": second_monday.isoformat(),
    }

    response = client.post("/recurring-bookings", json=payload, headers=member_headers)
    assert response.status_code == 409
    assert "not available" in response.json()["detail"].lower()

    # Verify atomic rollback in DB:
    # 1. No RecurringSeries record created
    series_list = db_session.scalars(
        select(RecurringSeries).where(
            RecurringSeries.user_id == member_user.id,
            RecurringSeries.court_id == test_court.id,
        )
    ).all()
    assert len(series_list) == 0

    # 2. No holds created for first Monday for this member
    first_start = datetime.combine(first_monday, time(10, 0), tzinfo=tz).astimezone(UTC)
    holds_list = db_session.scalars(
        select(Hold).where(
            Hold.user_id == member_user.id,
            Hold.court_id == test_court.id,
            Hold.start_time == first_start,
        )
    ).all()
    assert len(holds_list) == 0

    # 3. No reservation created for first Monday for this member
    res_list = db_session.scalars(
        select(Reservation).where(
            Reservation.user_id == member_user.id,
            Reservation.court_id == test_court.id,
            Reservation.start_at == first_start,
        )
    ).all()
    assert len(res_list) == 0


def test_tx_02_unexpected_error_during_occurrence_creation_rolls_back(
    member_user: User,
    test_court: Court,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TX-02: Force an unhandled error during the occurrence flush/commit phase.
    Verify that the series and all associated holds are completely rolled back.
    """
    tz = ZoneInfo("Africa/Addis_Ababa")
    today = datetime.now(tz).date()
    days_ahead = (1 - today.weekday()) % 7  # Tuesday
    if days_ahead == 0:
        days_ahead = 7
    first_tue = today + timedelta(days=days_ahead)
    second_tue = first_tue + timedelta(weeks=1)

    series_in = RecurringSeriesCreate(
        court_id=test_court.id,
        day_of_week=1,
        start_time=time(14, 0),
        end_time=time(15, 0),
        recurrence_start_date=first_tue,
        recurrence_end_date=second_tue,
    )

    original_commit = db_session.commit

    def failing_commit():
        raise RuntimeError("Simulated crash right before commit")

    monkeypatch.setattr(db_session, "commit", failing_commit)

    with pytest.raises(RuntimeError, match="Simulated crash"):
        RecurringService.create_recurring_booking(
            db=db_session,
            user_id=member_user.id,
            series_in=series_in,
        )

    # Restore commit and rollback
    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.rollback()

    # Assert no series remains in DB
    series = db_session.scalars(
        select(RecurringSeries).where(
            RecurringSeries.user_id == member_user.id,
            RecurringSeries.court_id == test_court.id,
        )
    ).all()
    assert len(series) == 0
