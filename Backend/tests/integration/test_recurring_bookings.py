import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.court import Court
from app.models.hold import Hold
from app.models.recurring_series import RecurringSeries
from app.models.user import User


def test_create_recurring_series_success(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    today = datetime.now(tz).date()
    # Find next Wednesday (day_of_week = 2)
    days_ahead = (2 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    start_date = today + timedelta(days=days_ahead)
    end_date = start_date + timedelta(weeks=1)  # 2 occurrences

    payload = {
        "court_id": str(test_court.id),
        "day_of_week": 2,
        "start_time": "15:00:00",
        "end_time": "16:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    response = client.post("/recurring-bookings", json=payload, headers=member_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["court_id"] == str(test_court.id)
    assert data["day_of_week"] == 2
    assert len(data["occurrences"]) == 2

    # Verify occurrence dates
    occ_dates = [occ["occurrence_date"] for occ in data["occurrences"]]
    assert occ_dates == [start_date.isoformat(), end_date.isoformat()]

    # Verify database persistence
    series_id = uuid.UUID(data["id"])
    series_db = db_session.get(RecurringSeries, series_id)
    assert series_db is not None
    assert series_db.user_id == member_user.id
    assert series_db.status == "ACTIVE"

    # Verify 2 active holds created
    holds = db_session.scalars(
        select(Hold).where(Hold.user_id == member_user.id, Hold.court_id == test_court.id)
    ).all()
    assert len(holds) >= 2


def test_create_recurring_booking_rejects_exceeding_3_booking_limit(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    today = datetime.now(tz).date()
    days_ahead = (3 - today.weekday()) % 7  # Thursday
    if days_ahead == 0:
        days_ahead = 7
    start_date = today + timedelta(days=days_ahead)
    # Spanning 4 weeks (4 occurrences) exceeds max 3 active future bookings
    end_date = start_date + timedelta(weeks=3)

    payload = {
        "court_id": str(test_court.id),
        "day_of_week": 3,
        "start_time": "17:00:00",
        "end_time": "18:00:00",
        "recurrence_start_date": start_date.isoformat(),
        "recurrence_end_date": end_date.isoformat(),
    }

    response = client.post("/recurring-bookings", json=payload, headers=member_headers)
    assert response.status_code == 409
    assert "limit" in response.json()["detail"].lower() or "maximum" in response.json()["detail"].lower()


def test_create_recurring_booking_validation_errors(
    client: TestClient,
    member_headers: dict[str, str],
    test_court: Court,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    today = datetime.now(tz).date()

    # 1. Invalid weekday
    res_bad_day = client.post(
        "/recurring-bookings",
        json={
            "court_id": str(test_court.id),
            "day_of_week": 7,  # invalid (0-6 allowed)
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "recurrence_start_date": (today + timedelta(days=1)).isoformat(),
            "recurrence_end_date": (today + timedelta(days=15)).isoformat(),
        },
        headers=member_headers,
    )
    assert res_bad_day.status_code in [400, 422]

    # 2. End date before start date
    res_bad_dates = client.post(
        "/recurring-bookings",
        json={
            "court_id": str(test_court.id),
            "day_of_week": 1,
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "recurrence_start_date": (today + timedelta(days=15)).isoformat(),
            "recurrence_end_date": (today + timedelta(days=1)).isoformat(),
        },
        headers=member_headers,
    )
    assert res_bad_dates.status_code in [400, 422]


def test_cancel_individual_recurring_occurrence(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    other_member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    today = datetime.now(tz).date()
    days_ahead = (4 - today.weekday()) % 7  # Friday
    if days_ahead == 0:
        days_ahead = 7
    start_date = today + timedelta(days=days_ahead)
    end_date = start_date + timedelta(weeks=1)

    create_res = client.post(
        "/recurring-bookings",
        json={
            "court_id": str(test_court.id),
            "day_of_week": 4,
            "start_time": "11:00:00",
            "end_time": "12:00:00",
            "recurrence_start_date": start_date.isoformat(),
            "recurrence_end_date": end_date.isoformat(),
        },
        headers=member_headers,
    )
    assert create_res.status_code == 201
    series_data = create_res.json()
    series_id = series_data["id"]
    occ1 = series_data["occurrences"][0]
    occ1_id = occ1["occurrence_id"]

    # Cancel first occurrence
    cancel_res = client.post(
        f"/recurring-bookings/{series_id}/occurrences/{occ1_id}/cancel",
        headers=member_headers,
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # Verify first occurrence's slot is now released for other members
    slot1_start = datetime.combine(start_date, time(11, 0), tzinfo=tz).astimezone(UTC)
    slot1_end = slot1_start + timedelta(hours=1)

    other_hold = client.post(
        "/holds",
        json={
            "court_id": str(test_court.id),
            "start_time": slot1_start.isoformat(),
            "end_time": slot1_end.isoformat(),
        },
        headers=other_member_headers,
    )
    assert other_hold.status_code == 201


def test_cancel_entire_recurring_series(
    client: TestClient,
    member_headers: dict[str, str],
    member_user: User,
    test_court: Court,
    db_session: Session,
) -> None:
    tz = ZoneInfo("Africa/Addis_Ababa")
    today = datetime.now(tz).date()
    days_ahead = (5 - today.weekday()) % 7  # Saturday
    if days_ahead == 0:
        days_ahead = 7
    start_date = today + timedelta(days=days_ahead)
    end_date = start_date + timedelta(weeks=1)

    create_res = client.post(
        "/recurring-bookings",
        json={
            "court_id": str(test_court.id),
            "day_of_week": 5,
            "start_time": "08:00:00",
            "end_time": "09:00:00",
            "recurrence_start_date": start_date.isoformat(),
            "recurrence_end_date": end_date.isoformat(),
        },
        headers=member_headers,
    )
    assert create_res.status_code == 201
    series_id = create_res.json()["id"]

    # Cancel entire series
    cancel_res = client.post(
        f"/recurring-bookings/{series_id}/cancel",
        headers=member_headers,
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # Database verification
    series_db = db_session.get(RecurringSeries, uuid.UUID(series_id))
    assert series_db is not None
    assert series_db.status == "CANCELLED"
