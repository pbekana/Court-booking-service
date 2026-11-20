from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RefundInfo(BaseModel):
    eligible: bool
    amount: Decimal
    currency: str = "ETB"
    status: str | None = None
    provider_refund_id: str | None = None
    failure_reason: str | None = None


class BookingCancellationResponse(BaseModel):
    message: str
    booking_id: UUID
    booking_status: str
    status: str = "CANCELLED"
    cancelled_at: datetime | None = None
    refund: RefundInfo

    model_config = ConfigDict(from_attributes=True)


class BookingRefundResponse(BaseModel):
    booking_id: UUID
    refund_eligible: bool
    refund_amount: Decimal = Decimal("0.00")
    currency: str = "ETB"
    refund_status: str | None = None
    provider_refund_id: str | None = None
    created_at: datetime | None = None
    message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RefundResponse(BaseModel):
    id: UUID
    payment_id: UUID
    booking_id: UUID
    amount: Decimal
    currency: str = "ETB"
    provider_refund_id: str | None = None
    idempotency_key: str
    status: str
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
