from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CourtUtilization(BaseModel):
    court_id: UUID
    court_name: str
    venue_id: UUID
    venue_name: str
    sport_type: str
    total_operating_hours: Decimal = Field(default=Decimal("0.00"))
    total_booked_hours: Decimal = Field(default=Decimal("0.00"))
    total_available_hours: Decimal = Field(default=Decimal("0.00"))
    utilization_percentage: Decimal = Field(default=Decimal("0.00"))
    confirmed_bookings_count: int = 0
    number_of_confirmed_bookings: int = 0
    active_holds_count: int = 0
    active_hold_hours: Decimal = Field(default=Decimal("0.00"))

    model_config = ConfigDict(from_attributes=True)


class WeeklyUtilizationReport(BaseModel):
    start_date: date
    end_date: date
    total_courts: int = 0
    total_operating_hours: Decimal = Field(default=Decimal("0.00"))
    total_booked_hours: Decimal = Field(default=Decimal("0.00"))
    total_available_hours: Decimal = Field(default=Decimal("0.00"))
    overall_utilization_percentage: Decimal = Field(default=Decimal("0.00"))
    courts: list[CourtUtilization] = []

    model_config = ConfigDict(from_attributes=True)
