from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

class reservations(BaseModel):
    id:UUID
    user_id:UUID
    court_id:UUID
    start_at:datetime
    end_at:datetime
    status:str
    expires_at:Optional[datetime]
    created_at:datetime

    model_config = ConfigDict(from_attributes=True)