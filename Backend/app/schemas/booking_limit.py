from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ActiveReservationInfo(BaseModel):
    id: UUID
    court_id: UUID
    start_at: datetime
    end_at: datetime
    status: str
    expires_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class BookingLimitData(BaseModel):
    booking_limit: int = 3
    active_bookings: int
    remaining_bookings: int
    active_reservations: list[ActiveReservationInfo] = []


class BookingLimitResponse(BaseModel):
    success: bool = True
    data: BookingLimitData
