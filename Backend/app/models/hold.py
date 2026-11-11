from datetime import datetime 
import uuid
from typing import Optional
from decimal import Decimal
from sqlalchemy import DateTime,Numeric,String,func,text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column

class booking_ocurrences(DeclarativeBase):
     __tablename  = "booking_ocurrences"
     id:Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
     reservation_id  :Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),nullable=False)
     user_id :Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),nullable=False)
     idempotency_key:Mapped[str] = mapped_column(Optional(String(255)),nullable=True)
     status:Mapped[str] = mapped_column(String(20),nullable=False,server_default=text("'held'"))
     expires_at:Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False)
     created_at:Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())