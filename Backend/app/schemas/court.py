from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class court(BaseModel):
    id:UUID
    venue_id:UUID
    name:str
    sport_type:str
    is_active:bool
    created_at:datetime

    model_config = ConfigDict(from_attributes=True)