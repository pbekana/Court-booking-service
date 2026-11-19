import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.idempotency import IdempotencyRecord


class IdempotencyRepository:
    @staticmethod
    def get(
        db: Session, user_id: UUID, idempotency_key: str
    ) -> IdempotencyRecord | None:
        stmt = select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        return db.scalar(stmt)

    @staticmethod
    def create(
        db: Session,
        user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        response_reference: UUID | None = None,
    ) -> IdempotencyRecord:
        record = IdempotencyRecord(
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_reference=response_reference,
        )
        db.add(record)
        db.flush()
        return record

    @staticmethod
    def compute_hash(data: Any) -> str:
        if isinstance(data, str):
            payload = data
        elif isinstance(data, dict):
            payload = json.dumps(data, sort_keys=True, default=str)
        else:
            payload = str(data)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
