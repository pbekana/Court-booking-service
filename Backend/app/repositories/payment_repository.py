from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payment import Payment


class PaymentRepository:
    @staticmethod
    def get_by_id(db: Session, payment_id: UUID) -> Payment | None:
        return db.get(Payment, payment_id)

    @staticmethod
    def get_by_reference(db: Session, payment_reference: str) -> Payment | None:
        stmt = select(Payment).where(Payment.payment_reference == payment_reference)
        return db.scalar(stmt)

    @staticmethod
    def get_by_hold_id(db: Session, hold_id: UUID) -> Payment | None:
        stmt = select(Payment).where(Payment.hold_id == hold_id)
        return db.scalar(stmt)

    @staticmethod
    def get_by_booking_id(db: Session, booking_id: UUID) -> Payment | None:
        stmt = select(Payment).where(Payment.booking_id == booking_id)
        return db.scalar(stmt)

    @staticmethod
    def get_by_provider_transaction_id(
        db: Session, provider: str, provider_transaction_id: str
    ) -> Payment | None:
        stmt = select(Payment).where(
            Payment.provider == provider,
            Payment.provider_transaction_id == provider_transaction_id,
        )
        return db.scalar(stmt)

    @staticmethod
    def create(db: Session, payment: Payment) -> Payment:
        db.add(payment)
        db.flush()
        return payment

    @staticmethod
    def update(db: Session, payment: Payment) -> Payment:
        db.flush()
        return payment
