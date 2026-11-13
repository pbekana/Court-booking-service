from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, get_user_role_str, require_roles
from app.core.db import get_db
from app.models.user import User, UserRole
from app.schemas.venue import VenueCreate, VenueResponse, VenueUpdate
from app.services.venue_service import VenueService

router = APIRouter(prefix="/api/v1/venues", tags=["Venues"])


@router.post(
    "",
    response_model=VenueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new venue",
    description="Administrator endpoint to create a physical sports venue.",
)
def create_venue(
    venue_in: VenueCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, "ADMIN"))],
):
    return VenueService.create_venue(db, venue_in)


@router.get(
    "",
    response_model=list[VenueResponse],
    summary="Get all venues",
    description="Retrieve venues. Members see active venues; Staff and Admins can see all venues.",
)
def get_all_venues(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    active_only: Annotated[
        bool,
        Query(description="Filter by active status only"),
    ] = True,
):
    user_role = get_user_role_str(current_user)
    is_active_only = True if user_role == "MEMBER" else active_only
    return VenueService.get_venues(db, is_active_only=is_active_only)


@router.get(
    "/{venue_id}",
    response_model=VenueResponse,
    summary="Get venue by ID",
    description="Retrieve details of a specific venue by its UUID.",
)
def get_venue_by_id(
    venue_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    user_role = get_user_role_str(current_user)
    is_active_only = user_role == "MEMBER"
    return VenueService.get_venue_by_id(db, venue_id, is_active_only=is_active_only)


@router.patch(
    "/{venue_id}",
    response_model=VenueResponse,
    summary="Update venue details",
    description="Administrator endpoint to update venue information such as operating hours, address, or active status.",
)
def update_venue(
    venue_id: UUID,
    venue_in: VenueUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, "ADMIN"))],
):
    return VenueService.update_venue(db, venue_id, venue_in)


@router.delete(
    "/{venue_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a venue",
    description="Administrator endpoint to soft-delete a venue. Fails if active future reservations exist.",
)
def deactivate_venue(
    venue_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, "ADMIN"))],
):
    VenueService.deactivate_venue(db, venue_id)
    return None
