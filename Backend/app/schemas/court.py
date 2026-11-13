from datetime import datetime
from typing import Optional
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
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    sport_type: Optional[str] = Field(None, min_length=1, max_length=50)
    venue_id: Optional[UUID] = Field(None, description="Venue UUID to move court to")
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Court name cannot be empty")
            return cleaned
        return v

    @field_validator("sport_type")
    @classmethod
    def validate_sport_type(cls, v: Optional[str]) -> Optional[str]:
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
    venue: Optional[VenueResponse] = None

    model_config = ConfigDict(from_attributes=True)


# Backward compatibility alias
court = CourtResponse
