from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.payment import PaymentResponse


class BookingResponse(BaseModel):
    id: UUID
    reservation_id: UUID | None = None
    hold_id: UUID
    user_id: UUID
    court_id: UUID
    start_at: datetime
    end_at: datetime
    total_price: Decimal
    currency: str = "ETB"
    status: str
    created_at: datetime
    cancelled_at: datetime | None = None
    payment: PaymentResponse | None = None

    model_config = ConfigDict(from_attributes=True)


# Backwards compatibility alias
booking = BookingResponse
