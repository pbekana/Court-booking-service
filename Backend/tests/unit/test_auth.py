from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base,get_db
from app.core.security import hash_password
from app.main import app
from app.models.user import User, UserRole


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-authentication")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Iterator[Session]:
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def register(client: TestClient, email: str = "member@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test Member",
            "email": email,
            "password": "secure-password-123",
        },
    )


def test_registration_creates_member_and_returns_token(client: TestClient) -> None:
    response = register(client)

    assert response.status_code == 201
    payload = response.json()
    assert payload["user"]["role"] == "MEMBER"
    assert payload["token"]


def test_registration_does_not_allow_client_to_choose_role(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test Staff",
            "email": "staff@example.com",
            "password": "secure-password-123",
            "role": "staff",
        },
    )

    assert response.status_code == 422


def test_duplicate_registration_and_invalid_login_are_rejected(
    client: TestClient,
) -> None:
    assert register(client).status_code == 201
    assert register(client).status_code == 400

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_authenticated_routes_require_a_valid_token(client: TestClient) -> None:
    register_response = register(client)
    token = register_response.json()["token"]

    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        ).status_code
        == 401
    )

    profile_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["user"]["email"] == "member@example.com"


def test_staff_route_rejects_members_and_allows_staff(client: TestClient) -> None:
    member_token = register(client).json()["token"]
    member_response = client.get(
        "/api/v1/auth/staff/me",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert member_response.status_code == 403

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        staff = User(
            full_name="Test Staff",
            email="staff@example.com",
            password_hash=hash_password("secure-password-123"),
            role=UserRole.Staff,
        )
        db.add(staff)
        db.commit()
    finally:
        db_generator.close()

    staff_login = client.post(
        "/api/v1/auth/login",
        json={"email": "staff@example.com", "password": "secure-password-123"},
    )
    assert staff_login.status_code == 200
    staff_token = staff_login.json()["token"]

    staff_response = client.get(
        "/api/v1/auth/staff/me",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert staff_response.status_code == 200
    assert staff_response.json()["role"] == "STAFF"
