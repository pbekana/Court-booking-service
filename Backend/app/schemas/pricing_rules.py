from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class pricing_rules(BaseModel):
    id:UUID
    court_id:UUID
    pricing_type:str
    start_time:time
    end_time:time
    day_of_week:int | None
    hourly_rate:Decimal
    currency:str
    effective_from:date
    effective_until:date | None
    created_at:datetime

    model_config = ConfigDict(from_attributes=True)
