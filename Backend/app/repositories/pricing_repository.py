from datetime import date, time
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.pricing_rules import PricingRule


def time_intervals_overlap(
    s1: time, e1: time, s2: time, e2: time
) -> bool:
    """Checks if two time intervals overlap on the 24-hour clock.

    Supports both normal intervals (start < end) and overnight intervals (start > end).
    """
    # Break interval 1 into normal segments on [00:00, 24:00)
    segs1: list[tuple[time, time]] = []
    if s1 < e1:
        segs1.append((s1, e1))
    else:
        segs1.append((s1, time.max))
        segs1.append((time.min, e1))

    # Break interval 2 into normal segments on [00:00, 24:00)
    segs2: list[tuple[time, time]] = []
    if s2 < e2:
        segs2.append((s2, e2))
    else:
        segs2.append((s2, time.max))
        segs2.append((time.min, e2))

    for a_start, a_end in segs1:
        for b_start, b_end in segs2:
            if max(a_start, b_start) < min(a_end, b_end):
                return True
    return False


class PricingRepository:
    @staticmethod
    def get_candidate_rules(
        db: Session,
        court_id: UUID,
        booking_date: date,
        day_of_week: int,
    ) -> list[PricingRule]:
        """Retrieve all active pricing rules for the given court that are effective on the

        specified date and apply to the specified day of week (or all days).
        """
        stmt = (
            select(PricingRule)
            .where(
                PricingRule.court_id == court_id,
                PricingRule.is_active.is_(True),
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

    @staticmethod
    def get_active_candidate_rules_for_range(
        db: Session,
        court_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[PricingRule]:
        stmt = (
            select(PricingRule)
            .where(
                PricingRule.court_id == court_id,
                PricingRule.is_active.is_(True),
                PricingRule.effective_from <= end_date,
                or_(
                    PricingRule.effective_until.is_(None),
                    PricingRule.effective_until >= start_date,
                ),
            )
            .order_by(
                PricingRule.start_time.asc(),
            )
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def court_has_any_rules(db: Session, court_id: UUID) -> bool:
        stmt = (
            select(PricingRule.id)
            .where(
                PricingRule.court_id == court_id,
                PricingRule.is_active.is_(True),
            )
            .limit(1)
        )
        return db.scalar(stmt) is not None

    @staticmethod
    def get_by_id(db: Session, rule_id: UUID) -> PricingRule | None:
        return db.get(PricingRule, rule_id)

    @staticmethod
    def get_all(
        db: Session,
        court_id: UUID | None = None,
        active_only: bool = False,
        effective_date: date | None = None,
    ) -> list[PricingRule]:
        stmt = select(PricingRule)
        if court_id is not None:
            stmt = stmt.where(PricingRule.court_id == court_id)
        if active_only:
            stmt = stmt.where(PricingRule.is_active.is_(True))
        if effective_date is not None:
            stmt = stmt.where(
                PricingRule.effective_from <= effective_date,
                or_(
                    PricingRule.effective_until.is_(None),
                    PricingRule.effective_until >= effective_date,
                ),
            )
        stmt = stmt.order_by(
            PricingRule.court_id.asc(),
            PricingRule.effective_from.asc(),
            PricingRule.start_time.asc(),
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def find_conflicts(
        db: Session,
        court_id: UUID,
        day_of_week: int | None,
        start_time: time,
        end_time: time,
        effective_from: date,
        effective_until: date | None,
        exclude_rule_id: UUID | None = None,
    ) -> list[PricingRule]:
        """Finds any active rules for the same court that have overlapping schedules."""
        max_end_date = effective_until or date.max
        stmt = (
            select(PricingRule)
            .where(
                PricingRule.court_id == court_id,
                PricingRule.is_active.is_(True),
                PricingRule.effective_from <= max_end_date,
                or_(
                    PricingRule.effective_until.is_(None),
                    PricingRule.effective_until >= effective_from,
                ),
            )
        )
        if exclude_rule_id is not None:
            stmt = stmt.where(PricingRule.id != exclude_rule_id)

        candidates = list(db.scalars(stmt).all())
        conflicts: list[PricingRule] = []

        for rule in candidates:
            # Check day of week overlap
            days_overlap = (
                day_of_week is None
                or rule.day_of_week is None
                or day_of_week == rule.day_of_week
            )
            if not days_overlap:
                continue

            # Check time interval overlap
            if time_intervals_overlap(
                start_time, end_time, rule.start_time, rule.end_time
            ):
                conflicts.append(rule)

        return conflicts

    @staticmethod
    def create(db: Session, rule: PricingRule) -> PricingRule:
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule

    @staticmethod
    def update(db: Session, rule: PricingRule) -> PricingRule:
        db.commit()
        db.refresh(rule)
        return rule

    @staticmethod
    def delete(db: Session, rule: PricingRule, soft: bool = True) -> None:
        if soft:
            rule.is_active = False
            db.commit()
        else:
            db.delete(rule)
            db.commit()
