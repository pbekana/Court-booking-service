from app.services.recurring_booking_service import RecurringBookingService

# Backwards compatibility alias
RecurringService = RecurringBookingService

__all__ = ["RecurringBookingService", "RecurringService"]
