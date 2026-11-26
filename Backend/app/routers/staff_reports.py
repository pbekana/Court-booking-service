from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.core.db import get_db
from app.models.user import User, UserRole
from app.schemas.staff_report import WeeklyUtilizationReport
from app.services.utilization_service import UtilizationService

router = APIRouter(prefix="/reports", tags=["Staff Reports"])


@router.get(
    "/utilization",
    response_model=WeeklyUtilizationReport,
    status_code=status.HTTP_200_OK,
    summary="Get weekly court utilization report",
    description="Authorized staff and administrators can view weekly court utilization statistics.",
)
def get_weekly_utilization_report(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_roles(UserRole.STAFF, UserRole.ADMIN, "STAFF", "ADMIN")),
    ],
    venue_id: Annotated[
        UUID | None,
        Query(description="Optional filter by venue UUID"),
    ] = None,
    court_id: Annotated[
        UUID | None,
        Query(description="Optional filter by court UUID"),
    ] = None,
    start_date: Annotated[
        date | None,
        Query(description="Start date for utilization period (defaults to Monday of current week)"),
    ] = None,
    end_date: Annotated[
        date | None,
        Query(description="End date for utilization period (defaults to Sunday of current week)"),
    ] = None,
) -> WeeklyUtilizationReport:
    return UtilizationService.get_weekly_utilization_report(
        db=db,
        venue_id=venue_id,
        court_id=court_id,
        start_date=start_date,
        end_date=end_date,
    )
