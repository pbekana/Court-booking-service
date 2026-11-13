import uuid
from datetime import UTC, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.court import Court
from app.models.reservations import Reservation
from app.models.user import User
from app.models.venue import Venue


def create_test_venue(client: TestClient, admin_headers: dict[str, str], name: str = "Test Venue") -> str:
    resp = client.post(
        "/api/v1/venues",
        headers=admin_headers,
        json={
            "name": name,
            "address": "123 Test St",
            "timezone": "Africa/Addis_Ababa",
            "opening_time": "06:00:00",
            "closing_time": "22:00:00",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_create_court_successfully(client: TestClient, admin_headers: dict[str, str]):
    venue_id = create_test_venue(client, admin_headers, "Court Creation Venue")

    response = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={
            "venue_id": venue_id,
            "name": "Center Court",
            "sport_type": "Tennis",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Center Court"
    assert data["sport_type"] == "Tennis"
    assert data["venue_id"] == venue_id
    assert data["is_active"] is True
    assert "id" in data


def test_reject_nonexistent_venue(client: TestClient, admin_headers: dict[str, str]):
    random_venue_id = str(uuid.uuid4())
    response = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={
            "venue_id": random_venue_id,
            "name": "Ghost Court",
            "sport_type": "Tennis",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Venue not found"


def test_reject_inactive_venue(client: TestClient, admin_headers: dict[str, str]):
    venue_id = create_test_venue(client, admin_headers, "Inactive Target Venue")
    client.delete(f"/api/v1/venues/{venue_id}", headers=admin_headers)

    response = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={
            "venue_id": venue_id,
            "name": "Court in Inactive Venue",
            "sport_type": "Squash",
        },
    )
    assert response.status_code == 400
    assert "inactive venue" in response.json()["detail"].lower()


def test_reject_duplicate_court_names_within_same_venue(client: TestClient, admin_headers: dict[str, str]):
    venue_1_id = create_test_venue(client, admin_headers, "Duplicate Test Venue 1")
    venue_2_id = create_test_venue(client, admin_headers, "Duplicate Test Venue 2")

    # Create first court in Venue 1
    resp1 = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={
            "venue_id": venue_1_id,
            "name": "Court 1",
            "sport_type": "Tennis",
        },
    )
    assert resp1.status_code == 201

    # Attempt to create duplicate court with same name in Venue 1
    resp_dup = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={
            "venue_id": venue_1_id,
            "name": "Court 1",
            "sport_type": "Tennis",
        },
    )
    assert resp_dup.status_code == 409
    assert "already exists" in resp_dup.json()["detail"].lower()

    # Case-insensitive duplicate check
    resp_dup_case = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={
            "venue_id": venue_1_id,
            "name": "court 1",
            "sport_type": "Basketball",
        },
    )
    assert resp_dup_case.status_code == 409

    # Same court name in Venue 2 must succeed
    resp_v2 = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={
            "venue_id": venue_2_id,
            "name": "Court 1",
            "sport_type": "Tennis",
        },
    )
    assert resp_v2.status_code == 201


def test_retrieve_courts_and_filters(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
):
    venue_a_id = create_test_venue(client, admin_headers, "Filter Venue A")
    venue_b_id = create_test_venue(client, admin_headers, "Filter Venue B")

    # Court A1 - Tennis in Venue A
    c_a1 = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={"venue_id": venue_a_id, "name": "A1 Tennis", "sport_type": "Tennis"},
    ).json()

    # Court A2 - Basketball in Venue A
    c_a2 = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={"venue_id": venue_a_id, "name": "A2 Basketball", "sport_type": "Basketball"},
    ).json()

    # Court B1 - Tennis in Venue B
    c_b1 = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={"venue_id": venue_b_id, "name": "B1 Tennis", "sport_type": "Tennis"},
    ).json()

    # Filter by venue_id
    filter_venue = client.get(
        f"/api/v1/courts?venue_id={venue_a_id}",
        headers=member_headers,
    )
    assert filter_venue.status_code == 200
    ids_by_venue = [c["id"] for c in filter_venue.json()]
    assert c_a1["id"] in ids_by_venue
    assert c_a2["id"] in ids_by_venue
    assert c_b1["id"] not in ids_by_venue

    # Filter by sport_type (case-insensitive)
    filter_sport = client.get(
        "/api/v1/courts?sport_type=tennis",
        headers=member_headers,
    )
    assert filter_sport.status_code == 200
    ids_by_sport = [c["id"] for c in filter_sport.json()]
    assert c_a1["id"] in ids_by_sport
    assert c_b1["id"] in ids_by_sport
    assert c_a2["id"] not in ids_by_sport


def test_retrieve_court_by_id_includes_venue(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
):
    venue_id = create_test_venue(client, admin_headers, "Venue With Details")
    create_court_resp = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={"venue_id": venue_id, "name": "Detailed Court", "sport_type": "Badminton"},
    )
    court_id = create_court_resp.json()["id"]

    get_resp = client.get(f"/api/v1/courts/{court_id}", headers=member_headers)
    assert get_resp.status_code == 200
    court_data = get_resp.json()
    assert court_data["id"] == court_id
    assert court_data["name"] == "Detailed Court"
    assert court_data["sport_type"] == "Badminton"
    assert "venue" in court_data
    assert court_data["venue"]["id"] == venue_id
    assert court_data["venue"]["name"] == "Venue With Details"


def test_return_404_for_nonexistent_court(client: TestClient, member_headers: dict[str, str]):
    random_id = uuid.uuid4()
    resp = client.get(f"/api/v1/courts/{random_id}", headers=member_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Court not found"


def test_member_cannot_retrieve_inactive_court_by_id(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    staff_headers: dict[str, str],
):
    venue_id = create_test_venue(client, admin_headers, "Inactive Court Venue")
    court_id = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={"venue_id": venue_id, "name": "Deactivated Court", "sport_type": "Tennis"},
    ).json()["id"]

    client.delete(f"/api/v1/courts/{court_id}", headers=admin_headers)

    # Member receives 404
    assert client.get(f"/api/v1/courts/{court_id}", headers=member_headers).status_code == 404

    # Staff and Admin can view
    staff_resp = client.get(f"/api/v1/courts/{court_id}", headers=staff_headers)
    assert staff_resp.status_code == 200
    assert staff_resp.json()["is_active"] is False


def test_update_court(client: TestClient, admin_headers: dict[str, str]):
    venue_1_id = create_test_venue(client, admin_headers, "Court Update V1")
    venue_2_id = create_test_venue(client, admin_headers, "Court Update V2")

    court_id = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={"venue_id": venue_1_id, "name": "Original Court", "sport_type": "Tennis"},
    ).json()["id"]

    # Update name and sport_type
    patch_resp = client.patch(
        f"/api/v1/courts/{court_id}",
        headers=admin_headers,
        json={"name": "Renamed Court", "sport_type": "Padel"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Renamed Court"
    assert patch_resp.json()["sport_type"] == "Padel"

    # Move to venue 2
    move_resp = client.patch(
        f"/api/v1/courts/{court_id}",
        headers=admin_headers,
        json={"venue_id": venue_2_id},
    )
    assert move_resp.status_code == 200
    assert move_resp.json()["venue_id"] == venue_2_id


def test_update_court_rejects_moving_to_inactive_or_nonexistent_venue(
    client: TestClient,
    admin_headers: dict[str, str],
):
    venue_1_id = create_test_venue(client, admin_headers, "Valid Venue")
    court_id = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={"venue_id": venue_1_id, "name": "Movable Court", "sport_type": "Tennis"},
    ).json()["id"]

    # Move to nonexistent venue
    resp_nonexistent = client.patch(
        f"/api/v1/courts/{court_id}",
        headers=admin_headers,
        json={"venue_id": str(uuid.uuid4())},
    )
    assert resp_nonexistent.status_code == 404

    # Move to inactive venue
    inactive_venue_id = create_test_venue(client, admin_headers, "Deactivated Venue")
    client.delete(f"/api/v1/venues/{inactive_venue_id}", headers=admin_headers)

    resp_inactive = client.patch(
        f"/api/v1/courts/{court_id}",
        headers=admin_headers,
        json={"venue_id": inactive_venue_id},
    )
    assert resp_inactive.status_code == 400


def test_update_court_rejects_duplicate_name_conflict(client: TestClient, admin_headers: dict[str, str]):
    venue_id = create_test_venue(client, admin_headers, "Conflict Venue")

    client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={"venue_id": venue_id, "name": "Court Alpha", "sport_type": "Tennis"},
    )
    c_beta_id = client.post(
        "/api/v1/courts",
        headers=admin_headers,
        json={"venue_id": venue_id, "name": "Court Beta", "sport_type": "Tennis"},
    ).json()["id"]

    # Try renaming Court Beta to Court Alpha -> 409
    resp = client.patch(
        f"/api/v1/courts/{c_beta_id}",
        headers=admin_headers,
        json={"name": "Court Alpha"},
    )
    assert resp.status_code == 409


def test_prevent_unauthorized_court_operations(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    staff_headers: dict[str, str],
):
    venue_id = create_test_venue(client, admin_headers, "Auth Test Venue")
    court_payload = {
        "venue_id": venue_id,
        "name": "Unauthorized Court",
        "sport_type": "Tennis",
    }

    # Member cannot create
    assert client.post("/api/v1/courts", headers=member_headers, json=court_payload).status_code == 403

    # Staff cannot create
    assert client.post("/api/v1/courts", headers=staff_headers, json=court_payload).status_code == 403

    # Unauthenticated cannot create or list
    assert client.post("/api/v1/courts", json=court_payload).status_code == 401
    assert client.get("/api/v1/courts").status_code == 401

    # Admin creates court
    court_id = client.post("/api/v1/courts", headers=admin_headers, json=court_payload).json()["id"]

    # Member cannot update or delete
    assert client.patch(f"/api/v1/courts/{court_id}", headers=member_headers, json={"name": "X"}).status_code == 403
    assert client.delete(f"/api/v1/courts/{court_id}", headers=member_headers).status_code == 403

    # Staff cannot update or delete
    assert client.patch(f"/api/v1/courts/{court_id}", headers=staff_headers, json={"name": "X"}).status_code == 403
    assert client.delete(f"/api/v1/courts/{court_id}", headers=staff_headers).status_code == 403


def test_deactivate_court_correctly(client: TestClient, admin_headers: dict[str, str], db_session: Session):
    venue_id = create_test_venue(client, admin_headers, "Deactivation Venue")
    court_id = uuid.UUID(
        client.post(
            "/api/v1/courts",
            headers=admin_headers,
            json={"venue_id": venue_id, "name": "To Deactivate", "sport_type": "Tennis"},
        ).json()["id"]
    )

    del_resp = client.delete(f"/api/v1/courts/{court_id}", headers=admin_headers)
    assert del_resp.status_code == 204

    court = db_session.get(Court, court_id)
    assert court is not None
    assert court.is_active is False


def test_prevent_court_deactivation_with_active_future_reservations(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
    member_user: User,
):
    venue = Venue(
        name="Venue For Court Res",
        timezone="Africa/Addis_Ababa",
        opening_time=time(7, 0),
        closing_time=time(22, 0),
        is_active=True,
    )
    db_session.add(venue)
    db_session.flush()

    court = Court(
        venue_id=venue.id,
        name="Court With Res",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    future_start = datetime.now(UTC) + timedelta(days=1)
    future_end = future_start + timedelta(hours=1)
    reservation = Reservation(
        user_id=member_user.id,
        court_id=court.id,
        start_at=future_start,
        end_at=future_end,
        status="CONFIRMED",
    )
    db_session.add(reservation)
    db_session.commit()

    # Attempt to deactivate -> 409
    resp = client.delete(f"/api/v1/courts/{court.id}", headers=admin_headers)
    assert resp.status_code == 409
    assert "active future reservations" in resp.json()["detail"].lower()

    # Cancel reservation
    reservation.status = "CANCELLED"
    db_session.commit()

    success_resp = client.delete(f"/api/v1/courts/{court.id}", headers=admin_headers)
    assert success_resp.status_code == 204
