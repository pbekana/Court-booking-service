from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class hold(BaseModel):
    id:UUID
    reservation_id:UUID
    user_id:UUID
    idempotency_key:Optional[str]
    status:str
    expires_at:datetime
    created_at:datetime

    model_config = ConfigDict(from_attributes=True)