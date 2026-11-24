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
