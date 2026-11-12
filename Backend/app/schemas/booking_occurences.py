from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class booking_ocurrences(BaseModel):
    id:UUID
    recurring_series_id:UUID
    booking_id:UUID
    occurrence_date:datetime
    status:str
    created_at:datetime

    model_config = ConfigDict(from_attributes=True)
