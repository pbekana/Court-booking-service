from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_user_role_str, require_roles
from app.core.db import get_db
from app.models.user import User, UserRole
from app.schemas.court import CourtCreate, CourtDetailResponse, CourtResponse, CourtUpdate
from app.services.court_service import CourtService

router = APIRouter(prefix="/api/v1/courts", tags=["Courts"])


@router.post(
    "",
    response_model=CourtResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new court",
    description="Administrator endpoint to create a court within an existing active venue.",
)
def create_court(
    court_in: CourtCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, "ADMIN"))],
):
    return CourtService.create_court(db, court_in)


@router.get(
    "",
    response_model=list[CourtResponse],
    summary="Get all courts",
    description="Retrieve courts with optional filtering by venue_id and sport_type. Members see active courts only.",
)
def get_all_courts(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    venue_id: Annotated[
        Optional[UUID],
        Query(description="Filter courts by venue UUID"),
    ] = None,
    sport_type: Annotated[
        Optional[str],
        Query(description="Filter courts by sport type (case-insensitive)"),
    ] = None,
    active_only: Annotated[
        bool,
        Query(description="Filter by active status only"),
    ] = True,
):
    user_role = get_user_role_str(current_user)
    is_active_only = True if user_role == "MEMBER" else active_only
    return CourtService.get_courts(
        db,
        venue_id=venue_id,
        sport_type=sport_type,
        is_active_only=is_active_only,
    )


@router.get(
    "/{court_id}",
    response_model=CourtDetailResponse,
    summary="Get court by ID",
    description="Retrieve details of a specific court along with its associated venue.",
)
def get_court_by_id(
    court_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    user_role = get_user_role_str(current_user)
    is_active_only = user_role == "MEMBER"
    return CourtService.get_court_by_id(db, court_id, is_active_only=is_active_only)


@router.patch(
    "/{court_id}",
    response_model=CourtResponse,
    summary="Update court details",
    description="Administrator endpoint to update court details, move it to another venue, or change active status.",
)
def update_court(
    court_id: UUID,
    court_in: CourtUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, "ADMIN"))],
):
    return CourtService.update_court(db, court_id, court_in)


@router.delete(
    "/{court_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a court",
    description="Administrator endpoint to soft-delete a court. Fails if active future reservations exist.",
)
def deactivate_court(
    court_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, "ADMIN"))],
):
    CourtService.deactivate_court(db, court_id)
    return None
