import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # Ensures all models are registered
from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import User

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:123456@localhost:5432/court_booking_service_test_db",
)

engine = create_engine(TEST_DATABASE_URL)


@pytest.fixture
def db_session() -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-authentication")

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db_session: Session) -> User:
    user = User(
        full_name="Admin Test User",
        email=f"admin_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("admin-password-123"),
        role="ADMIN",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def staff_user(db_session: Session) -> User:
    user = User(
        full_name="Staff Test User",
        email=f"staff_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("staff-password-123"),
        role="STAFF",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def member_user(db_session: Session) -> User:
    user = User(
        full_name="Member Test User",
        email=f"member_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("member-password-123"),
        role="MEMBER",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(admin_user.id), "role": "ADMIN"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def staff_headers(staff_user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(staff_user.id), "role": "STAFF"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def member_headers(member_user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(member_user.id), "role": "MEMBER"})
    return {"Authorization": f"Bearer {token}"}
