from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories.hold_repository import HoldRepository


def cleanup_expired_holds(db: Session, court_id: UUID | None = None) -> int:
    """Expires all stale active holds whose expires_at timestamp has passed."""
    return HoldRepository.expire_stale_holds(db, court_id=court_id)
