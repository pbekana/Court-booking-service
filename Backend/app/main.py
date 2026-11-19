from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.routers.booking import router as booking_router
from app.routers.court import availability_router
from app.routers.court import router as court_router
from app.routers.hold import router as hold_router
from app.routers.member import router as member_router
from app.routers.payment import router as payment_router
from app.routers.pricing import router as pricing_router
from app.routers.recurring import router as recurring_router
from app.routers.venue import router as venue_router
from app.services.booking_limit_service import BookingLimitExceededException

app = FastAPI(
    title="Court Booking Service Backend",
    description="Backend API for Court Booking Service with Venue, Court, Hold, Pricing, and Booking Limit Management.",
    version="1.0.0",
)


@app.exception_handler(BookingLimitExceededException)
async def booking_limit_exception_handler(
    request: Request, exc: BookingLimitExceededException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


app.include_router(auth_router)
app.include_router(venue_router)
app.include_router(court_router)
app.include_router(availability_router, prefix="/courts")
app.include_router(hold_router, prefix="/holds")
app.include_router(hold_router, prefix="/api/v1/holds")
app.include_router(pricing_router)
app.include_router(pricing_router, prefix="/api/v1")
app.include_router(member_router, prefix="/members")
app.include_router(member_router, prefix="/api/v1/members")
app.include_router(recurring_router)
app.include_router(recurring_router, prefix="/api/v1")
app.include_router(payment_router, prefix="/payments")
app.include_router(payment_router, prefix="/api/v1/payments")
app.include_router(booking_router, prefix="/bookings")
app.include_router(booking_router, prefix="/api/v1/bookings")
