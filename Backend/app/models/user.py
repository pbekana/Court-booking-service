import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    STAFF = "STAFF"
    MEMBER = "MEMBER"
    User = "MEMBER"
    Staff = "STAFF"
    Admin = "ADMIN"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    full_name: Mapped[str] = mapped_column(String(100), nullable=False)

    email: Mapped[str] = mapped_column(
        String(150), unique=True, index=True, nullable=False
    )

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="MEMBER",
        server_default=text("'MEMBER'"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.now,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.now,
        server_default=func.now(),
        onupdate=func.now(),
    )
