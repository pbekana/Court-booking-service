import os
from datetime import UTC, datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
MAX_PASSWORD_LENGTH = 72

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _get_secret_key() -> str:
    secret_key = os.getenv("JWT_SECRET")
    if not secret_key:
        raise RuntimeError("JWT_SECRET must be set before using authentication")
    return secret_key


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > MAX_PASSWORD_LENGTH:
        raise ValueError("Password exceeds bcrypt maximum length of 72 bytes")
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if len(plain_password.encode("utf-8")) > MAX_PASSWORD_LENGTH:
        return False
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()

    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})

    return jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)
