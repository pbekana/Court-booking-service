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
     recurring_series_id :Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),nullable=False)
     booking_id :Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),nullable=False)
     occurrence_date:Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())  
     status:Mapped[str] = mapped_column(String(20),nullable=False)
     created_at:Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())