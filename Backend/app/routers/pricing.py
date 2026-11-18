from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.core.db import get_db
from app.models.user import User, UserRole
from app.schemas.court import PricingBreakdown
from app.schemas.pricing_rules import (
    PricingPreviewRequest,
    PricingRuleCreate,
    PricingRuleResponse,
    PricingRuleUpdate,
)
from app.services.pricing_service import PricingService

router = APIRouter(tags=["Pricing Rules"])


@router.post(
    "/pricing-rules",
    response_model=PricingRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a pricing rule",
    description="Administrator endpoint to create peak or off-peak pricing rules for a court.",
)
def create_pricing_rule(
    rule_in: PricingRuleCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, "ADMIN"))],
) -> PricingRuleResponse:
    rule = PricingService.create_pricing_rule(db=db, rule_in=rule_in)
    return PricingRuleResponse.model_validate(rule)


@router.get(
    "/pricing-rules",
    response_model=list[PricingRuleResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve all pricing rules",
    description="Retrieve pricing rules with optional filtering by court_id, active_only, and effective_date.",
)
def get_pricing_rules(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    court_id: Annotated[UUID | None, Query(description="Filter by court UUID")] = None,
    active_only: Annotated[
        bool, Query(description="Filter by active status only")
    ] = False,
    effective_date: Annotated[
        date | None, Query(description="Filter rules effective on this date")
    ] = None,
) -> list[PricingRuleResponse]:
    rules = PricingService.get_pricing_rules(
        db=db,
        court_id=court_id,
        active_only=active_only,
        effective_date=effective_date,
    )
    return [PricingRuleResponse.model_validate(r) for r in rules]


@router.get(
    "/pricing-rules/{rule_id}",
    response_model=PricingRuleResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a specific pricing rule",
)
def get_pricing_rule_by_id(
    rule_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PricingRuleResponse:
    rule = PricingService.get_pricing_rule_by_id(db=db, rule_id=rule_id)
    return PricingRuleResponse.model_validate(rule)


@router.get(
    "/courts/{court_id}/pricing-rules",
    response_model=list[PricingRuleResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve pricing rules for a court",
)
def get_court_pricing_rules(
    court_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    active_only: Annotated[
        bool, Query(description="Filter by active status only")
    ] = False,
) -> list[PricingRuleResponse]:
    rules = PricingService.get_pricing_rules(
        db=db,
        court_id=court_id,
        active_only=active_only,
    )
    return [PricingRuleResponse.model_validate(r) for r in rules]


@router.put(
    "/pricing-rules/{rule_id}",
    response_model=PricingRuleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a pricing rule",
    description="Administrator endpoint to update an existing pricing rule.",
)
def update_pricing_rule(
    rule_id: UUID,
    rule_in: PricingRuleUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, "ADMIN"))],
) -> PricingRuleResponse:
    updated = PricingService.update_pricing_rule(
        db=db,
        rule_id=rule_id,
        rule_in=rule_in,
    )
    return PricingRuleResponse.model_validate(updated)


@router.delete(
    "/pricing-rules/{rule_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete/deactivate a pricing rule",
    description="Administrator endpoint to soft-deactivate a pricing rule to preserve booking snapshots.",
)
def delete_pricing_rule(
    rule_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN, "ADMIN"))],
) -> dict[str, str]:
    PricingService.delete_pricing_rule(db=db, rule_id=rule_id)
    return {"message": "Pricing rule deleted successfully"}


@router.post(
    "/pricing/preview",
    response_model=PricingBreakdown,
    status_code=status.HTTP_200_OK,
    summary="Preview booking pricing",
    description="Calculate and preview exact price breakdown before creating a hold or booking.",
)
def preview_pricing(
    preview_in: PricingPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PricingBreakdown:
    return PricingService.preview_pricing(db=db, preview_in=preview_in)
