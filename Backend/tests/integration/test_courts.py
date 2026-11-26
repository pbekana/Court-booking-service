import datetime
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.court import Court
from app.models.venue import Venue


def test_create_court_success(
    client: TestClient,
    admin_headers: dict[str, str],
    test_venue: Venue,
    db_session: Session,
) -> None:
    court_name = f"Center Court {uuid.uuid4().hex[:6]}"
    payload = {
        "venue_id": str(test_venue.id),
        "name": court_name,
        "sport_type": "Tennis",
    }
    response = client.post("/api/v1/courts", json=payload, headers=admin_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == court_name
    assert data["venue_id"] == str(test_venue.id)
    assert data["sport_type"] == "Tennis"
    assert data["is_active"] is True

    # Verify in database
    created_court = db_session.get(Court, uuid.UUID(data["id"]))
    assert created_court is not None
    assert created_court.name == court_name
    assert created_court.venue_id == test_venue.id


def test_create_court_rejects_nonexistent_venue(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    non_existent_venue_id = str(uuid.uuid4())
    payload = {
        "venue_id": non_existent_venue_id,
        "name": "Ghost Court",
        "sport_type": "Squash",
    }
    response = client.post("/api/v1/courts", json=payload, headers=admin_headers)
    assert response.status_code == 404
    assert "Venue not found" in response.json()["detail"]


def test_create_court_rejects_unauthorized(
    client: TestClient,
    member_headers: dict[str, str],
    staff_headers: dict[str, str],
    test_venue: Venue,
) -> None:
    payload = {
        "venue_id": str(test_venue.id),
        "name": "Restricted Court",
        "sport_type": "Basketball",
    }
    # Unauthenticated
    assert client.post("/api/v1/courts", json=payload).status_code == 401
    # Member forbidden
    assert client.post("/api/v1/courts", json=payload, headers=member_headers).status_code == 403
    # Staff forbidden (ADMIN only)
    assert client.post("/api/v1/courts", json=payload, headers=staff_headers).status_code == 403


def test_create_court_rejects_duplicate_name_in_same_venue(
    client: TestClient,
    admin_headers: dict[str, str],
    test_venue: Venue,
) -> None:
    court_name = f"Duplicate Court {uuid.uuid4().hex[:6]}"
    payload = {
        "venue_id": str(test_venue.id),
        "name": court_name,
        "sport_type": "Tennis",
    }
    first_res = client.post("/api/v1/courts", json=payload, headers=admin_headers)
    assert first_res.status_code == 201

    duplicate_res = client.post("/api/v1/courts", json=payload, headers=admin_headers)
    assert duplicate_res.status_code == 409
    assert "already exists" in duplicate_res.json()["detail"]


def test_list_courts_with_filtering_and_roles(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    test_venue: Venue,
    db_session: Session,
) -> None:
    # Create active and inactive courts
    c1 = Court(
        venue_id=test_venue.id,
        name=f"Active Tennis {uuid.uuid4().hex[:4]}",
        sport_type="Tennis",
        is_active=True,
    )
    c2 = Court(
        venue_id=test_venue.id,
        name=f"Inactive Tennis {uuid.uuid4().hex[:4]}",
        sport_type="Tennis",
        is_active=False,
    )
    c3 = Court(
        venue_id=test_venue.id,
        name=f"Active Squash {uuid.uuid4().hex[:4]}",
        sport_type="Squash",
        is_active=True,
    )
    db_session.add_all([c1, c2, c3])
    db_session.commit()

    # Members only see active courts
    member_res = client.get(
        f"/api/v1/courts?venue_id={test_venue.id}",
        headers=member_headers,
    )
    assert member_res.status_code == 200
    member_courts = member_res.json()
    assert all(c["is_active"] is True for c in member_courts)
    member_court_ids = {c["id"] for c in member_courts}
    assert str(c1.id) in member_court_ids
    assert str(c3.id) in member_court_ids
    assert str(c2.id) not in member_court_ids

    # Admin can see inactive courts when active_only=False
    admin_res = client.get(
        f"/api/v1/courts?venue_id={test_venue.id}&active_only=false",
        headers=admin_headers,
    )
    assert admin_res.status_code == 200
    admin_court_ids = {c["id"] for c in admin_res.json()}
    assert str(c2.id) in admin_court_ids

    # Filter by sport_type
    sport_res = client.get(
        f"/api/v1/courts?venue_id={test_venue.id}&sport_type=Squash",
        headers=member_headers,
    )
    assert sport_res.status_code == 200
    assert all(c["sport_type"].lower() == "squash" for c in sport_res.json())


def test_get_court_by_id(
    client: TestClient,
    member_headers: dict[str, str],
    admin_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    # Existing active court
    res = client.get(f"/api/v1/courts/{test_court.id}", headers=member_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(test_court.id)
    assert data["name"] == test_court.name
    assert "venue" in data
    assert data["venue"]["id"] == str(test_court.venue_id)

    # Nonexistent court
    nonexistent_id = uuid.uuid4()
    not_found_res = client.get(f"/api/v1/courts/{nonexistent_id}", headers=member_headers)
    assert not_found_res.status_code == 404

    # Inactive court hidden from members but visible to admin
    test_court.is_active = False
    db_session.commit()

    member_inactive_res = client.get(f"/api/v1/courts/{test_court.id}", headers=member_headers)
    assert member_inactive_res.status_code == 404

    admin_inactive_res = client.get(f"/api/v1/courts/{test_court.id}", headers=admin_headers)
    assert admin_inactive_res.status_code == 200
    assert admin_inactive_res.json()["is_active"] is False


def test_update_court(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    new_name = f"Renamed Court {uuid.uuid4().hex[:6]}"
    payload = {
        "name": new_name,
        "sport_type": "Badminton",
    }

    # Forbidden for member
    assert (
        client.patch(f"/api/v1/courts/{test_court.id}", json=payload, headers=member_headers).status_code
        == 403
    )

    # Success for admin
    update_res = client.patch(
        f"/api/v1/courts/{test_court.id}",
        json=payload,
        headers=admin_headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == new_name
    assert update_res.json()["sport_type"] == "Badminton"

    # Verify database
    db_session.refresh(test_court)
    assert test_court.name == new_name
    assert test_court.sport_type == "Badminton"


def test_update_nonexistent_court_rejected(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    res = client.patch(
        f"/api/v1/courts/{uuid.uuid4()}",
        json={"name": "New Name"},
        headers=admin_headers,
    )
    assert res.status_code == 404


def test_deactivate_court_soft_delete(
    client: TestClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    test_court: Court,
    db_session: Session,
) -> None:
    # Delete / deactivate endpoint
    res = client.delete(f"/api/v1/courts/{test_court.id}", headers=admin_headers)
    assert res.status_code == 204

    db_session.refresh(test_court)
    assert test_court.is_active is False

    # Inactive court cannot be reserved for holds
    now = datetime.datetime.now(datetime.UTC)
    hold_payload = {
        "court_id": str(test_court.id),
        "start_time": (now + datetime.timedelta(days=1)).isoformat(),
        "end_time": (now + datetime.timedelta(days=1, hours=1)).isoformat(),
    }
    hold_res = client.post("/holds", json=hold_payload, headers=member_headers)
    assert hold_res.status_code == 400
    assert "inactive" in hold_res.json()["detail"].lower()
