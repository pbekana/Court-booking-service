"""Unit tests for password hashing and verification functionality.

Covers:
- Password hashing success and bcrypt format.
- Generated hash != plain password.
- Verification of correct password against hash.
- Rejection of incorrect password.
- Cryptographic salt uniqueness (two hashes of same password differ).
- Empty password handling.
- Bcrypt 72-byte boundary and multi-byte UTF-8 handling.
- Invalid input handling.
"""

import passlib.exc
import pytest

from app.core.security import hash_password, verify_password


class TestPasswordHashing:
    """Tests for password hashing function."""

    def test_hash_password_success(self) -> None:
        """A password can be hashed successfully and produces a bcrypt hash."""
        password = "SecurePassword123!"
        hashed = hash_password(password)

        assert isinstance(hashed, str)
        assert len(hashed) > 0
        assert hashed.startswith(("$2b$", "$2a$", "$2y$"))

    def test_hash_not_equal_to_original_password(self) -> None:
        """The generated hash is not equal to the original plaintext password."""
        password = "MySuperSecretPassword"
        hashed = hash_password(password)

        assert hashed != password

    def test_verify_password_success_with_matching_password(self) -> None:
        """The same password can be verified against its hash."""
        password = "CorrectHorseBatteryStaple"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_fails_with_incorrect_password(self) -> None:
        """An incorrect password fails verification."""
        password = "CorrectPassword123"
        hashed = hash_password(password)

        assert verify_password("WrongPassword123", hashed) is False
        assert verify_password("correctpassword123", hashed) is False
        assert verify_password("CorrectPassword123 ", hashed) is False

    def test_password_salting_uniqueness(self) -> None:
        """Two hashes of the same password are not identical due to cryptographic salting."""
        password = "SamePasswordTwice!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True

    def test_empty_password_handled(self) -> None:
        """Empty password input can be hashed and verified appropriately."""
        hashed = hash_password("")

        assert isinstance(hashed, str)
        assert verify_password("", hashed) is True
        assert verify_password("non-empty", hashed) is False

    def test_password_boundary_at_max_length(self) -> None:
        """Passwords at exactly 72 UTF-8 bytes succeed, while >72 bytes are rejected."""
        exact_72_bytes = "a" * 72
        hashed = hash_password(exact_72_bytes)
        assert verify_password(exact_72_bytes, hashed) is True

        exceeds_72_bytes = "a" * 73
        with pytest.raises(
            ValueError, match="Password exceeds bcrypt maximum length of 72 bytes"
        ):
            hash_password(exceeds_72_bytes)

        # verify_password early-rejects passwords exceeding 72 bytes
        assert verify_password(exceeds_72_bytes, hashed) is False

    def test_utf8_multi_byte_password_handling(self) -> None:
        """UTF-8 multi-byte characters are measured by byte length rather than character count."""
        # 4-byte emoji: '🔒' is 4 bytes in UTF-8
        # 10 emojis = 40 bytes (< 72 bytes), should succeed
        emoji_pass = "🔒" * 10
        hashed = hash_password(emoji_pass)
        assert verify_password(emoji_pass, hashed) is True

        # 19 emojis = 76 bytes (> 72 bytes), should raise ValueError
        long_emoji_pass = "🔒" * 19
        with pytest.raises(
            ValueError, match="Password exceeds bcrypt maximum length of 72 bytes"
        ):
            hash_password(long_emoji_pass)

        assert verify_password(long_emoji_pass, hashed) is False

    def test_invalid_hash_verification_raises_or_fails(self) -> None:
        """Malformed or unrecognizable hash strings raise UnknownHashError in passlib."""
        with pytest.raises(passlib.exc.UnknownHashError):
            verify_password("password", "invalid_plain_text_hash")

        with pytest.raises(passlib.exc.UnknownHashError):
            verify_password("password", "")
