from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.routers.court import router as court_router
from app.routers.venue import router as venue_router

app = FastAPI(
    title="Court Booking Service Backend",
    description="Backend API for Court Booking Service with Venue and Court Management.",
    version="1.0.0",
)

app.include_router(auth_router)
app.include_router(venue_router)
app.include_router(court_router)
