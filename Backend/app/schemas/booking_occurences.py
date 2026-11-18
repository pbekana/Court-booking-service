from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BookingOccurrenceResponse(BaseModel):
    id: UUID
    recurring_series_id: UUID
    booking_id: UUID
    occurrence_date: date
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Backwards compatibility alias
booking_ocurrences = BookingOccurrenceResponse
