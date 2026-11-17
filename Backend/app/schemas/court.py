from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.venue import VenueResponse


class CourtBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Court name")
    sport_type: str = Field(..., min_length=1, max_length=50, description="Sport type (e.g., Tennis, Basketball)")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Court name cannot be empty")
        return cleaned

    @field_validator("sport_type")
    @classmethod
    def validate_sport_type(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Sport type cannot be empty")
        return cleaned


class CourtCreate(CourtBase):
    venue_id: UUID = Field(..., description="Associated Venue UUID")


class CourtUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    sport_type: str | None = Field(None, min_length=1, max_length=50)
    venue_id: UUID | None = Field(None, description="Venue UUID to move court to")
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Court name cannot be empty")
            return cleaned
        return v

    @field_validator("sport_type")
    @classmethod
    def validate_sport_type(cls, v: str | None) -> str | None:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Sport type cannot be empty")
            return cleaned
        return v


class CourtResponse(BaseModel):
    id: UUID
    venue_id: UUID
    name: str
    sport_type: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CourtDetailResponse(CourtResponse):
    venue: VenueResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class AvailabilityInterval(BaseModel):
    start_at: datetime
    end_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PricingSegment(BaseModel):
    pricing_type: str
    start_at: datetime
    end_at: datetime
    hourly_rate: Decimal
    subtotal: Decimal

    model_config = ConfigDict(from_attributes=True)


class PricingBreakdown(BaseModel):
    currency: str
    total_price: Decimal
    segments: list[PricingSegment]

    model_config = ConfigDict(from_attributes=True)


class CourtAvailabilityRequest(BaseModel):
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def validate_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("Timestamps must include timezone information")
        return v


class CourtAvailabilityResponse(BaseModel):
    court_id: UUID
    venue_id: UUID | None = None
    available: bool
    requested_interval: AvailabilityInterval | None = None
    pricing: PricingBreakdown | None = None
    message: str

    model_config = ConfigDict(from_attributes=True)


# Backward compatibility alias
court = CourtResponse
