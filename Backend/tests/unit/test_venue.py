import uuid
from datetime import UTC, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.court import Court
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue


def test_create_venue_successfully(client: TestClient, admin_headers: dict[str, str]):
    response = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Bole Sports Club",
            "address": "Bole Medhanialem, Addis Ababa",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "06:00:00",
            "closing_time": "22:00:00",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Bole Sports Club"
    assert data["address"] == "Bole Medhanialem, Addis Ababa"
    assert data["timezone"] == "Africa/Addis_Ababa"
    assert data["opening_time"] == "06:00:00"
    assert data["closing_time"] == "22:00:00"
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data


def test_reject_invalid_opening_and_closing_times(client: TestClient, admin_headers: dict[str, str]):
    # Closing time before opening time
    response = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Invalid Hours Arena",
            "address": "Downtown",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "22:00:00",
            "closing_time": "06:00:00",
        },
    )
    assert response.status_code == 422

    # Closing time equal to opening time
    response_equal = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Zero Duration Arena",
            "address": "Downtown",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "10:00:00",
            "closing_time": "10:00:00",
        },
    )
    assert response_equal.status_code == 422


def test_reject_invalid_timezone(client: TestClient, admin_headers: dict[str, str]):
    response = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Bad Timezone Arena",
            "address": "Downtown",
            "timezone": "Invalid/Fake_Zone",
            "opening_time": "08:00:00",
            "closing_time": "20:00:00",
        },
    )
    assert response.status_code == 422


def test_reject_empty_venue_name(client: TestClient, admin_headers: dict[str, str]):
    response = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "   ",
            "address": "Downtown",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "08:00:00",
            "closing_time": "20:00:00",
        },
    )
    assert response.status_code == 422


def test_retrieve_all_active_venues(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
):
    # Create active venue
    v1_resp = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Active Venue 1",
            "address": "Location 1",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "07:00:00",
            "closing_time": "21:00:00",
        },
    )
    assert v1_resp.status_code == 201
    v1_id = v1_resp.json()["id"]

    # Create another venue and deactivate it
    v2_resp = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Deactivated Venue 2",
            "address": "Location 2",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "07:00:00",
            "closing_time": "21:00:00",
        },
    )
    v2_id = v2_resp.json()["id"]
    client.delete(f"/api/v1/venues/{v2_id}", headers=admin_headers)

    # Member retrieves venues - must only see active
    member_get = client.get("/api/v1/venues", headers=member_headers)
    assert member_get.status_code == 200
    venues = member_get.json()
    returned_ids = [v["id"] for v in venues]
    assert v1_id in returned_ids
    assert v2_id not in returned_ids


def test_retrieve_venue_by_id(client: TestClient, admin_headers: dict[str, str], member_headers: dict[str, str]):
    create_resp = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Meskel Stadium",
            "address": "Meskel Square",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "06:00:00",
            "closing_time": "23:00:00",
        },
    )
    venue_id = create_resp.json()["id"]

    get_resp = client.get(f"/api/v1/venues/{venue_id}", headers=member_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == venue_id
    assert get_resp.json()["name"] == "Meskel Stadium"


def test_return_404_for_nonexistent_venue(client: TestClient, member_headers: dict[str, str]):
    random_id = uuid.uuid4()
    response = client.get(f"/api/v1/venues/{random_id}", headers=member_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Venue not found"


def test_member_cannot_retrieve_inactive_venue_by_id(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    staff_headers: dict[str, str],
):
    create_resp = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Hidden Arena",
            "address": "Hidden",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "08:00:00",
            "closing_time": "20:00:00",
        },
    )
    venue_id = create_resp.json()["id"]
    client.delete(f"/api/v1/venues/{venue_id}", headers=admin_headers)

    # Member should receive 404
    member_resp = client.get(f"/api/v1/venues/{venue_id}", headers=member_headers)
    assert member_resp.status_code == 404

    # Staff and Admin can still view inactive venue
    staff_resp = client.get(f"/api/v1/venues/{venue_id}", headers=staff_headers)
    assert staff_resp.status_code == 200
    assert staff_resp.json()["is_active"] is False


def test_update_venue(client: TestClient, admin_headers: dict[str, str]):
    create_resp = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Original Name",
            "address": "Original Address",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "08:00:00",
            "closing_time": "18:00:00",
        },
    )
    venue_id = create_resp.json()["id"]

    patch_resp = client.patch(
        f"/api/v1/venues/{venue_id}",
        headers=admin_headers,
        json={
            "name": "Updated Name",
            "address": "Updated Address",
            "closing_time": "21:00:00",
        },
    )
    assert patch_resp.status_code == 200
    updated_data = patch_resp.json()
    assert updated_data["name"] == "Updated Name"
    assert updated_data["address"] == "Updated Address"
    assert updated_data["opening_time"] == "08:00:00"
    assert updated_data["closing_time"] == "21:00:00"


def test_update_venue_rejects_invalid_time(client: TestClient, admin_headers: dict[str, str]):
    create_resp = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Time Test Venue",
            "address": "Address",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "08:00:00",
            "closing_time": "18:00:00",
        },
    )
    venue_id = create_resp.json()["id"]

    # Try setting opening_time to 19:00:00 (which is after existing closing_time 18:00:00)
    patch_resp = client.patch(
        f"/api/v1/venues/{venue_id}",
        headers=admin_headers,
        json={"opening_time": "19:00:00"},
    )
    assert patch_resp.status_code == 400


def test_prevent_unauthorized_venue_operations(
    client: TestClient,
    member_headers: dict[str, str],
    staff_headers: dict[str, str],
    admin_headers: dict[str, str],
):
    venue_payload = {
        "name": "Unauthorized Attempt",
        "address": "Anywhere",
        "timezone": "Africa/Addis_Ababa",
        "opening_time": "07:00:00",
        "closing_time": "22:00:00",
    }

    # Member cannot create
    assert client.post("/api/v1/venues", headers=member_headers, json=venue_payload).status_code == 403

    # Staff cannot create
    assert client.post("/api/v1/venues", headers=staff_headers, json=venue_payload).status_code == 403

    # Unauthenticated cannot create or read
    assert client.post("/api/v1/venues", json=venue_payload).status_code == 401
    assert client.get("/api/v1/venues").status_code == 401

    # Admin creates venue
    created_id = client.post("/api/v1/venues", headers=admin_headers, json=venue_payload).json()["id"]

    # Member cannot update or delete
    assert client.patch(f"/api/v1/venues/{created_id}", headers=member_headers, json={"name": "New"}).status_code == 403
    assert client.delete(f"/api/v1/venues/{created_id}", headers=member_headers).status_code == 403

    # Staff cannot update or delete
    assert client.patch(f"/api/v1/venues/{created_id}", headers=staff_headers, json={"name": "New"}).status_code == 403
    assert client.delete(f"/api/v1/venues/{created_id}", headers=staff_headers).status_code == 403


def test_deactivate_venue_correctly(client: TestClient, admin_headers: dict[str, str], db_session: Session):
    create_resp = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": "Deactivate Me",
            "address": "Address",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "08:00:00",
            "closing_time": "18:00:00",
        },
    )
    venue_id = uuid.UUID(create_resp.json()["id"])

    del_resp = client.delete(f"/api/v1/venues/{venue_id}", headers=admin_headers)
    assert del_resp.status_code == 204

    # Verify soft-deletion in DB
    venue = db_session.get(Venue, venue_id)
    assert venue is not None
    assert venue.is_active is False


def test_prevent_venue_deactivation_with_active_future_reservations(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
    member_user: User,
):
    # 1. Create venue
    venue = Venue(
        name="Venue With Reservation",
        address="123 Road",
        timezone="Africa/Addis_Ababa",
        opening_time=time(7, 0),
        closing_time=time(22, 0),
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    # 2. Create court
    court = Court(
        venue_id=venue.id,
        name="Court A",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    # 3. Create active future reservation
    future_start = datetime.now(UTC) + timedelta(days=2)
    future_end = future_start + timedelta(hours=2)
    reservation = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=future_start,
        end_at=future_end,
        status="CONFIRMED",
    )
    db_session.add(reservation)
    db_session.commit()

    # 4. Attempt to deactivate venue -> should return 409 Conflict
    resp = client.delete(f"/api/v1/venues/{venue.id}", headers=admin_headers)
    assert resp.status_code == 409
    assert "active future reservations" in resp.json()["detail"].lower()

    # 5. Cancel or expire reservation, then deactivation should succeed
    reservation.status = "CANCELLED"
    db_session.commit()

    success_resp = client.delete(f"/api/v1/venues/{venue.id}", headers=admin_headers)
    assert success_resp.status_code == 204
