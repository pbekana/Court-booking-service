from datetime import datetime, time
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_iana_timezone(tz: str) -> str:
    cleaned = tz.strip()
    if not cleaned:
        raise ValueError("Timezone cannot be empty")
    try:
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError, Exception):
        raise ValueError(f"'{cleaned}' is not a valid IANA timezone")
    return cleaned


class VenueBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Venue name")
    address: Optional[str] = Field(None, max_length=255, description="Physical address of the venue")
    timezone: str = Field(
        default="Africa/Addis_Ababa",
        max_length=100,
        description="IANA timezone identifier (e.g., Africa/Addis_Ababa, Europe/London)",
    )
    opening_time: time = Field(..., description="Daily opening time (HH:MM:SS)")
    closing_time: time = Field(..., description="Daily closing time (HH:MM:SS)")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Venue name cannot be empty")
        return cleaned

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        return _validate_iana_timezone(v)

    @model_validator(mode="after")
    def validate_operating_hours(self) -> "VenueBase":
        if self.opening_time is not None and self.closing_time is not None:
            if self.opening_time >= self.closing_time:
                raise ValueError("Opening time must be earlier than closing time")
        return self


class VenueCreate(VenueBase):
    pass


class VenueUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    address: Optional[str] = Field(None, max_length=255)
    timezone: Optional[str] = Field(None, max_length=100)
    opening_time: Optional[time] = None
    closing_time: Optional[time] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Venue name cannot be empty")
            return cleaned
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_iana_timezone(v)
        return v

    @model_validator(mode="after")
    def validate_hours(self) -> "VenueUpdate":
        if self.opening_time is not None and self.closing_time is not None:
            if self.opening_time >= self.closing_time:
                raise ValueError("Opening time must be earlier than closing time")
        return self


class VenueResponse(BaseModel):
    id: UUID
    name: str
    address: Optional[str] = None
    timezone: str
    opening_time: time
    closing_time: time
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Backward compatibility alias
venue = VenueResponse
