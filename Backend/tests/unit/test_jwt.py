"""Unit tests for JWT token generation, claims, and validation.

Covers:
- Valid access token generation.
- Correct user identity ("sub" claim).
- Expected expiration claim ("exp" ~ 60 mins).
- Application claims preservation ("role").
- Rejection of expired tokens.
- Rejection of invalid tokens.
- Rejection of tokens signed with incorrect secret.
- Rejection of tokens with malformed payloads.
- Missing JWT_SECRET environment handling.
- Rejection of inactive or nonexistent users with otherwise valid tokens.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    _get_secret_key,
    create_access_token,
)
from app.models.user import User, UserRole

TEST_SECRET = "test-secret-key-for-authentication"


@pytest.fixture(autouse=True)
def setup_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)


class TestJwtGenerationAndClaims:
    """Tests for token generation, claims format, and claims inspection."""

    def test_create_valid_access_token_format(self) -> None:
        """create_access_token generates a well-formed 3-part JWT."""
        user_id = str(uuid.uuid4())
        token = create_access_token({"sub": user_id, "role": "MEMBER"})

        assert isinstance(token, str)
        parts = token.split(".")
        assert len(parts) == 3

    def test_token_contains_correct_identity(self) -> None:
        """The token's 'sub' claim correctly reflects the user identity."""
        user_id = str(uuid.uuid4())
        token = create_access_token({"sub": user_id, "role": "MEMBER"})

        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        assert payload.get("sub") == user_id

    def test_token_contains_expected_expiration_claim(self) -> None:
        """The token contains an 'exp' claim ~60 minutes into the future."""
        before_creation = datetime.now(UTC)
        token = create_access_token({"sub": "user-123", "role": "MEMBER"})
        after_creation = datetime.now(UTC)

        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        assert "exp" in payload
        exp_timestamp = payload["exp"]

        expected_exp_seconds = ACCESS_TOKEN_EXPIRE_MINUTES * 60
        min_expected = int(before_creation.timestamp()) + expected_exp_seconds
        max_expected = int(after_creation.timestamp()) + expected_exp_seconds + 2

        assert min_expected <= exp_timestamp <= max_expected

    def test_token_contains_expected_application_claims(self) -> None:
        """Application-specific claims such as 'role' are preserved in the token payload."""
        token = create_access_token(
            {"sub": "admin-123", "role": "ADMIN", "custom_key": "custom_val"}
        )

        payload = jwt.decode(token, TEST_SECRET, algorithms=[ALGORITHM])
        assert payload.get("role") == "ADMIN"
        assert payload.get("custom_key") == "custom_val"


class TestJwtValidationAndRejection:
    """Tests for token rejection upon expiration, corruption, invalid signature, and malformed payload."""

    def test_expired_token_rejected_by_decode(self) -> None:
        """jwt.decode raises ExpiredSignatureError when token timestamp is in the past."""
        past_expire = datetime.now(UTC) - timedelta(minutes=15)
        expired_token = jwt.encode(
            {"sub": "user-123", "role": "MEMBER", "exp": past_expire},
            TEST_SECRET,
            algorithm=ALGORITHM,
        )

        with pytest.raises(ExpiredSignatureError):
            jwt.decode(expired_token, TEST_SECRET, algorithms=[ALGORITHM])

    def test_expired_token_rejected_in_get_current_user(self) -> None:
        """get_current_user dependency rejects expired token with 401 Unauthorized."""
        past_expire = datetime.now(UTC) - timedelta(minutes=5)
        expired_token = jwt.encode(
            {"sub": "user-123", "role": "MEMBER", "exp": past_expire},
            TEST_SECRET,
            algorithm=ALGORITHM,
        )

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token)
        mock_db = MagicMock(spec=Session)

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=creds, db=mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Could not validate credentials"

    @pytest.mark.parametrize(
        "invalid_token",
        [
            "invalid-token-string",
            "header.payload",
            "header.payload.signature.extra",
            "not.base64.encoded!",
            "",
        ],
    )
    def test_invalid_tokens_rejected_in_get_current_user(
        self, invalid_token: str
    ) -> None:
        """get_current_user dependency rejects invalid token formats with 401 Unauthorized."""
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=invalid_token)
        mock_db = MagicMock(spec=Session)

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=creds, db=mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Could not validate credentials"

    def test_token_signed_with_incorrect_secret_rejected(self) -> None:
        """Tokens signed with a different/incorrect secret are rejected."""
        foreign_secret = "completely-different-unauthorized-secret"
        foreign_token = jwt.encode(
            {
                "sub": "user-123",
                "role": "MEMBER",
                "exp": datetime.now(UTC) + timedelta(minutes=30),
            },
            foreign_secret,
            algorithm=ALGORITHM,
        )

        with pytest.raises(JWTError):
            jwt.decode(foreign_token, TEST_SECRET, algorithms=[ALGORITHM])

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=foreign_token)
        mock_db = MagicMock(spec=Session)

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=creds, db=mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Could not validate credentials"

    @pytest.mark.parametrize(
        "payload",
        [
            {"role": "MEMBER"},  # missing "sub"
            {"sub": "", "role": "MEMBER"},  # empty string "sub"
            {"sub": "   ", "role": "MEMBER"},  # whitespace-only "sub"
            {"sub": 12345, "role": "MEMBER"},  # integer "sub"
            {"sub": None, "role": "MEMBER"},  # None "sub"
            {"sub": ["user-id"], "role": "MEMBER"},  # list "sub"
            {"sub": {"id": "user-id"}, "role": "MEMBER"},  # dict "sub"
        ],
    )
    def test_malformed_payload_rejected_in_get_current_user(
        self, payload: dict[str, Any]
    ) -> None:
        """Tokens with missing, empty, or non-string 'sub' claims are rejected."""
        to_encode = payload.copy()
        to_encode["exp"] = datetime.now(UTC) + timedelta(minutes=30)
        token = jwt.encode(to_encode, TEST_SECRET, algorithm=ALGORITHM)

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        mock_db = MagicMock(spec=Session)

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=creds, db=mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Could not validate credentials"

    def test_missing_credentials_rejected(self) -> None:
        """get_current_user raises 401 when credentials object is None."""
        mock_db = MagicMock(spec=Session)
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=None, db=mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Could not validate credentials"

    def test_missing_jwt_secret_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_get_secret_key raises RuntimeError when JWT_SECRET is unset or empty."""
        monkeypatch.delenv("JWT_SECRET", raising=False)

        with pytest.raises(
            RuntimeError, match="JWT_SECRET must be set before using authentication"
        ):
            _get_secret_key()

        with pytest.raises(
            RuntimeError, match="JWT_SECRET must be set before using authentication"
        ):
            create_access_token({"sub": "user-123"})


class TestUserLookupInGetCurrentUser:
    """Tests for database user lookup during token authentication in get_current_user."""

    def test_active_user_lookup_succeeds(self) -> None:
        """A valid token for an existing active user successfully resolves the user."""
        user_id = uuid.uuid4()
        token = create_access_token({"sub": str(user_id), "role": "MEMBER"})
        active_user = User(
            id=user_id,
            full_name="Valid Active User",
            email="valid@example.com",
            password_hash="hashed",
            role=UserRole.MEMBER,
            is_active=True,
        )

        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = active_user

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = get_current_user(credentials=creds, db=mock_db)

        assert user.id == user_id
        assert user.is_active is True

    def test_inactive_user_with_valid_token_rejected(self) -> None:
        """A valid token for an inactive user is rejected with 401 Unauthorized."""
        user_id = uuid.uuid4()
        token = create_access_token({"sub": str(user_id), "role": "MEMBER"})
        inactive_user = User(
            id=user_id,
            full_name="Deactivated User",
            email="inactive@example.com",
            password_hash="hashed",
            role=UserRole.MEMBER,
            is_active=False,
        )

        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = (
            inactive_user
        )

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=creds, db=mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Could not validate credentials"

    def test_nonexistent_user_with_valid_token_rejected(self) -> None:
        """A valid token for a deleted/nonexistent user is rejected with 401 Unauthorized."""
        user_id = uuid.uuid4()
        token = create_access_token({"sub": str(user_id), "role": "MEMBER"})

        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=creds, db=mock_db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Could not validate credentials"
