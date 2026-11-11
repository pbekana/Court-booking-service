from datetime import datetime 
import uuid
from typing import Optional
from decimal import Decimal
from sqlalchemy import DateTime,Numeric,String,func,text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column

class court(DeclarativeBase):
   __tablename__ = "courts"

id:Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True),
    primary_key=True,
    server_default=text("gen_random_uuid()"),
)
venue_id:Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),nullable=False)
name:Mapped[str] = mapped_column(String(100),nullable=False)
sport_type:Mapped[str] = mapped_column(String(50),nullable=False)
is_active:Mapped[bool] = mapped_column(nullable=False,server_default=text("true"))
created_at:Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())