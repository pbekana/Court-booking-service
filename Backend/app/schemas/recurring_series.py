from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecurringSeriesBase(BaseModel):
    court_id: UUID
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    start_time: time
    end_time: time
    recurrence_start_date: date
    recurrence_end_date: date

    @model_validator(mode="after")
    def validate_series_dates_and_times(self) -> "RecurringSeriesBase":
        if self.start_time >= self.end_time:
            raise ValueError("end_time must be strictly later than start_time")
        if self.recurrence_end_date < self.recurrence_start_date:
            raise ValueError("recurrence_end_date cannot be earlier than recurrence_start_date")
        return self


class RecurringSeriesCreate(RecurringSeriesBase):
    pass


class RecurringSeriesResponse(BaseModel):
    id: UUID
    user_id: UUID
    court_id: UUID
    day_of_week: int
    start_time: time
    end_time: time
    recurrence_start_date: date
    recurrence_end_date: date
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Backwards compatibility alias
recurring_series = RecurringSeriesResponse
