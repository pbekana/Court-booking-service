"""Unit tests for role-based authorization, authentication requirements, and resource ownership.

Covers:
- Role authorization dependencies (require_role, require_roles, get_user_role_str).
- Expected permissions by role:
    * MEMBER: manage own bookings and member endpoints, denied staff/admin endpoints.
    * STAFF: access staff endpoints, denied admin endpoints.
    * ADMIN: access admin endpoints.
    * Unknown / unsupported roles are strictly rejected.
- Authentication requirements on protected endpoints (missing token, invalid token, expired token).
- User resource ownership checks:
    * Booking access: own booking allowed, another member's booking rejected with 403.
    * Booking cancellation: own cancellation allowed, another member's booking cancellation rejected with 403.
    * Hold access and cancellation: own hold allowed, another member's hold rejected with 403.
    * Staff and administrator access permissions.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_user_role_str, require_role, require_roles
from app.core.db import Base, get_db
from app.core.security import ALGORITHM, create_access_token, hash_password
from app.main import app
from app.models.booking import Booking, BookingStatus
from app.models.court import Court
from app.models.hold import Hold, HoldStatus
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.services.booking_service import BookingService
from app.services.hold_service import HoldService

TEST_SECRET = "test-secret-key-for-authentication"


@pytest.fixture(autouse=True)
def setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)


@pytest.fixture
def auth_db() -> Iterator[Session]:
    """In-memory SQLite session with all models created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(auth_db: Session) -> Iterator[TestClient]:
    """TestClient wired to isolated in-memory SQLite session."""

    def override_get_db() -> Iterator[Session]:
        yield auth_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def users(auth_db: Session) -> dict[str, User]:
    """Create test users covering MEMBER, STAFF, ADMIN, and secondary MEMBER."""
    member_1 = User(
        id=uuid.uuid4(),
        full_name="Member One",
        email="member1@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.MEMBER,
        is_active=True,
    )
    member_2 = User(
        id=uuid.uuid4(),
        full_name="Member Two",
        email="member2@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.MEMBER,
        is_active=True,
    )
    staff_user = User(
        id=uuid.uuid4(),
        full_name="Staff User",
        email="staff@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.STAFF,
        is_active=True,
    )
    admin_user = User(
        id=uuid.uuid4(),
        full_name="Admin User",
        email="admin@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    auth_db.add_all([member_1, member_2, staff_user, admin_user])
    auth_db.commit()
    for u in [member_1, member_2, staff_user, admin_user]:
        auth_db.refresh(u)

    return {
        "member_1": member_1,
        "member_2": member_2,
        "staff": staff_user,
        "admin": admin_user,
    }


def make_headers(user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(user.id), "role": get_user_role_str(user)})
    return {"Authorization": f"Bearer {token}"}


class TestRoleNormalization:
    """Tests for get_user_role_str helper."""

    @pytest.mark.parametrize(
        ("role_input", "expected"),
        [
            (UserRole.MEMBER, "MEMBER"),
            (UserRole.User, "MEMBER"),
            ("MEMBER", "MEMBER"),
            ("member", "MEMBER"),
            ("User", "MEMBER"),
            (UserRole.STAFF, "STAFF"),
            (UserRole.Staff, "STAFF"),
            ("STAFF", "STAFF"),
            ("staff", "STAFF"),
            (UserRole.ADMIN, "ADMIN"),
            (UserRole.Admin, "ADMIN"),
            ("ADMIN", "ADMIN"),
            ("admin", "ADMIN"),
        ],
    )
    def test_known_roles_normalization(
        self, role_input: UserRole | str, expected: str
    ) -> None:
        user = User(
            id=uuid.uuid4(),
            full_name="Test User",
            email="test@example.com",
            password_hash="hash",
            role=role_input,
            is_active=True,
        )
        assert get_user_role_str(user) == expected

    @pytest.mark.parametrize(
        "unknown_role",
        ["GUEST", "UNKNOWN", "ANONYMOUS", "CUSTOMER", "BOGUS_ROLE"],
    )
    def test_unknown_roles_not_defaulted_to_member(self, unknown_role: str) -> None:
        """Unsupported roles must retain their unknown representation and never default to MEMBER."""
        user = User(
            id=uuid.uuid4(),
            full_name="Unknown User",
            email="unknown@example.com",
            password_hash="hash",
            role=unknown_role,
            is_active=True,
        )
        role_str = get_user_role_str(user)
        assert role_str != "MEMBER"
        assert role_str != "STAFF"
        assert role_str != "ADMIN"
        assert role_str == unknown_role.upper()


class TestRoleAuthorizationDependencies:
    """Unit tests for require_role and require_roles dependency closures."""

    @pytest.mark.parametrize(
        ("user_role", "required_role", "should_allow"),
        [
            # MEMBER checks
            ("MEMBER", UserRole.MEMBER, True),
            ("STAFF", UserRole.MEMBER, False),
            ("ADMIN", UserRole.MEMBER, False),
            ("GUEST", UserRole.MEMBER, False),
            # STAFF checks
            ("STAFF", UserRole.STAFF, True),
            ("STAFF", UserRole.Staff, True),
            ("MEMBER", UserRole.STAFF, False),
            ("ADMIN", UserRole.STAFF, False),
            ("UNKNOWN", UserRole.STAFF, False),
            # ADMIN checks
            ("ADMIN", UserRole.ADMIN, True),
            ("ADMIN", UserRole.Admin, True),
            ("MEMBER", UserRole.ADMIN, False),
            ("STAFF", UserRole.ADMIN, False),
            ("ANONYMOUS", UserRole.ADMIN, False),
        ],
    )
    def test_require_role_matrix(
        self, user_role: str, required_role: UserRole, should_allow: bool
    ) -> None:
        """Test require_role for different user roles against required roles."""
        user = User(
            id=uuid.uuid4(),
            full_name="Role Test",
            email="role@example.com",
            password_hash="hash",
            role=user_role,
            is_active=True,
        )
        checker = require_role(required_role)

        if should_allow:
            assert checker(current_user=user) == user
        else:
            with pytest.raises(HTTPException) as exc_info:
                checker(current_user=user)
            assert exc_info.value.status_code == 403
            assert (
                exc_info.value.detail
                == "You do not have permission to access this resource"
            )

    @pytest.mark.parametrize(
        ("user_role", "allowed_roles", "should_allow"),
        [
            ("ADMIN", (UserRole.ADMIN, "ADMIN"), True),
            ("STAFF", (UserRole.ADMIN, "ADMIN"), False),
            ("MEMBER", (UserRole.ADMIN, "ADMIN"), False),
            ("GUEST", (UserRole.ADMIN, "ADMIN"), False),
            ("ADMIN", ("STAFF", "ADMIN"), True),
            ("STAFF", ("STAFF", "ADMIN"), True),
            ("MEMBER", ("STAFF", "ADMIN"), False),
            ("UNKNOWN", ("STAFF", "ADMIN"), False),
        ],
    )
    def test_require_roles_matrix(
        self,
        user_role: str,
        allowed_roles: tuple[UserRole | str, ...],
        should_allow: bool,
    ) -> None:
        """Test require_roles allows matching roles and forbids non-matching or unknown roles."""
        user = User(
            id=uuid.uuid4(),
            full_name="Roles Test",
            email="roles@example.com",
            password_hash="hash",
            role=user_role,
            is_active=True,
        )
        checker = require_roles(*allowed_roles)

        if should_allow:
            assert checker(current_user=user) == user
        else:
            with pytest.raises(HTTPException) as exc_info:
                checker(current_user=user)
            assert exc_info.value.status_code == 403
            assert (
                exc_info.value.detail
                == "You do not have permission to access this resource"
            )


class TestAuthenticationRequirementsOnEndpoints:
    """Tests authentication enforcement across protected endpoints."""

    def test_unauthenticated_request_rejected(self, client: TestClient) -> None:
        """Requests without an access token are rejected with 401 Unauthorized."""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["detail"] == "Could not validate credentials"

    def test_invalid_token_request_rejected(self, client: TestClient) -> None:
        """Requests with an invalid token string are rejected with 401 Unauthorized."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-garbage-token"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Could not validate credentials"

    def test_expired_token_request_rejected(
        self, client: TestClient, users: dict[str, User]
    ) -> None:
        """Requests with an expired token are rejected with 401 Unauthorized."""
        past_expire = datetime.now(UTC) - timedelta(minutes=10)
        expired_token = jwt.encode(
            {
                "sub": str(users["member_1"].id),
                "role": "MEMBER",
                "exp": past_expire,
            },
            TEST_SECRET,
            algorithm=ALGORITHM,
        )
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Could not validate credentials"

    def test_member_role_endpoint_access_boundaries(
        self, client: TestClient, users: dict[str, User]
    ) -> None:
        """A MEMBER can access member endpoints, but cannot access staff-only or admin-only endpoints."""
        member_headers = make_headers(users["member_1"])

        # Member accesses member profile -> 200 OK
        resp_me = client.get("/api/v1/auth/me", headers=member_headers)
        assert resp_me.status_code == 200
        assert resp_me.json()["user"]["email"] == "member1@example.com"

        # Member accesses staff profile -> 403 Forbidden
        resp_staff = client.get("/api/v1/auth/staff/me", headers=member_headers)
        assert resp_staff.status_code == 403

        # Member attempts admin action (creating a venue) -> 403 Forbidden
        resp_admin = client.post(
            "/api/v1/venues",
            json={
                "name": "New Venue",
                "address": "123 Street",
                "timezone": "UTC",
                "opening_time": "08:00:00",
                "closing_time": "22:00:00",
            },
            headers=member_headers,
        )
        assert resp_admin.status_code == 403

    def test_staff_role_endpoint_access_boundaries(
        self, client: TestClient, users: dict[str, User]
    ) -> None:
        """STAFF can access staff endpoints and create venues."""
        staff_headers = make_headers(users["staff"])

        # Staff accesses staff profile -> 200 OK
        resp_staff = client.get("/api/v1/auth/staff/me", headers=staff_headers)
        assert resp_staff.status_code == 200
        assert resp_staff.json()["role"] == "STAFF"

        # Staff creates venue -> 201 Created
        resp_venue = client.post(
            "/api/v1/venues",
            json={
                "name": "Staff Venue",
                "address": "123 Street",
                "timezone": "UTC",
                "opening_time": "08:00:00",
                "closing_time": "22:00:00",
            },
            headers=staff_headers,
        )
        assert resp_venue.status_code == 201
        assert resp_venue.json()["name"] == "Staff Venue"

    def test_admin_role_endpoint_access(
        self, client: TestClient, users: dict[str, User]
    ) -> None:
        """ADMIN can access administrator-authorized endpoints."""
        admin_headers = make_headers(users["admin"])

        # Admin accesses admin-authorized venue creation -> 201 Created
        resp = client.post(
            "/api/v1/venues",
            json={
                "name": "Admin Club",
                "address": "456 Avenue",
                "timezone": "UTC",
                "opening_time": "08:00:00",
                "closing_time": "22:00:00",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Admin Club"

    def test_unknown_role_token_rejected_on_protected_endpoints(
        self, client: TestClient, auth_db: Session
    ) -> None:
        """Users with unknown or unsupported roles are rejected from protected endpoints."""
        unknown_user = User(
            id=uuid.uuid4(),
            full_name="Guest User",
            email="guest@example.com",
            password_hash=hash_password("Pass123!"),
            role="GUEST",
            is_active=True,
        )
        auth_db.add(unknown_user)
        auth_db.commit()
        auth_db.refresh(unknown_user)

        headers = make_headers(unknown_user)

        # Staff route rejects guest
        assert client.get("/api/v1/auth/staff/me", headers=headers).status_code == 403

        # Admin route rejects guest
        assert (
            client.post(
                "/api/v1/venues",
                json={
                    "name": "Guest Venue",
                    "address": "123",
                    "timezone": "UTC",
                    "opening_time": "08:00:00",
                    "closing_time": "22:00:00",
                },
                headers=headers,
            ).status_code
            == 403
        )


class TestBookingResourceOwnership:
    """Tests for resource ownership access control on Bookings."""

    def test_booking_access_service_ownership_check(
        self, users: dict[str, User]
    ) -> None:
        """BookingService._check_booking_access allows owner, staff, and admin, rejecting other members."""
        booking = Booking(
            id=uuid.uuid4(),
            user_id=users["member_1"].id,
            court_id=uuid.uuid4(),
            start_at=datetime.now(UTC) + timedelta(days=1),
            end_at=datetime.now(UTC) + timedelta(days=1, hours=1),
            total_price=Decimal("50.00"),
            currency="USD",
            status=BookingStatus.CONFIRMED.value,
        )

        # 1. Owner member access -> allowed
        BookingService._check_booking_access(booking, users["member_1"])

        # 2. Another member access -> 403 Forbidden
        with pytest.raises(HTTPException) as exc_info:
            BookingService._check_booking_access(booking, users["member_2"])
        assert exc_info.value.status_code == 403
        assert (
            exc_info.value.detail == "You do not have permission to access this booking"
        )

        # 3. Staff access -> allowed
        BookingService._check_booking_access(booking, users["staff"])

        # 4. Admin access -> allowed
        BookingService._check_booking_access(booking, users["admin"])

    def test_booking_cancel_authorization_check(self, users: dict[str, User]) -> None:
        """Cancelling another member's booking raises 403 Forbidden."""
        booking_id = uuid.uuid4()
        booking = Booking(
            id=booking_id,
            user_id=users["member_1"].id,
            court_id=uuid.uuid4(),
            start_at=datetime.now(UTC) + timedelta(days=2),
            end_at=datetime.now(UTC) + timedelta(days=2, hours=1),
            total_price=Decimal("50.00"),
            currency="USD",
            status=BookingStatus.CONFIRMED.value,
        )

        mock_db = MagicMock(spec=Session)
        mock_db.execute.return_value.scalar_one_or_none.return_value = booking

        # Member 2 attempts to cancel Member 1's booking -> 403 Forbidden
        with pytest.raises(HTTPException) as exc_info:
            BookingService.cancel_booking(
                db=mock_db,
                booking_id=booking_id,
                current_user=users["member_2"],
            )
        assert exc_info.value.status_code == 403
        assert (
            exc_info.value.detail == "You do not have permission to cancel this booking"
        )

    def test_booking_endpoint_ownership_enforcement(
        self, client: TestClient, auth_db: Session, users: dict[str, User]
    ) -> None:
        """HTTP endpoints /bookings/{id} enforce user ownership against other members."""
        venue = Venue(
            name="Ownership Venue",
            address="Addr",
            timezone="UTC",
            opening_time=time(8, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        auth_db.add(venue)
        auth_db.commit()
        auth_db.refresh(venue)

        court = Court(
            venue_id=venue.id,
            name="Court 1",
            sport_type="TENNIS",
            is_active=True,
        )
        auth_db.add(court)
        auth_db.commit()
        auth_db.refresh(court)

        hold = Hold(
            user_id=users["member_1"].id,
            court_id=court.id,
            start_time=datetime.now(UTC) + timedelta(days=1),
            end_time=datetime.now(UTC) + timedelta(days=1, hours=1),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            status=HoldStatus.CONFIRMED.value,
        )
        auth_db.add(hold)
        auth_db.commit()
        auth_db.refresh(hold)

        booking = Booking(
            user_id=users["member_1"].id,
            court_id=court.id,
            hold_id=hold.id,
            start_at=datetime.now(UTC) + timedelta(days=1),
            end_at=datetime.now(UTC) + timedelta(days=1, hours=1),
            total_price=Decimal("40.00"),
            currency="USD",
            status=BookingStatus.CONFIRMED.value,
        )
        auth_db.add(booking)
        auth_db.commit()
        auth_db.refresh(booking)

        # Member 1 accesses own booking -> 200 OK
        resp_own = client.get(
            f"/api/v1/bookings/{booking.id}",
            headers=make_headers(users["member_1"]),
        )
        assert resp_own.status_code == 200
        assert resp_own.json()["id"] == str(booking.id)

        # Member 2 accesses Member 1's booking -> 403 Forbidden
        resp_other = client.get(
            f"/api/v1/bookings/{booking.id}",
            headers=make_headers(users["member_2"]),
        )
        assert resp_other.status_code == 403

        # Member 2 attempts to cancel Member 1's booking -> 403 Forbidden
        resp_cancel = client.post(
            f"/api/v1/bookings/{booking.id}/cancel",
            headers=make_headers(users["member_2"]),
        )
        assert resp_cancel.status_code == 403

        # Staff accesses Member 1's booking -> 200 OK
        resp_staff = client.get(
            f"/api/v1/bookings/{booking.id}",
            headers=make_headers(users["staff"]),
        )
        assert resp_staff.status_code == 200

        # Admin accesses Member 1's booking -> 200 OK
        resp_admin = client.get(
            f"/api/v1/bookings/{booking.id}",
            headers=make_headers(users["admin"]),
        )
        assert resp_admin.status_code == 200


class TestHoldResourceOwnership:
    """Tests for resource ownership access control on temporary Holds."""

    def test_hold_service_ownership_checks(self, users: dict[str, User]) -> None:
        """HoldService methods verify user_id == current_user.id and reject others with 403."""
        hold = Hold(
            id=uuid.uuid4(),
            user_id=users["member_1"].id,
            court_id=uuid.uuid4(),
            start_time=datetime.now(UTC) + timedelta(hours=2),
            end_time=datetime.now(UTC) + timedelta(hours=3),
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            status=HoldStatus.ACTIVE.value,
        )

        mock_db = MagicMock(spec=Session)
        mock_db.get.return_value = hold

        # 1. get_hold_by_id: owner allowed, other member raises 403
        HoldService.get_hold_by_id(
            db=mock_db, hold_id=hold.id, current_user=users["member_1"]
        )
        with pytest.raises(HTTPException) as exc_info:
            HoldService.get_hold_by_id(
                db=mock_db, hold_id=hold.id, current_user=users["member_2"]
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "You do not have permission to access this hold"

        # 2. confirm_hold: other member raises 403
        mock_db.execute.return_value.scalar_one_or_none.return_value = hold
        with pytest.raises(HTTPException) as exc_info:
            HoldService.confirm_hold(
                db=mock_db, hold_id=hold.id, current_user=users["member_2"]
            )
        assert exc_info.value.status_code == 403
        assert (
            exc_info.value.detail == "You do not have permission to confirm this hold"
        )

        # 3. cancel_hold: other member raises 403
        with pytest.raises(HTTPException) as exc_info:
            HoldService.cancel_hold(
                db=mock_db, hold_id=hold.id, current_user=users["member_2"]
            )
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "You do not have permission to cancel this hold"

    def test_hold_endpoint_ownership_enforcement(
        self, client: TestClient, auth_db: Session, users: dict[str, User]
    ) -> None:
        """HTTP endpoints /holds/{id} enforce hold ownership against non-owner users."""
        venue = Venue(
            name="Hold Venue",
            address="Addr",
            timezone="UTC",
            opening_time=time(8, 0),
            closing_time=time(22, 0),
            is_active=True,
        )
        auth_db.add(venue)
        auth_db.commit()

        court = Court(
            venue_id=venue.id,
            name="Court H",
            sport_type="TENNIS",
            is_active=True,
        )
        auth_db.add(court)
        auth_db.commit()

        hold = Hold(
            user_id=users["member_1"].id,
            court_id=court.id,
            start_time=datetime.now(UTC) + timedelta(hours=1),
            end_time=datetime.now(UTC) + timedelta(hours=2),
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            status=HoldStatus.ACTIVE.value,
        )
        auth_db.add(hold)
        auth_db.commit()
        auth_db.refresh(hold)

        # Member 1 accesses own hold -> 200 OK
        resp_own = client.get(
            f"/api/v1/holds/{hold.id}",
            headers=make_headers(users["member_1"]),
        )
        assert resp_own.status_code == 200
        assert resp_own.json()["id"] == str(hold.id)

        # Member 2 accesses Member 1's hold -> 403 Forbidden
        resp_other = client.get(
            f"/api/v1/holds/{hold.id}",
            headers=make_headers(users["member_2"]),
        )
        assert resp_other.status_code == 403
        assert (
            resp_other.json()["detail"]
            == "You do not have permission to access this hold"
        )

        # Member 2 cancels Member 1's hold -> 403 Forbidden
        resp_cancel = client.delete(
            f"/api/v1/holds/{hold.id}",
            headers=make_headers(users["member_2"]),
        )
        assert resp_cancel.status_code == 403
        assert (
            resp_cancel.json()["detail"]
            == "You do not have permission to cancel this hold"
        )
