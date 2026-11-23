"""Unit tests for user authentication functionality.

Covers:
- Authentication with valid credentials.
- Rejection of incorrect password.
- Rejection of nonexistent email.
- Rejection of inactive user accounts.
- Rejection of missing/invalid credentials.
- Prevention of sensitive data exposure (password hashes, internals).
- Pure mock unit tests of authentication handler.
"""

import uuid
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.router import login_user
from app.core.db import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models.user import User, UserRole
from app.schemas.auth import UserLogin


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Test client using an isolated in-memory SQLite database."""
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


@pytest.fixture
def test_users(auth_client: TestClient) -> dict[str, User]:
    """Seed test users into the SQLite test database."""
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        active_user = User(
            id=uuid.uuid4(),
            full_name="Active Member",
            email="active@example.com",
            password_hash=hash_password("ValidPassword123!"),
            role=UserRole.MEMBER,
            is_active=True,
        )
        inactive_user = User(
            id=uuid.uuid4(),
            full_name="Inactive Member",
            email="inactive@example.com",
            password_hash=hash_password("ValidPassword123!"),
            role=UserRole.MEMBER,
            is_active=False,
        )
        db.add_all([active_user, inactive_user])
        db.commit()
        db.refresh(active_user)
        db.refresh(inactive_user)
        return {"active": active_user, "inactive": inactive_user}
    finally:
        db_gen.close()


class TestUserAuthenticationEndpoint:
    """Tests for POST /api/v1/auth/login endpoint."""

    def test_authenticate_valid_credentials(
        self, auth_client: TestClient, test_users: dict[str, User]
    ) -> None:
        """A user can authenticate with valid credentials and receive token & user info."""
        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "active@example.com", "password": "ValidPassword123!"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert isinstance(data["token"], str)
        assert len(data["token"]) > 0
        assert data["user"]["email"] == "active@example.com"
        assert data["user"]["full_name"] == "Active Member"
        assert data["user"]["role"] == "MEMBER"

    def test_authenticate_incorrect_password_rejected(
        self, auth_client: TestClient, test_users: dict[str, User]
    ) -> None:
        """An incorrect password is rejected with 401 Unauthorized."""
        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "active@example.com", "password": "WrongPassword123!"},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["detail"] == "Invalid email or password"

    def test_authenticate_nonexistent_email_rejected(
        self, auth_client: TestClient, test_users: dict[str, User]
    ) -> None:
        """A nonexistent email is rejected with 401 Unauthorized without leaking user existence."""
        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "nonexistent@example.com", "password": "SomePassword123!"},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["detail"] == "Invalid email or password"

    def test_authenticate_inactive_user_cannot_authenticate(
        self, auth_client: TestClient, test_users: dict[str, User]
    ) -> None:
        """An inactive user account is rejected even with valid credentials."""
        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "inactive@example.com", "password": "ValidPassword123!"},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["detail"] == "User account is inactive"

    @pytest.mark.parametrize(
        ("payload", "expected_field"),
        [
            ({"email": "active@example.com"}, "password"),
            ({"password": "ValidPassword123!"}, "email"),
            ({}, "email"),
            ({"email": "not-a-valid-email", "password": "ValidPassword123!"}, "email"),
        ],
    )
    def test_authenticate_missing_or_invalid_credentials_rejected(
        self, auth_client: TestClient, payload: dict[str, str], expected_field: str
    ) -> None:
        """Missing or malformed credential payloads are rejected with 422 Unprocessable Entity."""
        response = auth_client.post("/api/v1/auth/login", json=payload)

        assert response.status_code == 422
        errors = response.json().get("detail", [])
        field_names = [e.get("loc", [])[-1] for e in errors]
        assert expected_field in field_names

    def test_authentication_failures_do_not_expose_sensitive_information(
        self, auth_client: TestClient, test_users: dict[str, User]
    ) -> None:
        """Authentication failures must never expose password hashes, salts, or internal details."""
        # Test wrong password
        r1 = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "active@example.com", "password": "WrongPassword"},
        )
        # Test nonexistent user
        r2 = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "WrongPassword"},
        )
        # Test inactive user
        r3 = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "inactive@example.com", "password": "ValidPassword123!"},
        )

        for resp in [r1, r2, r3]:
            resp_text = resp.text
            assert "password_hash" not in resp_text
            assert "$2b$" not in resp_text
            assert "$2a$" not in resp_text
            assert "traceback" not in resp_text.lower()
            assert "Traceback" not in resp_text

    def test_successful_authentication_does_not_expose_password_hash(
        self, auth_client: TestClient, test_users: dict[str, User]
    ) -> None:
        """Successful authentication response user object contains only public fields."""
        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "active@example.com", "password": "ValidPassword123!"},
        )
        assert response.status_code == 200
        user_data = response.json()["user"]

        assert "password_hash" not in user_data
        assert "password" not in user_data
        assert set(user_data.keys()) == {"id", "full_name", "email", "role"}


class TestUserAuthenticationIsolatedUnit:
    """Pure unit tests for login_user using a mocked SQLAlchemy Session."""

    def test_login_user_with_mocked_db_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """login_user returns user serialization and JWT token when credentials match."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-authentication")
        mock_user = User(
            id=uuid.uuid4(),
            full_name="Mock Member",
            email="mock@example.com",
            password_hash=hash_password("MockSecret123!"),
            role=UserRole.MEMBER,
            is_active=True,
        )

        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        login_data = UserLogin(email="mock@example.com", password="MockSecret123!")
        result = login_user(user_data=login_data, db=mock_db)

        assert "token" in result
        assert result["user"]["email"] == "mock@example.com"
        assert result["user"]["role"] == "MEMBER"

    def test_login_user_with_mocked_db_nonexistent_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """login_user raises 401 when user is not found in database."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-authentication")
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        login_data = UserLogin(email="missing@example.com", password="AnyPassword123!")
        with pytest.raises(HTTPException) as exc_info:
            login_user(user_data=login_data, db=mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid email or password"

    def test_login_user_with_mocked_db_inactive_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """login_user raises 401 when user.is_active is False."""
        monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-authentication")
        mock_user = User(
            id=uuid.uuid4(),
            full_name="Mock Inactive",
            email="inactive@example.com",
            password_hash=hash_password("MockSecret123!"),
            role=UserRole.MEMBER,
            is_active=False,
        )

        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user

        login_data = UserLogin(email="inactive@example.com", password="MockSecret123!")
        with pytest.raises(HTTPException) as exc_info:
            login_user(user_data=login_data, db=mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "User account is inactive"
