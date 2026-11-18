from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PricingRuleBase(BaseModel):
    court_id: UUID
    pricing_type: Literal["PEAK", "OFF_PEAK"] = Field(
        ..., description="Pricing category (PEAK or OFF_PEAK)"
    )
    start_time: time = Field(..., description="Start time (HH:MM:SS)")
    end_time: time = Field(..., description="End time (HH:MM:SS)")
    day_of_week: int | None = Field(
        None, ge=0, le=6, description="0=Monday, 6=Sunday, None=all days"
    )
    hourly_rate: Decimal = Field(
        ..., gt=Decimal("0.00"), description="Hourly rate, must be greater than 0"
    )
    currency: str = Field(
        "ETB", min_length=3, max_length=3, description="Currency code (e.g. ETB, USD)"
    )
    effective_from: date = Field(..., description="Date this rule starts taking effect")
    effective_until: date | None = Field(
        None, description="Date this rule stops taking effect (inclusive)"
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 3:
            raise ValueError("Currency must be a 3-letter code")
        return v

    @field_validator("hourly_rate")
    @classmethod
    def validate_hourly_rate(cls, v: Decimal) -> Decimal:
        if v <= Decimal("0.00"):
            raise ValueError("Hourly rate must be greater than zero")
        return v.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def validate_times_and_dates(self) -> "PricingRuleBase":
        if self.start_time == self.end_time:
            raise ValueError("start_time and end_time cannot be equal")
        if (
            self.effective_until is not None
            and self.effective_until < self.effective_from
        ):
            raise ValueError("effective_until cannot be earlier than effective_from")
        return self


class PricingRuleCreate(PricingRuleBase):
    pass


class PricingRuleUpdate(BaseModel):
    pricing_type: Literal["PEAK", "OFF_PEAK"] | None = None
    start_time: time | None = None
    end_time: time | None = None
    day_of_week: int | None = Field(None, ge=0, le=6)
    hourly_rate: Decimal | None = Field(None, gt=Decimal("0.00"))
    currency: str | None = Field(None, min_length=3, max_length=3)
    effective_from: date | None = None
    effective_until: date | None = None
    is_active: bool | None = None

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip().upper()
            if len(v) != 3:
                raise ValueError("Currency must be a 3-letter code")
            return v
        return v

    @field_validator("hourly_rate")
    @classmethod
    def validate_hourly_rate(cls, v: Decimal | None) -> Decimal | None:
        if v is not None:
            if v <= Decimal("0.00"):
                raise ValueError("Hourly rate must be greater than zero")
            return v.quantize(Decimal("0.01"))
        return v


class PricingRuleResponse(BaseModel):
    id: UUID
    court_id: UUID
    pricing_type: str
    start_time: time
    end_time: time
    day_of_week: int | None
    hourly_rate: Decimal
    currency: str
    effective_from: date
    effective_until: date | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PricingPreviewRequest(BaseModel):
    court_id: UUID
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def validate_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("Timestamps must include timezone information")
        return v

    @model_validator(mode="after")
    def validate_time_order(self) -> "PricingPreviewRequest":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be strictly later than start_at")
        return self


# Backwards compatibility alias
pricing_rules = PricingRuleResponse
