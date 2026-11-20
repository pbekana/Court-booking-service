from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.refund import Refund, RefundStatus


class RefundRepository:
    @staticmethod
    def get_by_id(db: Session, refund_id: UUID) -> Refund | None:
        return db.get(Refund, refund_id)

    @staticmethod
    def get_by_booking_id(db: Session, booking_id: UUID) -> Refund | None:
        stmt = (
            select(Refund)
            .where(Refund.booking_id == booking_id)
            .order_by(Refund.created_at.desc())
        )
        return db.scalars(stmt).first()

    @staticmethod
    def get_by_idempotency_key(
        db: Session, idempotency_key: str
    ) -> Refund | None:
        stmt = select(Refund).where(Refund.idempotency_key == idempotency_key)
        return db.scalar(stmt)

    @staticmethod
    def get_by_payment_id(db: Session, payment_id: UUID) -> list[Refund]:
        stmt = (
            select(Refund)
            .where(Refund.payment_id == payment_id)
            .order_by(Refund.created_at.desc())
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def create(db: Session, refund: Refund) -> Refund:
        db.add(refund)
        db.flush()
        return refund

    @staticmethod
    def update(db: Session, refund: Refund) -> Refund:
        db.flush()
        return refund

    @staticmethod
    def get_retryable_refunds(db: Session) -> list[Refund]:
        stmt = (
            select(Refund)
            .where(
                Refund.status.in_(
                    [RefundStatus.PENDING.value, RefundStatus.FAILED.value]
                )
            )
            .order_by(Refund.created_at.asc())
        )
        return list(db.scalars(stmt).all())
