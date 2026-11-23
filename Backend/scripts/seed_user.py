"""Reusable development-only seeding utility for creating privileged accounts (ADMIN, STAFF).

Ensures:
- Safe development-only execution (strictly blocked in production environments).
- Secure password input via getpass without plaintext exposure.
- Password hashing using the application's existing bcrypt implementation.
- Email uniqueness validation before database persistence.
- Never exposed as a public API endpoint.
"""

import argparse
import getpass
import os
import re
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

# Add Backend to sys.path if not present
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.db import SessionLocal
from app.core.security import MAX_PASSWORD_LENGTH, hash_password
from app.models.user import User, UserRole

PROD_ENV_NAMES = {"prod", "production"}
ENV_CHECK_VARIABLES = ("ENVIRONMENT", "APP_ENV", "ENV")
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check_development_environment() -> None:
    """Verify that current environment is not production.

    Raises:
        RuntimeError: If any production environment variable flag is detected.
    """
    for var in ENV_CHECK_VARIABLES:
        val = os.getenv(var, "").strip().lower()
        if val in PROD_ENV_NAMES:
            raise RuntimeError(
                f"Development seeding commands are disabled in production environments ({var}={val})."
            )


def validate_user_input(full_name: str, email: str, password: str) -> tuple[str, str]:
    """Validate full name, email, and password.

    Returns:
        tuple[str, str]: Cleaned (full_name, email).

    Raises:
        ValueError: If any validation rule fails.
    """
    name_clean = full_name.strip()
    if len(name_clean) < 2 or len(name_clean) > 100:
        raise ValueError("Full name must be between 2 and 100 characters long.")

    email_clean = email.strip().lower()
    if not EMAIL_REGEX.match(email_clean) or len(email_clean) > 150:
        raise ValueError(f"Invalid email address: '{email}'.")

    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")

    if len(password.encode("utf-8")) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must not exceed {MAX_PASSWORD_LENGTH} UTF-8 bytes.")

    return name_clean, email_clean


def create_privileged_user(
    db: Session,
    full_name: str,
    email: str,
    password: str,
    role: UserRole | str,
    bypass_env_check: bool = False,
) -> User:
    """Create and persist an administrator or staff user account.

    Args:
        db: Active SQLAlchemy database session.
        full_name: User's full name.
        email: User's email address.
        password: Raw password to hash.
        role: Privileged role (ADMIN or STAFF).
        bypass_env_check: Optional flag for isolated unit tests.

    Returns:
        User: Created User database model instance.

    Raises:
        RuntimeError: If execution is attempted in production.
        ValueError: If validation fails or the email already exists.
    """
    if not bypass_env_check:
        check_development_environment()

    # Determine string representation of role
    role_raw = role.value if hasattr(role, "value") else str(role)
    role_upper = role_raw.upper()
    if role_upper not in {"ADMIN", "STAFF"}:
        raise ValueError(f"Role must be ADMIN or STAFF, got '{role_raw}'.")

    name_clean, email_clean = validate_user_input(full_name, email, password)

    # Check for existing email case-insensitively
    existing = db.execute(
        select(User).where(func.lower(User.email) == email_clean)
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"A user with email '{email_clean}' already exists.")

    password_hash = hash_password(password)

    user = User(
        full_name=name_clean,
        email=email_clean,
        password_hash=password_hash,
        role=role_upper,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def run_seed_cli(
    role: UserRole | str,
    role_display: str,
    argv: list[str] | None = None,
) -> int:
    """CLI execution entrypoint for creating privileged accounts."""
    parser = argparse.ArgumentParser(
        description=f"Development tool to create a {role_display} account."
    )
    parser.add_argument("--name", help="Full name of the user", default=None)
    parser.add_argument("--email", help="Email address of the user", default=None)
    parser.add_argument(
        "--password",
        help="Password for non-interactive scripting (prompted securely if omitted)",
        default=None,
    )

    args = parser.parse_args(argv)

    try:
        check_development_environment()
    except RuntimeError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    name = args.name
    if not name:
        try:
            name = input(f"Enter {role_display} full name: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.", file=sys.stderr)
            return 1

    email = args.email
    if not email:
        try:
            email = input(f"Enter {role_display} email address: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.", file=sys.stderr)
            return 1

    password = args.password
    if not password:
        try:
            password = getpass.getpass(f"Enter {role_display} password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Error: Passwords do not match.", file=sys.stderr)
                return 1
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.", file=sys.stderr)
            return 1

    if SessionLocal is None:
        print("Error: DATABASE_URL is not configured.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        user = create_privileged_user(
            db=db,
            full_name=name,
            email=email,
            password=password,
            role=role,
        )
        print("=" * 60)
        print(f"Successfully created {role_display} account:")
        print(f"  User ID : {user.id}")
        print(f"  Name    : {user.full_name}")
        print(f"  Email   : {user.email}")
        print(f"  Role    : {user.role}")
        print(f"  Active  : {user.is_active}")
        print("=" * 60)
        return 0
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    except SQLAlchemyError as err:
        print(f"Database error: {err}", file=sys.stderr)
        return 1
    finally:
        db.close()
