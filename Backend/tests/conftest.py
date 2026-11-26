import datetime
import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models  # Ensures all models are registered

_ = models.Court
from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.court import Court
from app.models.user import User
from app.models.venue import Venue

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


@pytest.fixture
def other_member_user(db_session: Session) -> User:
    user = User(
        full_name="Other Member Test User",
        email=f"other_member_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("other-member-password-123"),
        role="MEMBER",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def other_member_headers(other_member_user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(other_member_user.id), "role": "MEMBER"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_venue(db_session: Session) -> Venue:
    venue = Venue(
        name=f"Fixture Venue {uuid.uuid4().hex[:8]}",
        address="123 Test Street",
        timezone="Africa/Addis_Ababa",
        opening_time=datetime.time(6, 0),
        closing_time=datetime.time(22, 0),
        is_active=True,
    )
    db_session.add(venue)
    db_session.commit()
    return venue


@pytest.fixture
def test_court(db_session: Session, test_venue: Venue) -> Court:
    from decimal import Decimal

    from app.models.pricing_rules import PricingRule

    court = Court(
        venue_id=test_venue.id,
        name=f"Fixture Court {uuid.uuid4().hex[:8]}",
        sport_type="Tennis",
        is_active=True,
    )
    db_session.add(court)
    db_session.flush()

    pricing_rule = PricingRule(
        court_id=court.id,
        pricing_type="OFF_PEAK",
        day_of_week=None,
        start_time=datetime.time(0, 0),
        end_time=datetime.time(23, 59, 59),
        hourly_rate=Decimal("100.00"),
        currency="ETB",
        effective_from=datetime.date(2025, 1, 1),
        effective_until=datetime.date(2035, 12, 31),
        is_active=True,
    )
    db_session.add(pricing_rule)
    db_session.commit()
    return court


