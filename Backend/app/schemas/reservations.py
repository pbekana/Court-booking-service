from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class reservations(BaseModel):
    id:UUID
    user_id:UUID
    court_id:UUID
    start_at:datetime
    end_at:datetime
    status:str
    expires_at:datetime | None
    created_at:datetime

    model_config = ConfigDict(from_attributes=True)