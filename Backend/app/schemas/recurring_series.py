from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict

class recurring_series(BaseModel):
    id:UUID
    user_id:UUID
    court_id:UUID
    day_of_week:int
    start_time:time
    end_time:time
    recurrence_start_date:date
    recurrence_end_date:date
    status:str
    created_at:datetime

    model_config = ConfigDict(from_attributes=True)