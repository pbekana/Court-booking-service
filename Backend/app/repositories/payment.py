import logging

from fastapi import Fastapi
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import fastapi
from sqlalchemy import func, select, text,insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from Backend.app.schemas import court
from app.models.payment import payment

logger = logging.getLogger(__name__)
class PaymentRepository:
    @staticmethod
    def get_by_id(db:Session, payment_id: UUID) -> payment | None:
        return db.get(payment, payment_id)
    app = Fastapi()
    @app.get("/payments/{payment_id}")
    def get_payment_repository(court_id: UUID) -> PaymentRepository:
        if court_id is None:
            raise fastapi.HTTPException(status_code=400, detail="court_id is required")
        else:
         return {court_id:court_id,booking_id:booking_id,hold_id:hold_id,provider:provider,provider_transaction_id:provider_transaction_id,payment_reference:payment_reference,amount:amount,currency:currency,status:status,created_at:created_at,updated_at:updated_at}
         db.add(payment)
    