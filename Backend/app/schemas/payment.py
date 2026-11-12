from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class payment(BaseModel):
    id:UUID
    booking_id:Optional[UUID]
    hold_id:Optional[UUID]
    provider:str
    provider_transaction_id:Optional[str]
    payment_reference:str
    amount:Decimal
    currency:str
    status:str
    created_at:datetime
    updated_at:datetime

    model_config = ConfigDict(from_attributes=True)