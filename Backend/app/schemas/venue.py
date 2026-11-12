from datetime import datetime, time
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

class venue(BaseModel):
    id:UUID
    name:str
    address:Optional[str]
    timezone:str
    opening_time:time
    closing_time:time
    is_active:bool
    created_at:datetime

    model_config = ConfigDict(from_attributes=True)