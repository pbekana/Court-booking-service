from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class payment(BaseModel):
    id:UUID
    booking_id:UUID | None
    hold_id:UUID | None
    provider:str
    provider_transaction_id:str | None
    payment_reference:str
    amount:Decimal
    currency:str
    status:str
    created_at:datetime
    updated_at:datetime

    model_config = ConfigDict(from_attributes=True)