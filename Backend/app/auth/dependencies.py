import uuid
from collections.abc import Callable
from typing import Annotated, Union

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import ALGORITHM, _get_secret_key
from app.models.user import User, UserRole

security = HTTPBearer(auto_error=False)


def get_user_role_str(user: User) -> str:
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    role_upper = str(role_val).upper()
    if "ADMIN" in role_upper:
        return "ADMIN"
    elif "STAFF" in role_upper:
        return "STAFF"
    return "MEMBER"


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(security),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    try:
        payload = jwt.decode(
            credentials.credentials,
            _get_secret_key(),
            algorithms=[ALGORITHM],
        )

        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id.strip():
            raise credentials_exception
    except (JWTError, TypeError, ValueError):
        raise credentials_exception

    user = None
    if user_id.isdecimal():
        user = db.query(User).filter(User.id == int(user_id)).first()
    else:
        try:
            val = uuid.UUID(user_id)
            user = db.query(User).filter(User.id == val).first()
        except Exception:
            user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise credentials_exception

    return user


def require_role(required_role: Union[UserRole, str]) -> Callable[..., User]:
    def role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        user_role_str = get_user_role_str(current_user)
        target = required_role.value if hasattr(required_role, "value") else str(required_role)
        target_upper = str(target).upper()
        if "ADMIN" in target_upper:
            expected = "ADMIN"
        elif "STAFF" in target_upper:
            expected = "STAFF"
        else:
            expected = "MEMBER"

        if user_role_str != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return current_user

    return role_checker


def require_roles(*allowed_roles: Union[UserRole, str]) -> Callable[..., User]:
    def role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        user_role_str = get_user_role_str(current_user)
        expected_set = set()
        for r in allowed_roles:
            target = r.value if hasattr(r, "value") else str(r)
            target_upper = str(target).upper()
            if "ADMIN" in target_upper:
                expected_set.add("ADMIN")
            elif "STAFF" in target_upper:
                expected_set.add("STAFF")
            else:
                expected_set.add("MEMBER")

        if user_role_str not in expected_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return current_user

    return role_checker
