from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PaymentStatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class PaymentResponse(BaseModel):
    id: UUID
    booking_id: UUID | None = None
    hold_id: UUID | None = None
    provider: str
    provider_transaction_id: str | None = None
    payment_reference: str
    amount: Decimal
    currency: str = "ETB"
    status: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PaymentWebhookPayload(BaseModel):
    provider: str = Field(..., min_length=1, max_length=50)
    provider_transaction_id: str = Field(..., min_length=1, max_length=255)
    event_type: str = Field(..., min_length=1, max_length=50)
    signature: str = Field(..., min_length=1)
    status: str | None = None
    payment_reference: str | None = None
    amount: Decimal | None = None
    currency: str | None = None


class RefundResponse(BaseModel):
    payment_id: UUID
    booking_id: UUID
    status: str
    amount: Decimal
    currency: str
    refund_transaction_id: str | None = None
    message: str


# Backwards compatibility alias
payment = PaymentResponse
