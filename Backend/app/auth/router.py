from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_role
from app.core.db import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.auth import AuthResponse, UserLogin, UserPublic
from app.schemas.user import UserRegister

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


def serialize_user(user: User) -> dict:
    role_raw = user.role.value if hasattr(user.role, "value") else str(user.role)
    role_upper = str(role_raw).upper()
    if "ADMIN" in role_upper:
        role = "ADMIN"
    elif "STAFF" in role_upper:
        role = "STAFF"
    else:
        role = "MEMBER"
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "role": role,
    }


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    user_data: UserRegister,
    db: Annotated[Session, Depends(get_db)],
):
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered",
        )

    new_user = User(
        full_name=user_data.full_name,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        role=UserRole.User,
    )

    db.add(new_user)
    try:
        db.flush()
        access_token = create_access_token(
            {
                "sub": str(new_user.id),
                "role": new_user.role.value if hasattr(new_user.role, "value") else str(new_user.role),
            }
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already registered",
            ) from error
        raise
    db.refresh(new_user)

    return {
        "user": serialize_user(new_user),
        "token": access_token,
    }


@router.post(
    "/login",
    response_model=AuthResponse,
)
def login_user(
    user_data: UserLogin,
    db: Annotated[Session, Depends(get_db)],
):
    user = db.query(User).filter(User.email == user_data.email).first()

    if user is None or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token = create_access_token(
        {
            "sub": str(user.id),
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        }
    )

    return {
        "user": serialize_user(user),
        "token": access_token,
    }


@router.post("/logout")
def logout_user(
    current_user: Annotated[User, Depends(get_current_user)],
):
    return {
        "message": "Logged out successfully. JWTs are stateless; remove the token from the client storage.",
        "user": serialize_user(current_user),
    }


@router.get(
    "/me",
    response_model=dict,
)
def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
):
    return {"user": serialize_user(current_user)}


@router.get("/staff/me", response_model=UserPublic)
def get_staff_profile(
    current_user: Annotated[User, Depends(require_role(UserRole.Staff))],
):
    return serialize_user(current_user)
