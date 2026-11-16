from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class HoldCreate(BaseModel):
    court_id: UUID
    start_time: datetime
    end_time: datetime
    idempotency_key: str | None = None

    @field_validator("start_time", "end_time", mode="after")
    @classmethod
    def ensure_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class HoldResponse(BaseModel):
    id: UUID
    user_id: UUID
    court_id: UUID
    start_time: datetime
    end_time: datetime
    expires_at: datetime
    status: str
    idempotency_key: str | None = None
    created_at: datetime
    reservation_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)


# Backwards compatibility alias
hold = HoldResponse
