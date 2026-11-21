from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.court import CourtResponse
from app.schemas.hold import HoldResponse
from app.schemas.refund import RefundInfo


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
    series_id: UUID | None = None
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

    @model_validator(mode="after")
    def populate_series_id(self) -> "RecurringSeriesResponse":
        if self.series_id is None:
            self.series_id = self.id
        return self


class RecurringOccurrenceDetail(BaseModel):
    occurrence_id: UUID | None = None
    occurrence_date: date
    start_time: datetime
    end_time: datetime
    status: str
    hold_id: UUID | None = None
    reservation_id: UUID | None = None
    booking_id: UUID | None = None
    hold_status: str | None = None
    booking_status: str | None = None
    total_price: Decimal | None = None
    currency: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RecurringSeriesDetailResponse(BaseModel):
    id: UUID
    series_id: UUID | None = None
    user_id: UUID
    court_id: UUID
    court: CourtResponse | None = None
    day_of_week: int
    start_time: time
    end_time: time
    recurrence_start_date: date
    recurrence_end_date: date
    status: str
    created_at: datetime
    occurrences: list[RecurringOccurrenceDetail] = []
    holds: list[HoldResponse] = []

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def populate_series_id(self) -> "RecurringSeriesDetailResponse":
        if self.series_id is None:
            self.series_id = self.id
        return self


class OccurrenceCancellationResponse(BaseModel):
    message: str
    series_id: UUID
    occurrence_id: UUID
    occurrence_date: date | None = None
    status: str = "CANCELLED"
    booking_id: UUID | None = None
    hold_id: UUID | None = None
    refund: RefundInfo | None = None
    cancelled_at: datetime | None = None


class RecurringSeriesCancellationResponse(BaseModel):
    message: str
    series_id: UUID
    status: str = "CANCELLED"
    cancelled_occurrences_count: int
    cancelled_holds_count: int
    cancelled_bookings_count: int
    total_refund_amount: Decimal = Decimal("0.00")
    currency: str = "ETB"
    occurrences: list[OccurrenceCancellationResponse] = []


# Backwards compatibility alias
recurring_series = RecurringSeriesResponse
