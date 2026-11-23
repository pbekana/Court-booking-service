"""Unit tests for development-only seeding mechanisms and public registration constraints.

Verifies:
- Public registration always creates MEMBER accounts.
- Public registration cannot assign ADMIN or STAFF by injecting a role field.
- Development seeding creates the correct role (ADMIN, STAFF).
- Duplicate email addresses are rejected.
- Passwords are properly hashed using bcrypt and plaintext is never stored.
- Development seeding is strictly blocked in production environments.
- CLI scripts execute cleanly with appropriate exit codes.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.core.security import verify_password
from app.main import app
from app.models.user import User, UserRole
from scripts.create_admin import main as create_admin_main
from scripts.create_staff import main as create_staff_main
from scripts.seed_user import (
    check_development_environment,
    create_privileged_user,
)


@pytest.fixture
def auth_db() -> Iterator[Session]:
    """Isolated in-memory SQLite session."""
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
def client(auth_db: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient wired to isolated in-memory SQLite session with test JWT secret."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-development-seeding")

    def override_get_db() -> Iterator[Session]:
        yield auth_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


class TestPublicRegistrationConstraints:
    """Verifies that the public registration endpoint cannot be exploited to escalate privileges."""

    def test_public_registration_always_creates_member_accounts(
        self, client: TestClient, auth_db: Session
    ) -> None:
        """Standard public registration automatically assigns role MEMBER."""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Normal Citizen",
                "email": "citizen@example.com",
                "password": "ValidPassword123!",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["user"]["role"] == "MEMBER"
        assert data["user"]["email"] == "citizen@example.com"

        # Check directly in the database
        db_user = auth_db.execute(
            select(User).where(User.email == "citizen@example.com")
        ).scalar_one()
        assert db_user.role == "MEMBER"
        assert db_user.is_active is True

    @pytest.mark.parametrize(
        "injected_role",
        ["ADMIN", "STAFF", "admin", "staff", "superuser", "root", "MEMBER"],
    )
    def test_public_registration_cannot_inject_role_field(
        self, client: TestClient, auth_db: Session, injected_role: str
    ) -> None:
        """Registration payload with a 'role' field is rejected with 422 Unprocessable Entity."""
        email = f"attacker_{uuid.uuid4().hex[:6]}@example.com"
        response = client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Privilege Escalator",
                "email": email,
                "password": "ValidPassword123!",
                "role": injected_role,
            },
        )
        assert response.status_code == 422
        errors = response.json().get("detail", [])
        assert any(
            "extra_forbidden" in str(e) or "role" in str(e.get("loc", []))
            for e in errors
        )

        # Confirm user was not created
        db_user = auth_db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        assert db_user is None


class TestDevelopmentSeedingMechanisms:
    """Verifies internal development seeding functions for ADMIN and STAFF."""

    def test_development_seeding_creates_admin_role(self, auth_db: Session) -> None:
        """create_privileged_user correctly creates an active user with ADMIN role."""
        admin = create_privileged_user(
            db=auth_db,
            full_name="Chief Administrator",
            email="admin.dev@example.com",
            password="SecureAdminPassword123!",
            role=UserRole.ADMIN,
            bypass_env_check=True,
        )

        assert admin.id is not None
        assert admin.role == "ADMIN"
        assert admin.email == "admin.dev@example.com"
        assert admin.full_name == "Chief Administrator"
        assert admin.is_active is True

        # Verify database record
        persisted = auth_db.execute(
            select(User).where(User.email == "admin.dev@example.com")
        ).scalar_one()
        assert persisted.role == "ADMIN"

    def test_development_seeding_creates_staff_role(self, auth_db: Session) -> None:
        """create_privileged_user correctly creates an active user with STAFF role."""
        staff = create_privileged_user(
            db=auth_db,
            full_name="Operations Staff",
            email="staff.dev@example.com",
            password="SecureStaffPassword123!",
            role=UserRole.STAFF,
            bypass_env_check=True,
        )

        assert staff.id is not None
        assert staff.role == "STAFF"
        assert staff.email == "staff.dev@example.com"
        assert staff.is_active is True

        # Verify database record
        persisted = auth_db.execute(
            select(User).where(User.email == "staff.dev@example.com")
        ).scalar_one()
        assert persisted.role == "STAFF"

    def test_development_seeding_rejects_non_privileged_roles(
        self, auth_db: Session
    ) -> None:
        """create_privileged_user rejects MEMBER or unknown roles."""
        with pytest.raises(ValueError, match="Role must be ADMIN or STAFF"):
            create_privileged_user(
                db=auth_db,
                full_name="Invalid Role",
                email="invalid.role@example.com",
                password="SecurePassword123!",
                role=UserRole.MEMBER,
                bypass_env_check=True,
            )

        with pytest.raises(ValueError, match="Role must be ADMIN or STAFF"):
            create_privileged_user(
                db=auth_db,
                full_name="Unknown Role",
                email="unknown.role@example.com",
                password="SecurePassword123!",
                role="GUEST",
                bypass_env_check=True,
            )

    def test_development_seeding_rejects_duplicate_email(
        self, auth_db: Session
    ) -> None:
        """Duplicate email addresses are rejected when seeding privileged accounts."""
        create_privileged_user(
            db=auth_db,
            full_name="First Admin",
            email="duplicate@example.com",
            password="AdminPassword123!",
            role=UserRole.ADMIN,
            bypass_env_check=True,
        )

        with pytest.raises(
            ValueError, match="A user with email 'duplicate@example.com' already exists"
        ):
            create_privileged_user(
                db=auth_db,
                full_name="Second Admin",
                email="duplicate@example.com",
                password="AnotherPassword123!",
                role=UserRole.ADMIN,
                bypass_env_check=True,
            )

    def test_development_seeding_rejects_duplicate_email_case_insensitively(
        self, auth_db: Session
    ) -> None:
        """Duplicate check is case-insensitive."""
        create_privileged_user(
            db=auth_db,
            full_name="Original Admin",
            email="case_test@example.com",
            password="AdminPassword123!",
            role=UserRole.ADMIN,
            bypass_env_check=True,
        )

        with pytest.raises(
            ValueError, match="A user with email 'case_test@example.com' already exists"
        ):
            create_privileged_user(
                db=auth_db,
                full_name="Uppercase Attempt",
                email="CASE_TEST@EXAMPLE.COM",
                password="AnotherPassword123!",
                role=UserRole.ADMIN,
                bypass_env_check=True,
            )

    def test_development_seeding_password_is_properly_hashed(
        self, auth_db: Session
    ) -> None:
        """Passwords are encrypted with bcrypt; plaintext is never stored."""
        raw_password = "PlaintextSecretPassword123!"
        admin = create_privileged_user(
            db=auth_db,
            full_name="Hashed Admin",
            email="hashed.admin@example.com",
            password=raw_password,
            role=UserRole.ADMIN,
            bypass_env_check=True,
        )

        # Plaintext password is not stored
        assert admin.password_hash != raw_password
        assert admin.password_hash.startswith(("$2b$", "$2a$", "$2y$"))

        # Verify password using security utility
        assert verify_password(raw_password, admin.password_hash) is True
        assert verify_password("WrongPassword123!", admin.password_hash) is False

    @pytest.mark.parametrize(
        ("name", "email", "password", "expected_err"),
        [
            (
                "A",
                "valid@example.com",
                "Password123!",
                "Full name must be between 2 and 100",
            ),
            (
                "Valid Name",
                "invalid-email-format",
                "Password123!",
                "Invalid email address",
            ),
            ("Valid Name", "valid@example.com", "short", "Password must be at least 8"),
            (
                "Valid Name",
                "valid@example.com",
                "p" * 73,
                "Password must not exceed 72",
            ),
        ],
    )
    def test_development_seeding_validation_rules(
        self, auth_db: Session, name: str, email: str, password: str, expected_err: str
    ) -> None:
        """Inputs failing validation are rejected with descriptive ValueError messages."""
        with pytest.raises(ValueError, match=expected_err):
            create_privileged_user(
                db=auth_db,
                full_name=name,
                email=email,
                password=password,
                role=UserRole.ADMIN,
                bypass_env_check=True,
            )


class TestEnvironmentSafetyControls:
    """Verifies that development seeding commands are strictly prohibited in production environments."""

    @pytest.mark.parametrize(
        ("env_var", "env_val"),
        [
            ("ENVIRONMENT", "production"),
            ("ENVIRONMENT", "prod"),
            ("ENVIRONMENT", "PRODUCTION"),
            ("APP_ENV", "production"),
            ("APP_ENV", "prod"),
            ("ENV", "production"),
            ("ENV", "prod"),
        ],
    )
    def test_development_seeding_blocked_in_production(
        self, monkeypatch: pytest.MonkeyPatch, env_var: str, env_val: str
    ) -> None:
        """check_development_environment raises RuntimeError when production environment flags exist."""
        monkeypatch.setenv(env_var, env_val)

        with pytest.raises(
            RuntimeError,
            match="Development seeding commands are disabled in production environments",
        ):
            check_development_environment()

    def test_create_privileged_user_enforces_production_guard(
        self, auth_db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_privileged_user aborts when ENVIRONMENT=production."""
        monkeypatch.setenv("ENVIRONMENT", "production")

        with pytest.raises(
            RuntimeError,
            match="Development seeding commands are disabled in production environments",
        ):
            create_privileged_user(
                db=auth_db,
                full_name="Prod Admin",
                email="prod.admin@example.com",
                password="SecurePassword123!",
                role=UserRole.ADMIN,
                bypass_env_check=False,
            )


class TestCliScripts:
    """Verifies the CLI entrypoints for create_admin and create_staff."""

    def test_create_admin_cli_success(
        self, auth_db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_admin_main completes successfully with code 0."""
        monkeypatch.setattr("scripts.seed_user.SessionLocal", lambda: auth_db)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)

        exit_code = create_admin_main(
            [
                "--name",
                "CLI Admin",
                "--email",
                "cli.admin@example.com",
                "--password",
                "AdminPassword123!",
            ]
        )
        assert exit_code == 0

        # Verify user in database
        user = auth_db.execute(
            select(User).where(User.email == "cli.admin@example.com")
        ).scalar_one()
        assert user.role == "ADMIN"
        assert verify_password("AdminPassword123!", user.password_hash) is True

    def test_create_staff_cli_success(
        self, auth_db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_staff_main completes successfully with code 0."""
        monkeypatch.setattr("scripts.seed_user.SessionLocal", lambda: auth_db)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)

        exit_code = create_staff_main(
            [
                "--name",
                "CLI Staff",
                "--email",
                "cli.staff@example.com",
                "--password",
                "StaffPassword123!",
            ]
        )
        assert exit_code == 0

        # Verify user in database
        user = auth_db.execute(
            select(User).where(User.email == "cli.staff@example.com")
        ).scalar_one()
        assert user.role == "STAFF"
        assert verify_password("StaffPassword123!", user.password_hash) is True

    def test_cli_duplicate_email_returns_error_code(
        self, auth_db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Running CLI with existing email exits with code 1."""
        monkeypatch.setattr("scripts.seed_user.SessionLocal", lambda: auth_db)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)

        # First run succeeds
        code1 = create_admin_main(
            [
                "--name",
                "First",
                "--email",
                "dup.cli@example.com",
                "--password",
                "Password123!",
            ]
        )
        assert code1 == 0

        # Second run with same email returns code 1
        code2 = create_admin_main(
            [
                "--name",
                "Second",
                "--email",
                "dup.cli@example.com",
                "--password",
                "Password123!",
            ]
        )
        assert code2 == 1

    def test_cli_blocked_in_production_returns_error_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Running CLI in production exits with code 1."""
        monkeypatch.setenv("ENVIRONMENT", "production")

        exit_code = create_admin_main(
            [
                "--name",
                "Prod Try",
                "--email",
                "prodfail@example.com",
                "--password",
                "Password123!",
            ]
        )
        assert exit_code == 1
