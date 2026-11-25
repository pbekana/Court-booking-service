from typing import Any

from fastapi.testclient import TestClient


def test_venue_creation_requires_staff_or_admin(
    client: TestClient,
    admin_headers: dict[str, str],
    staff_headers: dict[str, str],
    member_headers: dict[str, str],
) -> None:
    payload = {
        "name": "Authorized Venue",
        "address": "123 Test Street",
        "timezone": "UTC",
        "opening_time": "08:00:00",
        "closing_time": "22:00:00",
    }

    assert client.post("/api/v1/venues", json=payload).status_code == 401
    assert (
        client.post(
            "/api/v1/venues",
            json=payload,
            headers=member_headers,
        ).status_code
        == 403
    )

    for role, headers in (
        ("Staff", staff_headers),
        ("Admin", admin_headers),
    ):
        response = client.post(
            "/api/v1/venues",
            json={**payload, "name": f"{role} Venue"},
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["name"] == f"{role} Venue"


def get_venue_id(
    client: TestClient, headers: dict[str, str], venue_id: str
) -> str:
    response = client.get(f"/api/v1/venues/{venue_id}", headers=headers)
    assert response.status_code == 200
    venue = response.json()
    assert venue["id"] == venue_id
    return venue["id"]


def get_all_venues(
    client: TestClient, headers: dict[str, str]
) -> list[dict[str, Any]]:
    response = client.get("/api/v1/venues", headers=headers)
    assert response.status_code == 200
    return response.json()


def update_venue(
    client: TestClient, headers: dict[str, str], venue_id: str
) -> None:
    payload = {
        "name": "Updated Venue",
        "address": "456 Updated Street",
        "timezone": "UTC",
        "opening_time": "09:00:00",
        "closing_time": "21:00:00",
        "is_active": True,
    }
    response = client.patch(
        f"/api/v1/venues/{venue_id}",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Venue"


def delete_venue(
    client: TestClient, headers: dict[str, str], venue_id: str
) -> None:
    response = client.delete(
        f"/api/v1/venues/{venue_id}",
        headers=headers,
    )
    assert response.status_code == 204


def test_venue_read_update_and_deactivate(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    payload = {
        "name": "Integration Test Venue",
        "address": "123 Test Street",
        "timezone": "UTC",
        "opening_time": "08:00:00",
        "closing_time": "22:00:00",
    }
    create_response = client.post(
        "/api/v1/venues",
        json=payload,
        headers=admin_headers,
    )
    assert create_response.status_code == 201
    venue_id = create_response.json()["id"]

    assert get_venue_id(client, admin_headers, venue_id) == venue_id
    assert any(
        venue["id"] == venue_id for venue in get_all_venues(client, admin_headers)
    )

    update_venue(client, admin_headers, venue_id)
    updated_venue = client.get(
        f"/api/v1/venues/{venue_id}",
        headers=admin_headers,
    )
    assert updated_venue.status_code == 200
    assert updated_venue.json()["address"] == "456 Updated Street"

    delete_venue(client, admin_headers, venue_id)
    assert all(
        venue["id"] != venue_id for venue in get_all_venues(client, admin_headers)
    )
    deactivated_venue = client.get(
        f"/api/v1/venues/{venue_id}",
        headers=admin_headers,
    )
    assert deactivated_venue.status_code == 200
    assert deactivated_venue.json()["is_active"] is False
