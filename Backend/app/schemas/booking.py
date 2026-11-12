from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class booking(BaseModel):
    id: UUID
    reservation_id: UUID
    hold_id: UUID
    user_id: UUID
    court_id: UUID
    start_at:datetime
    end_at:datetime
    total_price:Decimal
    currency:str
    status:str
    created_at:datetime
    cancelled_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
