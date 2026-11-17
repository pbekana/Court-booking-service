from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.pricing_rules import PricingRule


class PricingRepository:
    @staticmethod
    def get_candidate_rules(
        db: Session,
        court_id: UUID,
        booking_date: date,
        day_of_week: int,
    ) -> list[PricingRule]:
        """Retrieve all pricing rules for the given court that are effective on the

        specified date and apply to the specified day of week (or all days).
        """
        stmt = (
            select(PricingRule)
            .where(
                PricingRule.court_id == court_id,
                PricingRule.effective_from <= booking_date,
                or_(
                    PricingRule.effective_until.is_(None),
                    PricingRule.effective_until >= booking_date,
                ),
                or_(
                    PricingRule.day_of_week.is_(None),
                    PricingRule.day_of_week == day_of_week,
                ),
            )
            .order_by(
                PricingRule.start_time.asc(),
            )
        )
        return list(db.scalars(stmt).all())
